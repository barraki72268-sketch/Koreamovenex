"""Stream the supported ECT workbooks to CSV without retaining every cell in RAM."""
from pathlib import Path
from zipfile import ZipFile
from lxml import etree as E
import csv,gzip,json,posixpath,re
from ectlab.data import file_hash
N='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def convert_workbook(profile,input_path,output,on_progress=None):
    if profile not in ('crack','shaft'):raise ValueError('크랙 또는 샤프트를 선택하세요.')
    dest=Path(output).resolve();dest.mkdir(parents=True,exist_ok=True)
    path=Path(input_path).resolve();width=78 if profile=='crack' else 106
    csv_path=dest/(profile+'_raw.csv.gz')
    fields=['c'+str(i) for i in range(width)]+['source_file','source_sheet','source_row','fill_descriptors']
    meta=[];inventory=[];total=0;pattern=re.compile('마스터|MASTER',re.I)
    with ZipFile(path) as book, gzip.open(csv_path,'wt',encoding='utf-8',newline='',compresslevel=3) as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        shared=[''.join(si.itertext()) for si in E.fromstring(book.read('xl/sharedStrings.xml'))] if 'xl/sharedStrings.xml' in book.namelist() else []
        rels={v.get('Id'):v.get('Target') for v in E.fromstring(book.read('xl/_rels/workbook.xml.rels'))}
        styles=E.fromstring(book.read('xl/styles.xml'))
        fills=[dict(fg.attrib) if (fg:=fill.find('.//'+N+'fgColor')) is not None else {} for fill in styles.find(N+'fills')]
        xf=[int(v.get('fillId','0')) for v in styles.find(N+'cellXfs')]
        style_colors=[json.dumps(fills[i],sort_keys=True) if fills[i] else '' for i in xf]
        columns={}
        for sheet in E.fromstring(book.read('xl/workbook.xml')).find(N+'sheets'):
            title=sheet.get('name');target=rels[sheet.get(R+'id')]
            part=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
            headers=[];count=0;groups={}
            if on_progress:on_progress(('크랙' if profile=='crack' else '샤프트')+' Excel 읽는 중 · '+title)
            for _,row in E.iterparse(book.open(part),events=('end',),tag=N+'row'):
                rn=int(row.get('r'));values={};colors=set()
                # Styled empty rows do not contribute to the original date-keyed dataset.
                first=row.find(N+'c[@r="A'+str(rn)+'"]')
                active=rn<=2 or (first is not None and (first.find(N+'v') is not None or first.get('t')=='inlineStr'))
                if active:
                    for cell in row:
                        v=cell.find(N+'v');value=v.text if v is not None else None
                        kind=cell.get('t')
                        if kind=='s' and value is not None:value=shared[int(value)]
                        elif kind=='inlineStr':value=''.join(cell.itertext())
                        elif value is not None and kind not in ('str','e'):
                            try:value=float(value)
                            except ValueError:pass
                        if value is None:continue
                        letters=cell.get('r').rstrip('0123456789');column=columns.get(letters)
                        if column is None:
                            ci=0
                            for letter in letters:ci=ci*26+ord(letter)-64
                            column='c'+str(ci-1);columns[letters]=column
                        values[column]=value
                        color=style_colors[int(cell.get('s','0'))]
                        if color:colors.add(color)
                    if rn==1:
                        marker=str(values.get('c9','')).strip().upper()
                        if marker!=('TRANSM FRQ' if profile=='crack' else 'FRQ 1'):
                            raise ValueError('지원하는 크랙/샤프트 열 배치가 아닙니다: '+title)
                    if rn<=2:headers.append(values)
                    elif values.get('c0') is not None:
                        label=values.get('c5')
                        if label not in ('OK','NG'):raise ValueError('설비 OK/NG 열을 확인하세요: '+title+' / '+str(rn)+'행')
                        record=dict(values,source_file=path.name,source_sheet=title,source_row=rn,fill_descriptors=';'.join(sorted(colors)))
                        writer.writerow(record);count+=1;total+=1
                        key=values.get('c6')
                        if key not in groups:
                            groups[key]={'sheet':title,'position':key,'rows':0,'OK':0,'NG':0,'zero':0,'max100':0,'first':{k:values.get(k) for k in ('c0','c1','c2','c5','c7')},'master_text':0}
                        g=groups[key];g['rows']+=1;g[label]+=1
                        g['zero']+=int(values.get('c7')==0);g['max100']+=int(values.get('c7')==100)
                        g['master_text']+=int(any(pattern.search(value) for value in record.values() if isinstance(value,str)))
                row.clear()
                while row.getprevious() is not None:del row.getparent()[0]
            meta.append({'sheet':title,'headers':headers,'rows':count});inventory.extend(groups.values())
            print(profile,title,count,flush=True)
    if not total:raise ValueError('측정행이 없습니다: '+path.name)
    (dest/(profile+'_schema.json')).write_text(json.dumps({'source':path.name,'sha256':file_hash(path),'fills':fills,'sheets':meta},ensure_ascii=False,indent=2),encoding='utf-8')
    (dest/(profile+'_inventory.json')).write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    print(profile,'변환 완료:',total,'행',flush=True)
    return csv_path


def main():
    import argparse
    parser=argparse.ArgumentParser(description='크랙·샤프트 Excel을 원본 변경 없이 변환합니다.')
    parser.add_argument('--crack');parser.add_argument('--shaft');parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if not args.crack and not args.shaft:parser.error('--crack 또는 --shaft 파일이 필요합니다.')
    for profile,path in [('crack',args.crack),('shaft',args.shaft)]:
        if path:convert_workbook(profile,path,args.output)

if __name__=='__main__':main()
