// upload.js — Two-phase file upload: preview + confirm

let _pendingUpload=null;

async function handleFiles(files){
  if(_upl){addSysMsg('上传进行中，请稍等…','orange');return;}
  _upl=true;
  try{for(const f of Array.from(files))await uploadFile(f);}
  finally{_upl=false;const fi=$('fileInput');if(fi)fi.value='';}
}

async function uploadFile(file){
  if(!file)return;
  addSysMsg('正在解析：<b>'+esc(file.name)+'</b>…','blue');
  const fd=new FormData();fd.append('file',file);
  const ctrl=new AbortController();
  const timer=setTimeout(()=>ctrl.abort(),60000);
  try{
    const r=await fetch('/api/upload',{method:'POST',body:fd,signal:ctrl.signal});
    const d=await r.json();
    if(d.ok){
      showUploadConfirm(d);
    }else{addSysMsg('上传失败：'+esc(d.error),'red');}
  }catch(e){
    if(e.name==='AbortError')addSysMsg('解析超时，请重试','red');
    else addSysMsg('上传异常：'+esc(e.message),'red');
  }finally{clearTimeout(timer);}
}

function showUploadConfirm(d){
  _pendingUpload=d;
  $('ucFilename').textContent=d.filename;
  $('ucRows').textContent=(d.row_estimate||0)+'行';
  $('ucCols').textContent=(d.col_count||0)+'列';
  const sel=$('ucType');sel.value=d.detected_type||'unknown';
  $('ucDate').value=d.detected_date||'';
  const stem=d.filename.replace(/\.[^.]+$/,'').replace(/[^a-zA-Z0-9一-鿿_\-]/g,'_');
  $('ucTableName').value=(d.detected_type||'unknown')+'_'+stem;
  const cols=d.columns||[];const rows=d.preview_rows||[];
  let th='<tr>'+cols.map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr>';
  let tbody=rows.map(r=>'<tr>'+r.map(v=>'<td>'+esc(String(v))+'</td>').join('')+'</tr>').join('');
  $('ucPreview').innerHTML='<table class="preview-tbl"><thead>'+th+'</thead><tbody>'+tbody+'</tbody></table>';
  $('uploadConfirmOverlay').style.display='flex';
}

async function confirmUploadFile(){
  if(!_pendingUpload)return;
  const payload={
    file_path:_pendingUpload.file_path,
    filename:_pendingUpload.filename,
    table_type:$('ucType').value,
    date_tag:$('ucDate').value.trim(),
    table_name:$('ucTableName').value.trim(),
  };
  $('uploadConfirmOverlay').style.display='none';
  addSysMsg('正在入库：<b>'+esc(payload.table_name)+'</b>…','blue');
  try{
    const r=await fetch('/api/upload/confirm',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    });
    const d=await r.json();
    if(d.ok){
      addSysMsg('已加载：<b>'+esc(d.table_name)+'</b>（'+d.row_count+'行 × '+d.col_count+'列）','green');
      if(d.quality_report)renderQuality(d.quality_report,d.table_name);
      openSec('tables');refreshSidebar();
    }else{addSysMsg('入库失败：'+esc(d.error),'red');}
  }catch(e){addSysMsg('入库异常：'+esc(e.message),'red');}
  _pendingUpload=null;
}

function cancelUploadConfirm(){
  $('uploadConfirmOverlay').style.display='none';
  _pendingUpload=null;
  addSysMsg('已取消文件上传','orange');
  _upl=false;
  const fi=$('fileInput');if(fi)fi.value='';
}

function guessType(fn){
  const n=fn.toLowerCase();
  if(n.includes('持仓')||n.includes('holding'))return'holding';
  if(n.includes('净值')||n.includes('nav'))return'nav';
  if(n.includes('评级')&&n.includes('主体'))return'rating_entity';
  if(n.includes('评级')&&n.includes('债券'))return'rating_bond';
  return'unknown';
}
