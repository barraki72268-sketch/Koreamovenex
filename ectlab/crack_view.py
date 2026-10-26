"""Show a verified, source-bound GPU experiment only for the matching crack file."""
from pathlib import Path
import json,shutil,html,re
import numpy as np
import pandas as pd
from ectlab.data import file_hash

CACHE='크랙_TabICLv2_결과'


def attach_crack_view(result,root,source,start_hour=6):
    folder=Path(result['folder']);cache=Path(root)/'notebooks'/CACHE
    view={'status':'unavailable','message':'현재 파일의 TabICLv2 GPU 결과가 없어 원본 PCA·t-SNE를 표시합니다. 새 GPU 실험이 필요합니다.','groups':[]}
    result['tabicl_view']=view
    if not (cache/'manifest.json').is_file():return view
    try:
        manifest=json.loads((cache/'manifest.json').read_text(encoding='utf-8'))
        if manifest['source_sha256']!=file_hash(source):
            view.update(status='source_mismatch',message='새 크랙 파일이므로 이전 TabICLv2 결과를 재사용하지 않습니다. 원본 PCA·t-SNE를 표시합니다.');return view
        if manifest['crack_day_start_hour']!=start_hour:
            view.update(status='boundary_mismatch',message='검사일 경계가 GPU 실험과 달라 저장된 TabICLv2 결과를 사용하지 않습니다. 원본 그림을 표시합니다.');return view
        for name,digest in manifest['files'].items():
            path=Path(name)
            if path.is_absolute() or '..' in path.parts:raise ValueError('GPU 결과 경로 오류')
            if not (cache/path).is_file() or file_hash(cache/path)!=digest:raise ValueError('GPU 결과 파일 해시 불일치: '+name)
        for group in manifest['groups']:
            if group['status']=='ready':
                for key in ('plot','scores_default','scores_preserve'):
                    if group[key] not in manifest['files']:raise ValueError('GPU 결과 목록에 없는 파일')
                if group.get('comparison_plot') and group['comparison_plot'] not in manifest['files']:raise ValueError('GPU 대조 그림 목록 확인 필요')
        for key in ('summary_plot','summary_csv'):
            if manifest[key] not in manifest['files']:raise ValueError('GPU 요약 목록 확인 필요')
    except Exception as exc:
        view.update(status='invalid',message='저장된 GPU 결과를 검증하지 못해 원본 그림을 표시합니다: '+str(exc));return view
    target=folder/'TabICLv2_저장GPU결과';target.mkdir(exist_ok=True)
    for name in manifest['files']:
        p=target/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(cache/name,p)
    shutil.copyfile(cache/'manifest.json',target/'manifest.json')
    groups=[]
    for group in manifest['groups']:
        item=dict(group)
        if item['status']=='ready':
            stem=re.sub(r'[^\w가-힣.-]+','_',str(item['line'])+'_'+str(item['product'])+'_위치'+str(item['position']))
            primary=folder/('TabICLv2_'+stem+'_PCA.png');shutil.copyfile(cache/item['plot'],primary)
            item['display_file']=str(primary)
            if item.get('comparison_plot'):
                comparison=folder/('TabICLv2_'+stem+'_원본대조_PCA.png');shutil.copyfile(cache/item['comparison_plot'],comparison);item['comparison_file']=str(comparison)
        groups.append(item)
    index=result.get('sample_index',[])
    for entry in index:
        if entry['profile']!='crack':continue
        group=next((g for g in groups if str(g['line'])==entry['line'] and str(g['product'])==entry['product'] and g['position']==entry['position']),None)
        path=folder/entry['file'];samples=pd.read_csv(path,dtype={'원본시트':str},low_memory=False)
        for tag,key in [('TabICLv2','scores_default'),('TabICLv2_큰값보존','scores_preserve')]:
            samples[tag+'점수']=np.nan;samples[tag+'결과']='미계산: 학습 MASTER 부족 또는 GPU 시험일 밖'
            if not group or group['status']!='ready':continue
            score=pd.read_csv(cache/group[key],dtype={'source_sheet':str})
            if score.duplicated(['source_sheet','source_row']).any():raise ValueError('GPU 샘플 키 중복')
            score=score.set_index(['source_sheet','source_row'])
            keys=pd.MultiIndex.from_frame(samples[['원본시트','원본행']])
            value=score.TabICLv2_score.reindex(keys).to_numpy()
            reference=score.reference_label.reindex(keys).to_numpy()
            samples[tag+'점수']=value
            samples[tag+'결과']=np.where(~np.isfinite(value),'미계산: GPU 시험일 밖',np.where(reference==-2,'보류: MASTER/설비 OK 충돌',np.where(value>=.9,'MASTER 유사 높음',np.where(value<=.1,'MASTER 유사 낮음','보류'))))
        samples['TabICLv2_실행정보']='저장된 GPU 실험 '+str(manifest['job_id'])+' · 이전 날짜 문맥 / 마지막 날짜 시험 · 이번 버튼에서 새 GPU 학습 아님'
        samples.to_csv(path,index=False,compression={'method':'gzip','compresslevel':3})
    summary=pd.read_csv(cache/manifest['summary_csv'])
    result['tables']['09_TabICLv2_저장GPU시험']=summary
    view.update(status='matched',message='크랙은 원본과 같은 샘플의 TabICLv2 내부 특징 PCA·t-SNE를 우선 표시합니다. 저장된 GPU 실험 '+str(manifest['job_id'])+' 결과이며 이번 버튼에서 새로 GPU 학습한 것은 아닙니다. 일반 NG의 진성·가성은 미확정입니다.',groups=groups,summary_file=str(target/manifest['summary_plot']),job_id=manifest['job_id'])
    (folder/'TabICLv2_표시정보.json').write_text(json.dumps(view,ensure_ascii=False,indent=2),encoding='utf-8')
    report=folder/'검증보고서.html'
    if report.is_file():
        with report.open('a',encoding='utf-8') as f:
            f.write('<h2>크랙 TabICLv2 저장 GPU 실험</h2><p>'+html.escape(view['message'])+'</p><img src="TabICLv2_저장GPU결과/'+html.escape(manifest['summary_plot'],quote=True)+'">')
            for group in groups:
                if group['status']=='ready':
                    f.write('<h3>'+html.escape(str(group['line'])+' 위치 '+str(group['position']))+'</h3><img src="'+Path(group['display_file']).name+'">')
                    if group.get('comparison_file'):f.write('<details><summary>원본 측정값과 같은 샘플로 비교</summary><img src="'+Path(group['comparison_file']).name+'"></details>')
                else:f.write('<p>'+html.escape(str(group['line'])+' 위치 '+str(group['position'])+': '+group['reason'])+'</p>')
    return view


def panel_for_crack(result,entry):
    if entry['profile']!='crack':return None
    view=result.get('tabicl_view',{})
    if view.get('status')!='matched':return None
    group=next((g for g in view['groups'] if str(g['line'])==entry['line'] and str(g['product'])==entry['product'] and g['position']==entry['position']),None)
    if not group or group['status']!='ready':return None
    return {'title':f'{entry["line"]} / {entry["product"]} / 위치 {entry["position"]} · TabICLv2 내부 특징 (저장 GPU 결과)',
            'file':group['display_file'],'rows':group['query_rows'],'valid_rows':group['query_rows'],'tsne_rows':group['plot_rows'],
            'notice':group.get('notice',''),'view':'TabICLv2_default_saved_GPU',**({'comparison_file':group['comparison_file']} if group.get('comparison_file') else {})}
