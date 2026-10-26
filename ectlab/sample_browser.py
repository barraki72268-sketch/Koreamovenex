"""One sample browser for legacy labelled CSVs and the new delivery formats."""
from pathlib import Path
import html,json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from ectlab.pipeline import evenly_sample


def load_sample_matrix(folder,entry,rows):
    folder=Path(folder)/entry.get('source_folder','')
    if entry['profile']=='legacy':
        raw=pd.read_csv(Path(folder)/'기존입력.csv.gz',low_memory=False)
        raw=raw[raw.position.eq(entry['position'])]
        raw=raw.set_index(['source_sheet','source_row'])
        return raw[entry['features']].reindex(pd.MultiIndex.from_frame(rows[['원본시트','원본행']])).to_numpy(float)
    from ectlab.delivery import feature_frame
    raw=pd.read_csv(Path(folder)/'변환CSV'/(entry['profile']+'_raw.csv.gz'),low_memory=False)
    raw=raw[raw.c3.astype(str).eq(entry['line'])&raw.c4.astype(str).eq(entry['product'])&raw.c6.eq(entry['position'])].reset_index(drop=True)
    matrix,_=feature_frame(raw,entry['profile'])
    matrix.index=pd.MultiIndex.from_frame(raw[['source_sheet','source_row']])
    return matrix[entry['features']].reindex(pd.MultiIndex.from_frame(rows[['원본시트','원본행']])).to_numpy(float)


def comparison_figure(rows,entry):
    from ectlab.plots import style
    style();fig,axes=plt.subplots(2,2,figsize=(12,9))
    kinds=np.where(rows.MASTER여부,'MASTER',np.where(rows.설비판정.eq('OK'),'설비 OK','일반 NG (미확정)'))
    for ax,(x,y,title) in zip(axes.ravel(),[('PC1','PC2','전체 범위'),('PC1','PC2','OK 밀집 구간 확대'),('PC1','PC3','다른 방향: PC1–PC3'),('PC2','PC3','다른 방향: PC2–PC3')]):
        for name,color,marker in [('설비 OK','#8C9DAF','o'),('일반 NG (미확정)','#DF952F','o'),('MASTER','#7951B0','*')]:
            ids=np.flatnonzero((kinds==name)&rows[x].notna()&rows[y].notna())
            shown=evenly_sample(ids,2000)
            ax.scatter(rows.iloc[shown][x],rows.iloc[shown][y],s=120 if name=='MASTER' else 14,marker=marker,c=color,alpha=.9 if name=='MASTER' else .5,label=f'{name} ({len(ids)}행)')
        if '확대' in title:
            ok=rows[rows.설비판정.eq('OK')&~rows.MASTER여부&rows.PC1.notna()]
            if len(ok)>=3:
                bounds=[]
                for col in (x,y):
                    lo,hi=ok[col].quantile([.005,.995]);pad=max((hi-lo)*.15,.01)
                    bounds.append((lo-pad,hi+pad))
                ax.set_xlim(*bounds[0]);ax.set_ylim(*bounds[1])
                inside=rows[x].between(*bounds[0])&rows[y].between(*bounds[1])
                title+=f'\n확대 화면 밖: {int((~inside&rows.PC1.notna()).sum())}행 · 전체 범위는 왼쪽'
        if not rows[y].notna().any():ax.text(.5,.5,'사용 가능한 세 번째 주성분 없음',ha='center',transform=ax.transAxes)
        ax.set(title=title,xlabel=x,ylabel=y);ax.legend(fontsize=7);ax.grid(alpha=.15)
    fig.suptitle(f'{entry["line"]} / 위치 {entry["position"]} / {entry["condition"]}\n같은 데이터의 다른 방향과 확대 보기 · 분류 정확도 아님')
    fig.tight_layout();return fig


def tsne_figure(folder,rows,entry):
    from sklearn.manifold import TSNE
    from sklearn.preprocessing import RobustScaler
    from sklearn.decomposition import PCA
    valid=rows.분석가능&rows.PC1.notna()
    normal=valid&rows.설비판정.eq('OK')&~rows.MASTER여부
    selected=np.unique(np.r_[evenly_sample(np.flatnonzero(normal),1000),evenly_sample(np.flatnonzero(valid&~normal),1000)])
    if len(selected)<5:raise ValueError('t-SNE에는 유효 샘플이 5행 이상 필요합니다.')
    active=rows.iloc[selected].reset_index(drop=True)
    X=load_sample_matrix(folder,entry,active)
    if not np.isfinite(X).all():raise ValueError('선택한 특징에 결측값이 있습니다.')
    X=RobustScaler().fit_transform(X)
    if X.shape[1]>30:X=PCA(n_components=min(30,len(X)-1),random_state=42).fit_transform(X)
    embedding=TSNE(n_components=2,perplexity=min(30,(len(X)-1)/3),init='pca',learning_rate='auto',max_iter=750,random_state=42,n_jobs=2).fit_transform(X)
    fig,ax=plt.subplots(figsize=(8,6));kinds=np.where(active.MASTER여부,'MASTER',np.where(active.설비판정.eq('OK'),'설비 OK','일반 NG (미확정)'))
    for name,color,marker in [('설비 OK','#8C9DAF','o'),('일반 NG (미확정)','#DF952F','o'),('MASTER','#7951B0','*')]:
        ix=kinds==name;ax.scatter(embedding[ix,0],embedding[ix,1],c=color,marker=marker,s=120 if name=='MASTER' else 18,label=f'{name} ({int(ix.sum())}행)',alpha=.8)
    ax.set(title=f'{entry["line"]} / 위치 {entry["position"]} · t-SNE 탐색\n표시 {len(active)}행 / 전체 {len(rows)}행 · seed 42 · 그림상 거리는 불량 확률이 아님',xlabel='t-SNE 1',ylabel='t-SNE 2');ax.legend();fig.tight_layout()
    active['TSNE1']=embedding[:,0];active['TSNE2']=embedding[:,1]
    return fig,active


def show_sample_browser(result):
    import ipywidgets as w
    from IPython.display import display,HTML,clear_output
    folder=Path(result['folder'])
    entries=json.loads((folder/'샘플결과_목록.json').read_text(encoding='utf-8'))['entries']
    pick=w.Dropdown(options=[(f'{e.get("dataset",e["profile"])} / {e["line"]} / {e["product"]} / 위치 {e["position"]} / {e["condition"]}',i) for i,e in enumerate(entries)],description='결과 선택:',layout=w.Layout(width='98%'))
    kind=w.Dropdown(options=['일반 NG','MASTER','설비 OK','제외행','전체'],description='볼 샘플:')
    search=w.Text(description='검색:',placeholder='날짜, 검사번호, 원본 행, 샘플ID')
    page=w.BoundedIntText(value=1,min=1,max=1,description='페이지:')
    select=w.Dropdown(description='샘플 선택:',layout=w.Layout(width='98%'))
    listing=w.Output();detail=w.Output();views=w.Output()
    alt=w.Button(description='다른 PCA 축 · 확대 보기',icon='search')
    nonlinear=w.Button(description='t-SNE 비교 (선택 실행)',icon='area-chart')
    state={'rows':None,'entry':None}

    def show_detail(*_):
        with detail:
            clear_output(wait=True)
            if select.value is None or state['rows'] is None:return
            row=state['rows'].iloc[int(select.value)]
            display(HTML('<h4>선택 샘플: '+html.escape(str(row['샘플ID']))+'</h4>'))
            display(row.to_frame('값'))
            display(HTML('<p>거리: 작을수록 해당 기준과 비슷합니다. 자기 자신과의 거리는 제외했습니다. 현장판정과 모델 점수는 별개입니다. 미계산은 가성 판정이 아닙니다.</p>'))

    def render(*_):
        rows=state['rows']
        if rows is None:return
        mask=np.ones(len(rows),bool)
        if kind.value=='일반 NG':mask=rows.설비판정.eq('NG')&~rows.MASTER여부
        elif kind.value=='MASTER':mask=rows.MASTER여부
        elif kind.value=='설비 OK':mask=rows.설비판정.eq('OK')&~rows.MASTER여부
        elif kind.value=='제외행':mask=~rows.분석가능
        if search.value.strip():
            text=rows[['샘플ID','원본날짜','시간','검사번호','원본행']].astype(str).agg(' | '.join,axis=1)
            mask=mask&text.str.contains(search.value.strip(),case=False,regex=False)
        filtered=rows[mask];page.max=max(1,int(np.ceil(len(filtered)/50)))
        shown=filtered.iloc[(page.value-1)*50:page.value*50]
        with listing:
            clear_output(wait=True)
            display(HTML(f'<p>검색 결과 {len(filtered):,}행 · 페이지 {page.value}/{page.max} · 50행씩 표시. CSV에는 제외행까지 전체가 저장됩니다.</p>'))
            cols=[c for c in ['샘플ID','원본날짜','시간','검사일','설비판정','현장판정','분석가능','NG_MASTER거리','OK거리','거리참고','기존거리판정','기존MASTER거리비율','기존OK거리비율','RF점수','RF결과','XGBoost점수','XGBoost결과'] if c in shown]
            display(shown[cols])
        select.options=[(str(row['원본날짜'])+' '+str(row['시간'])+' / 원본행 '+str(row['원본행'])+' / '+str(row['설비판정']),int(i)) for i,row in shown.iterrows()]
        if len(shown):select.value=int(shown.index[0])
        else:
            select.options=[]
            detail.clear_output()
        show_detail()

    def load(*_):
        entry=entries[pick.value];state['entry']=entry
        state['rows']=pd.read_csv(folder/entry['file'],low_memory=False)
        page.value=1;views.clear_output();render()

    def explain(tsne=False):
        alt.disabled=nonlinear.disabled=True
        with views:
            clear_output(wait=True)
            try:
                entry=state['entry'];rows=state['rows'];stem=Path(entry['file']).name.removesuffix('.csv.gz')
                if entry.get('source_folder'):
                    import hashlib
                    stem=hashlib.sha256(entry['file'].encode()).hexdigest()[:10]+'_'+stem
                if tsne:
                    print('같은 입력 측정값으로 t-SNE를 계산합니다. 표본을 줄여 탐색하며 최종 판정용이 아닙니다.')
                    fig,coordinates=tsne_figure(folder,rows,entry)
                    coordinates.to_csv(folder/(stem+'_tSNE.csv'),index=False,encoding='utf-8-sig');suffix='_tSNE.png'
                else:fig=comparison_figure(rows,entry);suffix='_PCA확대와다른축.png'
                fig.savefig(folder/(stem+suffix),dpi=140,bbox_inches='tight');display(fig);plt.close(fig)
                display(HTML('<p>다른 축과 확대는 같은 데이터를 보여줍니다. 확대에서 화면 밖인 점은 삭제한 것이 아닙니다. t-SNE의 덩어리나 거리를 실제 진성·가성 정확도로 해석하지 않습니다.</p>'))
                if result.get('refresh_download'):result['refresh_download']()
            except Exception as exc:print('확인:',str(exc))
            finally:alt.disabled=nonlinear.disabled=False

    pick.observe(load,names='value');kind.observe(render,names='value');search.observe(render,names='value');page.observe(render,names='value');select.observe(show_detail,names='value')
    alt.on_click(lambda _:explain(False));nonlinear.on_click(lambda _:explain(True))
    detailbox=w.Accordion(children=[detail]);detailbox.set_title(0,'선택 샘플 상세 · 점수 / 거리 / 학습 포함 여부');detailbox.selected_index=None
    app=w.VBox([w.HTML('<h3>샘플별 결과와 거리 확인</h3><p>결과 조건과 NG/MASTER/OK를 고르고, 날짜·검사번호·원본 행으로 검색하세요. RF·XGBoost 결과는 모델 비교를 실행했을 때 표시됩니다.</p>'),pick,w.HBox([alt,nonlinear]),views,w.HBox([kind,page]),search,listing,select,detailbox])
    display(app)
    if entries:load()
    return {'app':app,'state':state,'pick':pick,'kind':kind,'search':search,'select':select,'page':page,'alt':alt,'tsne':nonlinear}
