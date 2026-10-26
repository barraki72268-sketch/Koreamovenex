from pathlib import Path
from zipfile import ZipFile
from lxml import etree as E
import json,posixpath,re,sys
import pandas as pd
from ectlab.data import file_hash
N='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

def convert_workbook(profile, input_path, output, on_progress=None):
 if profile not in ('crack','shaft'):raise ValueError('크랙 또는 샤프트를 선택하세요.')
 dest=Path(output).resolve();dest.mkdir(parents=True,exist_ok=True)
 p=Path(input_path).resolve();filename=p.name
 records=[];meta=[]
 with ZipFile(p) as z:
  shared=[''.join(si.itertext()) for si in E.fromstring(z.read('xl/sharedStrings.xml'))] if 'xl/sharedStrings.xml' in z.namelist() else []
  rels={v.get('Id'):v.get('Target') for v in E.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
  styles=E.fromstring(z.read('xl/styles.xml'))
  fills=[dict(fg.attrib) if (fg:=f.find('.//'+N+'fgColor')) is not None else {} for f in styles.find(N+'fills')]
  xf=[int(v.get('fillId','0')) for v in styles.find(N+'cellXfs')]
  style_colors=[json.dumps(fills[i],sort_keys=True) if fills[i] else '' for i in xf]
  columns={}
  for sh in E.fromstring(z.read('xl/workbook.xml')).find(N+'sheets'):
   target=rels[sh.get(R+'id')];part=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
   headers=[];start=len(records)
   if on_progress:on_progress(('크랙' if profile=='crack' else '샤프트')+' Excel 읽는 중 · '+str(sh.get('name')))
   for _,row in E.iterparse(z.open(part),events=('end',),tag=N+'row'):
    rn=int(row.get('r'));values={};colors=set()
    for c in row:
     letters=c.get('r').rstrip('0123456789');column=columns.get(letters)
     if column is None:
      ci=0
      for letter in letters:ci=ci*26+ord(letter)-64
      column='c'+str(ci-1);columns[letters]=column
     v=c.find(N+'v');val=v.text if v is not None else None
     if c.get('t')=='s' and val is not None:val=shared[int(val)]
     elif c.get('t')=='inlineStr':val=''.join(c.itertext())
     elif val is not None and c.get('t') not in ['str','e']:
      try:val=float(val)
      except ValueError:pass
     if val is not None:
      values[column]=val
      color=style_colors[int(c.get('s','0'))]
      if color:colors.add(color)
    if rn==1:
     marker=str(values.get('c9','')).strip().upper()
     if (profile=='crack' and marker!='TRANSM FRQ') or (profile=='shaft' and marker!='FRQ 1'):
      raise ValueError('이 변환기가 지원하는 크랙/샤프트 열 배치가 아닙니다: '+str(sh.get('name')))
    if rn<=2:headers.append(values)
    elif values.get('c0') is not None:
     records.append(dict(values,source_file=filename,source_sheet=sh.get('name'),source_row=rn,fill_descriptors=';'.join(sorted(colors))))
    row.clear()
    while row.getprevious() is not None:del row.getparent()[0]
   meta.append({'sheet':sh.get('name'),'headers':headers,'rows':len(records)-start})
   print(profile,sh.get('name'),len(records)-start,flush=True)
 df=pd.DataFrame(records)
 if df.empty or not df.c5.isin(['OK','NG']).all():raise ValueError('측정행과 설비 OK/NG 열을 확인하세요: '+filename)
 df.to_csv(dest/(profile+'_raw.csv.gz'),index=False)
 (dest/(profile+'_schema.json')).write_text(json.dumps({'source':filename,'sha256':file_hash(p),'fills':fills,'sheets':meta},ensure_ascii=False,indent=2),encoding='utf-8')
 summary=[]
 for key,g in df.groupby(['source_sheet','c6'],dropna=False):
  first=g.sort_values('source_row').iloc[0]
  summary.append({'sheet':key[0],'position':key[1],'rows':len(g),'OK':int(g.c5.eq('OK').sum()),'NG':int(g.c5.eq('NG').sum()),'zero':int(g.c7.eq(0).sum()),'max100':int(g.c7.eq(100).sum()),'first':first[['c0','c1','c2','c5','c7']].to_dict(),'master_text':int(g.astype(str).apply(lambda s:s.str.contains('마스터|MASTER',case=False,regex=True)).any(axis=1).sum())})
 (dest/(profile+'_inventory.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(profile, "변환 완료:", len(df), "행", flush=True)
 return df


def main():
 import argparse
 parser=argparse.ArgumentParser(description='크랙·샤프트 Excel을 원본 변경 없이 변환합니다.')
 parser.add_argument('--crack')
 parser.add_argument('--shaft')
 parser.add_argument('--output',required=True)
 args=parser.parse_args()
 if not args.crack and not args.shaft:parser.error('--crack 또는 --shaft 파일이 필요합니다.')
 for profile,input_path in [('crack',args.crack),('shaft',args.shaft)]:
  if input_path:convert_workbook(profile,input_path,args.output)

if __name__=='__main__':main()
