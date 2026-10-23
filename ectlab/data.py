"""Read-only Excel ingestion, explicit company labels, and portable CSV schema."""
from pathlib import Path
import collections
import hashlib
import posixpath
import re
import zipfile
import numpy as np
import pandas as pd
from lxml import etree as E

COLUMNS = ['date','time','counter','line','product','equipment_label','position','max_value','max_frequency'] + [v for j in range(1,25) for v in [f'freq_{j}',f'x_{j}',f'y_{j}',f'spear_{j}']] + ['part_no']
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def signature(values, skip=(2,)):
    # Counter was annotated by the company; it is not a measurement matching key.
    text = '\x1f'.join(format(v,'.12g') if isinstance(v,(float,int,np.number)) else str(v) for i,v in enumerate(values) if i not in skip)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def read_workbook(path, show_progress=False):
    """Read the supplied 106-column workbook including fills, without Excel or macros.

    This adapter is specific to the supplied two-header-row ECT template. A different
    column layout must be reviewed rather than silently interpreted as this schema.
    """
    path = Path(path); records = []
    with zipfile.ZipFile(path) as z:
        styles = E.fromstring(z.read('xl/styles.xml'))
        fills = []
        for f in styles.find(NS+'fills'):
            fg = f.find('.//'+NS+'fgColor'); fills.append(dict(fg.attrib) if fg is not None else {})
        xf = [int(v.get('fillId','0')) for v in styles.find(NS+'cellXfs')]
        shared = [''.join(si.itertext()) for si in E.fromstring(z.read('xl/sharedStrings.xml'))] if 'xl/sharedStrings.xml' in z.namelist() else []
        rels = {v.get('Id'):v.get('Target') for v in E.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        wb = E.fromstring(z.read('xl/workbook.xml'))
        for sh in wb.find(NS+'sheets'):
            sheet_start = len(records)
            target = rels[sh.get(REL+'id')]
            part = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
            for _, row in E.iterparse(z.open(part), events=('end',), tag=NS+'row'):
                rn = int(row.get('r')); values = [None]*106; marks = collections.defaultdict(set)
                if rn > 2:
                    for c in row:
                        letters = re.match('[A-Z]+',c.get('r')).group(); ci = 0
                        for letter in letters: ci = ci*26+ord(letter)-64
                        ci -= 1
                        if ci >= 106: continue
                        v = c.find(NS+'v'); value = v.text if v is not None else None
                        if c.get('t') == 's' and value is not None: value = shared[int(value)]
                        elif c.get('t') == 'inlineStr': value = ''.join(c.itertext())
                        elif value is not None and c.get('t') not in ['str','e']:
                            try: value = float(value)
                            except ValueError: pass
                        values[ci] = value
                        sid = int(c.get('s','0')); desc = fills[xf[sid]] if sid < len(xf) else {}
                        if value is None: continue
                        rgb = desc.get('rgb','').upper(); theme = desc.get('theme'); tint = float(desc.get('tint','0'))
                        if rgb in ['FFFEFCE8','FFFFFF00','FFFFF2CC']: marks['yellow'].add(letters)
                        if rgb == 'FFFFC000': marks['bright_orange'].add(letters)
                        if rgb == 'FFFFC000' or theme == '7': marks['orange'].add(letters)
                        if theme == '9': marks['green'].add(letters)
                        if theme == '0' and tint < -.1: marks['gray'].add(letters)
                    if values[0] is not None:
                        records.append(dict(zip(COLUMNS,values), source_file=path.name, source_sheet=sh.get('name'), source_row=rn,
                                            yellow_any=bool(marks['yellow']), **{k+'_cells':','.join(sorted(v)) for k,v in marks.items()}))
                row.clear()
                while row.getprevious() is not None: del row.getparent()[0]
            if show_progress: print(f'  {sh.get("name")} 시트: {len(records)-sheet_start:,}행 읽음',flush=True)
    df = pd.DataFrame(records)
    if df.empty: raise ValueError(f'측정 데이터가 없습니다: {path.name}')
    for col in ['orange_cells','bright_orange_cells','green_cells','gray_cells']:
        if col not in df: df[col] = ''
        df[col] = df[col].fillna('')
    if not df.equipment_label.isin(['OK','NG']).all():
        raise ValueError('106컬럼 ECT 형식과 OK/NG 열을 확인하세요. 다른 형식을 자동 추정하지 않습니다.')
    return df

def company_label(row):
    text = str(row['counter'])+' '+str(row['time'])
    if row['gray_cells'] or float(row['max_value']) == 100 or '오류' in text: return 'measurement_error'
    if '마스터' in text: return 'NG_master'
    orange = set(str(row['bright_orange_cells']).split(',')) & {'A','B','F','H'}
    green = set(str(row['green_cells']).split(',')) & {'A','B','F','H'}
    if orange and green: return 'color_conflict'
    if orange: return 'field_true' if row['equipment_label'] == 'NG' else 'color_on_OK_unverified'
    if green: return 'field_false'
    if row['orange_cells']: return 'reference_marker'
    return 'unlabeled'

def convert_excel(original, returned, output):
    """Connect company labels to original rows by measurements; never by row number alone."""
    print('1/4 원본 Excel을 읽습니다. 파일 크기에 따라 수 분 걸릴 수 있습니다.',flush=True)
    old = read_workbook(original,show_progress=True)
    print('2/4 기업 판정 Excel을 읽습니다.',flush=True)
    new = read_workbook(returned,show_progress=True)
    if Path(original).name != Path(returned).name: raise ValueError('같은 품번 파일끼리 연결하세요.')
    print('3/4 측정값을 기준으로 기업 라벨을 연결합니다.',flush=True)
    new['field_label'] = new.apply(company_label,axis=1)
    a = [signature(v) for v in old[COLUMNS].itertuples(index=False,name=None)]
    b = [signature(v) for v in new[COLUMNS].itertuples(index=False,name=None)]
    grouped = collections.defaultdict(list); exact_counts = collections.Counter(a)
    for i,key in enumerate(b): grouped[key].append(i)
    af = [signature(v,(1,2)) for v in old[COLUMNS].itertuples(index=False,name=None)]
    bf = [signature(v,(1,2)) for v in new[COLUMNS].itertuples(index=False,name=None)]
    ac,bc = collections.Counter(af),collections.Counter(bf); fallback = {k:i for i,k in enumerate(bf) if bc[k]==1}
    linked = []
    for i,key in enumerate(a):
        match = grouped.get(key,[]); status = 'exact_unique' if len(match)==1 and exact_counts[key]==1 else 'duplicate_identical_label'
        if not match and ac[af[i]]==1 and bc[af[i]]==1:
            match=[fallback[af[i]]]; status='unique_measurements_time_changed'
        labels = sorted(set(new.iloc[j].field_label for j in match))
        label = labels[0] if len(labels)==1 else 'mapping_label_conflict' if labels else 'unmatched'
        linked.append({'field_label':label,'field_row':','.join(str(int(new.iloc[j].source_row)) for j in match),
                       'field_sheet':','.join(sorted(set(str(new.iloc[j].source_sheet) for j in match))),
                       'mapping_status':status if len(labels)==1 else 'duplicate_conflict' if labels else 'not_found'})
    result = pd.concat([old[COLUMNS+['source_file','source_sheet','source_row','yellow_any']],pd.DataFrame(linked)],axis=1)
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    print('4/4 표준 CSV와 원본 파일 해시를 저장합니다.',flush=True)
    result.to_csv(output,index=False,encoding='utf-8-sig')
    import json
    output.with_name(output.name+'.provenance.json').write_text(json.dumps({'original_sha256':file_hash(original),'returned_sha256':file_hash(returned),
        'original_rows':len(old),'returned_rows':len(new),'matching':result.mapping_status.value_counts().to_dict(),
        'labels':result.field_label.value_counts().to_dict()},ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def load_csv(path):
    """CSV is a measurement-row table. No position merging or unsafe pickle loading."""
    df = pd.read_csv(path,dtype={'source_sheet':str,'field_sheet':str},low_memory=False)
    required = COLUMNS+['source_file','source_sheet','source_row','yellow_any','field_label']
    missing = sorted(set(required)-set(df))
    if missing: raise ValueError(f'필수 CSV 컬럼 누락: {missing}')
    if df.source_file.nunique()!=1: raise ValueError('한 번에 한 품번만 입력하세요.')
    df['position']=pd.to_numeric(df.position,errors='raise').astype(int)
    if not df.position.isin([1,2]).all(): raise ValueError('위치는 1/2만 허용합니다.')
    if not df.equipment_label.isin(['OK','NG']).all(): raise ValueError('설비 판정은 OK/NG만 허용합니다.')
    df['date']=pd.to_datetime(df.date,errors='raise').dt.strftime('%Y-%m-%d')
    df['yellow_any']=df.yellow_any.astype(str).str.lower().map({'true':True,'false':False,'1':True,'0':False})
    if df.yellow_any.isna().any(): raise ValueError('yellow_any는 True/False 값이어야 합니다.')
    for col in ['max_value']+[f'{a}_{j}' for j in range(1,25) for a in ['x','y']]: df[col]=pd.to_numeric(df[col],errors='coerce')
    labels={'NG_master','field_true','field_false','measurement_error','unlabeled','reference_marker','color_on_OK_unverified','color_conflict','mapping_label_conflict','unmatched'}
    if not df.field_label.isin(labels).all(): raise ValueError('field_label 코드가 가이드와 다릅니다.')
    df['id']=df.source_file.str.replace(r'\.xlsx$','',regex=True)+'|'+df.source_sheet+'|'+df.source_row.astype(str)+'|p'+df.position.astype(str)
    if df.id.duplicated().any(): raise ValueError('같은 원본 파일/시트/행/위치가 중복되었습니다. 중복 추가를 확인하세요.')
    df['event_group']=df.date.astype(str)+'|'+df.counter.astype(str)
    return df

def feature_schema(rows):
    """Verify every slot's frequency across all rows, not only the first sample."""
    features=[]
    for slot in range(1,25):
        freqs=rows[f'freq_{slot}'].astype(str).str.replace(r'^\d+x','',regex=True)
        if freqs.nunique()!=1: raise ValueError(f'위치 {rows.position.iloc[0]} 슬롯{slot} 주파수가 바뀌었습니다. 설비 조건별로 CSV를 분리하세요.')
        frequency=freqs.iloc[0]
        if frequency in ['0','0.0','None','nan']: continue
        for axis in ['x','y']: features.append({'column':f'{axis}_{slot}','block':(slot-1)//8+1,'frequency':frequency,'axis':axis})
    if not features: raise ValueError('활성 X/Y 측정값이 없습니다.')
    return features

def inventory(df):
    rows=[]
    for pos,g in df.groupby('position'):
        features=feature_schema(g)
        rows.append({'위치':pos,'측정행':len(g),'시작일':g.date.min(),'종료일':g.date.max(),'X/Y 입력수':len(features),
                     '설비 OK':int(g.equipment_label.eq('OK').sum()),'설비 NG':int(g.equipment_label.eq('NG').sum()),
                     '기업 진성':int(g.field_label.eq('field_true').sum()),'기업 가성':int(g.field_label.eq('field_false').sum()),
                     'NG 마스터':int(g.field_label.eq('NG_master').sum()),'0/노랑':int((g.yellow_any|g.max_value.eq(0)).sum()),
                     '측정 오류':int(g.field_label.eq('measurement_error').sum())})
    return pd.DataFrame(rows)
