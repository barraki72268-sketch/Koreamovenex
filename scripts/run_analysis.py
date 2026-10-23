"""Optional command-line equivalent of the notebook. No company data defaults."""
from pathlib import Path
import sys, argparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ectlab.data import load_csv, inventory
from ectlab.pipeline import Settings,prepare,distance_analysis,train_models,export_run
from ectlab.plots import pca_plot,comparison_plot,true_case_plot
import pandas as pd
p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',default='results');p.add_argument('--train-end',default='2026-08-20');p.add_argument('--calibration-end',default='2026-10-07')
a=p.parse_args(); df=load_csv(a.input); print(inventory(df).to_string(index=False))
s=Settings(train_end=a.train_end,calibration_end=a.calibration_end);packs,counts=prepare(df,s);print(counts.to_string(index=False))
d=distance_analysis(packs);m=train_models(packs);pred=pd.concat([d['predictions'],m['predictions']],ignore_index=True)
figures={'01_PCA_위치별_분포':pca_plot(packs),'02_전체NG_가성구분':comparison_plot(pred),'03_시험날짜_가성구분':comparison_plot(pred,True),'04_진성행_점수':true_case_plot(pred)}
export_run(a.output,a.input,s,packs,d,m,figures)
