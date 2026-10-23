"""python scripts/convert_excel.py --original ... --returned ... --output ...csv.gz"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ectlab.data import convert_excel
import argparse
p=argparse.ArgumentParser(description='원본+기업 색상 판정 Excel을 표준 CSV로 변환합니다. 원본은 변경하지 않습니다.')
p.add_argument('--original',required=True); p.add_argument('--returned',required=True); p.add_argument('--output',required=True)
a=p.parse_args(); df=convert_excel(a.original,a.returned,a.output)
print(df.groupby(['position','field_label']).size().to_string()); print('저장:',a.output)
