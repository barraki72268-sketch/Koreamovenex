"""Authenticated HTTP chunk uploads; only small UI events use the kernel channel."""
from pathlib import Path
import os,html
import json
import re
import uuid
import ipywidgets as w
from traitlets import Bool, Unicode, observe

class ChunkUpload(w.VBox):
    busy = Bool(False)
    disabled = Bool(False)
    error = Unicode('')

    def __init__(self, folder, on_complete, label='Excel 선택', extensions=('.xlsx',), **kwargs):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.extensions=extensions
        self.completed=on_complete
        self.identity='ect-upload-'+uuid.uuid4().hex
        self.events=w.Text(layout=w.Layout(display='none'))
        self.events.add_class(self.identity+'-events')
        self.events.observe(self.receive,names='value')
        import html
        self.local_mode=os.name=='nt'
        if self.local_mode:
            self.choose=w.Button(description=label,icon='folder-open',layout=w.Layout(width='260px'))
            self.path=w.Text(placeholder='선택 창이 열리지 않으면 파일 탐색기에서 복사한 전체 경로를 붙여넣으세요.',layout=w.Layout(width='98%'))
            self.use_path=w.Button(description='위 경로의 파일 추가',icon='file')
            self.local_status=w.HTML()
            self.choose.on_click(self.choose_local)
            self.use_path.on_click(lambda _:self.import_local(self.path.value))
            super().__init__(children=[self.choose,self.path,self.use_path,self.local_status,self.events],**kwargs)
        else:
            native=w.HTML('<div id="'+self.identity+'"><button type="button" style="padding:9px 16px;background:#edf1f4;color:#19374c;border:1px solid #c4ced8;border-radius:5px;cursor:pointer;font:inherit">'+html.escape(label)+'</button><input type="file" accept="'+','.join(extensions)+'" hidden><div class="upload-status" style="font-size:13px;margin:8px 0;overflow-wrap:anywhere;color:#38566d"></div><progress max="100" value="0" hidden style="width:95%"></progress></div>')
            super().__init__(children=[native,self.events],**kwargs)

    @observe('disabled')
    def sync_disabled(self,change):
        if hasattr(self,'events'):self.events.disabled=change['new']
        for name in ('choose','path','use_path'):
            if hasattr(self,name):getattr(self,name).disabled=change['new']

    def choose_local(self,_=None):
        if self.disabled:return
        window=None
        try:
            import tkinter as tk
            from tkinter import filedialog
            window=tk.Tk();window.withdraw();window.attributes('-topmost',True)
            name=filedialog.askopenfilename(parent=window,title='분석할 CSV·Excel 파일 선택',filetypes=[('측정 자료','*.xlsx *.csv *.csv.gz'),('모든 파일','*.*')])
            if name:self.import_local(name)
        except Exception as exc:
            self.error=str(exc);self.local_status.value='<p>파일 선택 창을 열지 못했습니다. 아래 전체 경로로 추가해 주세요. '+html.escape(str(exc))+'</p>'
        finally:
            if window is not None:window.destroy()

    def import_local(self,name):
        if self.disabled:return
        self.error='';self.busy=True
        try:
            path=Path(str(name).strip().strip('"')).expanduser().resolve(strict=True)
            if not path.is_file():raise ValueError('폴더가 아닌 파일을 선택하세요.')
            if path.stat().st_size>100*1024*1024:raise ValueError('100MB 이하의 파일을 사용해 주세요.')
            from ectlab.delivery_ui import save_upload
            copied=save_upload(self.folder,path.name,path.read_bytes(),extensions=self.extensions)
            self.completed(copied)
            if hasattr(self,'local_status'):self.local_status.value='<p style="color:#21724b">추가 완료 · '+html.escape(path.name)+'</p>'
            return copied
        except Exception as exc:
            self.error=str(exc)
            if hasattr(self,'local_status'):self.local_status.value='<p style="color:#bd2c28">파일 확인: '+html.escape(str(exc))+'</p>'
        finally:self.busy=False

    def receive(self,event):
        message={};error=''
        try:
            message=json.loads(event['new']);action=message['action']
            if action=='begin':
                self.error='';self.busy=True;return
            if action not in ('finish','error'):raise ValueError('파일 전송 상태를 확인해 주세요.')
            name=message.get('part','')
            if not re.fullmatch(r'upload_[a-f0-9]{32}\.part',name):raise ValueError('파일 전송 경로를 확인해 주세요.')
            part=self.folder/name
            if action=='finish':
                if part.stat().st_size>100*1024*1024:raise ValueError('100MB 이하의 파일을 사용해 주세요.')
                from ectlab.delivery_ui import save_upload
                path=save_upload(self.folder,message['name'],part.read_bytes(),extensions=self.extensions)
                part.unlink()
                self.completed(path)
            elif part.is_file():part.unlink()
        except Exception as exc:
            error=str(exc)
        finally:
            if message.get('action')!='begin':self.busy=False
            if error:self.error=error

    def javascript(self, relative_folder):
        # The standard Contents API accepts chunked PUTs, as Jupyter's file browser does.
        from IPython.display import Javascript
        if self.local_mode:
            from IPython.display import HTML
            return HTML('')
        source=r'''
        (()=>{
          const id=IDENTITY, relative=RELATIVE;
          let attempts=0;
          function attach(){
            const box=document.getElementById(id),eventInput=document.querySelector('.'+id+'-events input');
            if(!box||!eventInput){if(attempts++<100)setTimeout(attach,100);return;}
            if(box.dataset.ready)return;box.dataset.ready='yes';
            const button=box.querySelector('button'),input=box.querySelector('input[type=file]'),status=box.querySelector('.upload-status'),progress=box.querySelector('progress');
            let uploading=false;
            const timer=setInterval(()=>{if(!document.contains(box)){clearInterval(timer);return;}button.disabled=uploading||eventInput.disabled;},150);
            function notify(data){eventInput.value=JSON.stringify({...data,nonce:crypto.randomUUID()});eventInput.dispatchEvent(new Event('input',{bubbles:true}));}
            button.onclick=()=>{if(!eventInput.disabled)input.click();};
            input.onchange=async()=>{
              const file=input.files[0];if(!file)return;
              if(!input.accept.split(',').some(ext=>file.name.toLowerCase().endsWith(ext))||file.size>100*1024*1024){status.textContent='100MB 이하의 '+input.accept+' 파일을 선택해 주세요.';input.value='';return;}
              const part='upload_'+crypto.randomUUID().replaceAll('-','')+'.part';
              uploading=true;button.disabled=true;progress.hidden=false;progress.value=0;
              notify({action:'begin'});
              try{
                let base='/';
                const config=document.getElementById('jupyter-config-data');
                if(config)base=JSON.parse(config.textContent).baseUrl||'/';
                const url=base.replace(/\/$/,'')+'/api/contents/'+(relative+'/'+part).split('/').map(encodeURIComponent).join('/');
                const xsrf=document.cookie.split(';').map(v=>v.trim()).find(v=>v.startsWith('_xsrf='));
                if(!xsrf)throw new Error('로그인 상태를 확인한 뒤 다시 선택해 주세요.');
                const step=1024*1024;
                for(let offset=0;offset<file.size;offset+=step){
                  const bytes=new Uint8Array(await file.slice(offset,offset+step).arrayBuffer());
                  let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
                  const payload={type:'file',format:'base64',content:btoa(binary)};
                  if(file.size>step)payload.chunk=offset+step>=file.size?-1:offset/step+1;
                  const response=await fetch(url,{method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/json','X-XSRFToken':decodeURIComponent(xsrf.slice(6))},body:JSON.stringify(payload)});
                  if(!response.ok)throw new Error('파일 전송 오류 ('+response.status+'). 다시 로그인하거나 담당자에게 문의해 주세요.');
                  const percent=Math.round(Math.min(file.size,offset+step)/file.size*100);progress.value=percent;status.textContent='업로드 '+percent+'% · '+file.name;
                }
                notify({action:'finish',part,name:file.name});
                status.textContent='전송 완료 · '+file.name+' · 아래 선택됨 표시를 확인하세요.';
              }catch(error){status.textContent='업로드 확인: '+error.message;notify({action:'error',part});}
              finally{uploading=false;button.disabled=false;input.value='';}
            };
          }
          attach();
        })();
        '''
        return Javascript(source.replace('IDENTITY',json.dumps(self.identity)).replace('RELATIVE',json.dumps(relative_folder)))
