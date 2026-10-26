"""Authenticated HTTP chunk uploads; only small UI events use the kernel channel."""
from pathlib import Path
import json
import re
import uuid
import ipywidgets as w
from traitlets import Bool, Unicode, observe

class ChunkUpload(w.VBox):
    busy = Bool(False)
    disabled = Bool(False)
    error = Unicode('')

    def __init__(self, folder, on_complete, label='Excel 선택', **kwargs):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.completed=on_complete
        self.identity='ect-upload-'+uuid.uuid4().hex
        self.events=w.Text(layout=w.Layout(display='none'))
        self.events.add_class(self.identity+'-events')
        self.events.observe(self.receive,names='value')
        import html
        native=w.HTML('<div id="'+self.identity+'"><button type="button" style="padding:9px 16px;background:#edf1f4;color:#19374c;border:1px solid #c4ced8;border-radius:5px;cursor:pointer;font:inherit">'+html.escape(label)+'</button><input type="file" accept=".xlsx" hidden><div class="upload-status" style="font-size:13px;margin:8px 0;overflow-wrap:anywhere;color:#38566d"></div><progress max="100" value="0" hidden style="width:95%"></progress></div>')
        super().__init__(children=[native,self.events],**kwargs)

    @observe('disabled')
    def sync_disabled(self,change):
        if hasattr(self,'events'):self.events.disabled=change['new']

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
                path=save_upload(self.folder,message['name'],part.read_bytes())
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
              if(!file.name.toLowerCase().endsWith('.xlsx')||file.size>100*1024*1024){status.textContent='100MB 이하의 .xlsx 파일을 선택해 주세요.';input.value='';return;}
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
