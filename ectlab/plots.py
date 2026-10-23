"""Plain-language notebook charts. Training PCA is visualization only, not a new classifier."""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from .pipeline import summarize, evenly_sample

COLORS={'OK':'#96A9BD','NG_master':'#7552B5','field_false':'#249A78','field_true':'#E26332','unlabeled':'#DCB437'}
LABELS={'OK':'설비 OK','NG_master':'NG 마스터','field_false':'기업 가성','field_true':'기업 진성','unlabeled':'판정 미확인 NG'}

def style():
    from matplotlib import font_manager
    candidates=['Malgun Gothic','NanumGothic','Noto Sans CJK KR','Noto Sans KR']
    installed={f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in installed: plt.rcParams['font.family']=name; break
    plt.rcParams.update({'axes.unicode_minus':False,'figure.dpi':115,'font.size':11,'axes.spines.top':False,'axes.spines.right':False})

def pca_plot(packs):
    style(); fig,axes=plt.subplots(1,len(packs),figsize=(7*len(packs),5.6),squeeze=False)
    for ax,(pos,p) in zip(axes[0],packs.items()):
        r,X=p['rows'],p['X']; train=np.flatnonzero(r.normal&r.role.eq('train'))
        med=np.median(X[train],0); scale=np.quantile(X[train],.75,axis=0)-np.quantile(X[train],.25,axis=0); scale=np.where(scale<=1e-6,1,scale)
        Z=(X-med)/scale; mu=Z[train].mean(0); eig,V=np.linalg.eigh(np.atleast_2d(np.cov(Z[train],rowvar=False))); order=np.argsort(eig)[::-1]; eig=np.maximum(eig[order],0); V=V[:,order]
        xy=(Z-mu)@V[:,:2]
        groups={'OK':evenly_sample(np.flatnonzero(r.normal&r.role.eq('calibration')),400),
                'NG_master':np.flatnonzero(r.eligible&r.field_label.eq('NG_master')),
                'field_false':np.flatnonzero(r.NG_query&r.field_label.eq('field_false')),
                'unlabeled':np.flatnonzero(r.NG_query&r.field_label.isin(['unlabeled','reference_marker'])),
                'field_true':np.flatnonzero(r.NG_query&r.field_label.eq('field_true'))}
        for label,idx in groups.items():
            if not len(idx): continue
            ax.scatter(xy[idx,0],xy[idx,1],s=110 if label=='field_true' else 40 if label=='NG_master' else 18,
                       marker='*' if label=='field_true' else 'D' if label=='NG_master' else 'o',color=COLORS[label],alpha=.85 if label!='OK' else .35,label=f'{LABELS[label]} ({len(idx)}행)')
        variance=eig[:2].sum()/max(eig.sum(),1e-12)
        ax.set(title=f'위치 {pos} | PCA 2차원 설명 비율 {variance:.1%}',xlabel='PC1: 주요 변화 방향 1',ylabel='PC2: 주요 변화 방향 2')
        ax.legend(fontsize=9); ax.grid(alpha=.15)
    fig.suptitle('X/Y 여러 입력값을 두 축으로 줄여서 본 분포\n점의 색은 기업 판정 / 그림에서의 거리만으로 최종 판정하지 않습니다',fontsize=13)
    fig.tight_layout(); return fig

def comparison_plot(predictions, temporal=False):
    style(); summary=summarize(predictions)
    scope='시험 날짜 NG' if temporal else '전체 NG: 학습 포함'
    table=summary[summary['비교 구간'].eq(scope)&summary['학습 방식'].isin(['distance','master_proxy'])]
    fig,axes=plt.subplots(1,2,figsize=(14,5.8))
    for ax,pos in zip(axes,[1,2]):
        g=table[table['위치'].eq(pos)]; yy=np.arange(len(g)); left=np.zeros(len(g))
        for col,color in [('가성 후보','#249A78'),('가성 보류','#D6A437'),('가성을 진성 의심으로','#D96343')]:
            v=g[col].to_numpy(); ax.barh(yy,v,left=left,label=col,color=color,height=.6)
            for i,n in enumerate(v):
                if n: ax.text(left[i]+n/2,i,str(n),ha='center',va='center',color='white' if col!='가성 보류' else '#222',fontweight='bold')
            left+=v
        ax.set_yticks(yy,g['모델']); ax.invert_yaxis(); ax.set(title=f'위치 {pos} | 기업 가성 {int(g["가성 행"].max()) if len(g) else 0}행',xlabel='측정행 수'); ax.grid(axis='x',alpha=.15)
    handles,labels=axes[0].get_legend_handles_labels(); fig.legend(handles,labels,loc='lower center',ncol=3,frameon=False)
    fig.suptitle(f'{scope} — 가성 구분과 보류 수\n'+('시험 날짜에 기업 진성이 없으므로 진성 검출률은 평가할 수 없습니다.' if temporal else '전체 수량은 학습에 사용한 행을 포함합니다. 독립 성능으로 해석하지 마세요.'),fontsize=13)
    fig.tight_layout(rect=(0,.08,1,.91)); return fig

def true_case_plot(predictions):
    style(); f=predictions[predictions.field_label.eq('field_true')&predictions.experiment.eq('master_proxy')].copy()
    fig,ax=plt.subplots(figsize=(11,4.8))
    if f.empty:
        ax.text(.5,.5,'비교 가능한 기업 진성 행이 없습니다.',ha='center',va='center',transform=ax.transAxes); return fig
    labels=[]; colors=[]
    for _,row in f.iterrows():
        labels.append(f'위치{row.position} / {row.model} / 원본행{row.source_row}')
        colors.append('#D96343' if row.decision=='true_suspect' else '#D6A437' if row.decision=='review' else '#249A78')
    ax.barh(np.arange(len(f)),f.positive_score,color=colors)
    for i,v in enumerate(f.positive_score): ax.text(min(v+.015,.95),i,f'{v:.3f}',va='center')
    ax.axvline(.1,color='#249A78',ls='--'); ax.axvline(.9,color='#D96343',ls='--')
    ax.set_yticks(np.arange(len(f)),labels); ax.invert_yaxis(); ax.set_xlim(0,1.08)
    ax.set(title='마스터 기반 모델에서 기업 진성 행의 점수\n진성 행을 학습에서 제외한 비교 / 같은 날짜·사건의 사후 확인',xlabel='모델 출력 점수 — 실제 불량 확률이 아닙니다')
    fig.tight_layout(); return fig

def frequency_plot(packs,position=2,block=1,frequency='30.0Hz'):
    style(); p=packs[position]; r,X=p['rows'],p['X']
    indices=[i for i,f in enumerate(p['features']) if f['block']==block and f['frequency']==frequency]
    if len(indices)!=2: raise ValueError('선택한 위치/블록/주파수에 X/Y 쌍이 없습니다.')
    fig,ax=plt.subplots(figsize=(8.5,5.6))
    for label in ['OK','NG_master','field_false','field_true']:
        mask=r.normal&r.role.eq('calibration') if label=='OK' else r.eligible&r.field_label.eq(label)
        idx=evenly_sample(np.flatnonzero(mask),500) if label=='OK' else np.flatnonzero(mask)
        if len(idx): ax.scatter(X[idx,indices[0]],X[idx,indices[1]],s=130 if label=='field_true' else 26,marker='*' if label=='field_true' else 'o',alpha=.8 if label!='OK' else .3,color=COLORS[label],label=f'{LABELS[label]} ({len(idx)}행)')
    ax.set(title=f'위치 {position} / 블록 {block} / {frequency} 원래 X/Y 값',xlabel='X 측정값',ylabel='Y 측정값'); ax.legend(); ax.grid(alpha=.15); fig.tight_layout(); return fig
