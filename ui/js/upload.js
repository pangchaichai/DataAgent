// upload.js — Two-phase file upload: preview + confirm (single & batch)

let _pendingUpload=null;
let _pendingBatch=[];

function _uploadMsg(html,color){
  if(ST.currentPage==='/chat')addSysMsg(html,color);
  else toast(html.replace(/<[^>]*>/g,''),color==='red'?'error':color==='green'?'success':'');
}

async function handleFiles(files){
  if(_upl){_uploadMsg('上传进行中，请稍等…','orange');return;}
  const arr=Array.from(files);
  if(!arr.length)return;
  _upl=true;
  try{
    if(arr.length===1){
      await uploadFile(arr[0]);
    }else{
      await uploadBatch(arr);
    }
  }finally{_upl=false;const fi=$('fileInput');if(fi)fi.value='';}
}

// --- Single file upload (existing flow) ---

async function uploadFile(file){
  if(!file)return;
  _uploadMsg('正在解析：<b>'+esc(file.name)+'</b>…','blue');
  const fd=new FormData();fd.append('file',file);
  const ctrl=new AbortController();
  const timer=setTimeout(()=>ctrl.abort(),60000);
  try{
    const r=await fetch('/api/upload',{method:'POST',body:fd,signal:ctrl.signal});
    const d=await r.json();
    if(d.ok){
      if(d.file_kind==='document'){
        showDocumentResult(d);
      }else{
        showUploadConfirm(d);
      }
    }else{_uploadMsg('上传失败：'+esc(d.error),'red');}
  }catch(e){
    if(e.name==='AbortError')_uploadMsg('解析超时，请重试','red');
    else _uploadMsg('上传异常：'+esc(e.message),'red');
  }finally{clearTimeout(timer);}
}

function showDocumentResult(d){
  if(ST.currentPage==='/chat'){
    let html='<div class="bubble-outer da"><div class="avatar">DA</div><div class="bubble">';
    html+='<b>📄 文档已解析：'+esc(d.filename)+'</b><br>';
    html+='<span style="color:var(--text-2)">类型：'+esc(d.file_type||'文档')
      +'　字数：'+(d.word_count||0)
      +(d.page_count?'　页数：'+d.page_count:'')
      +(d.table_count?'　表格：'+d.table_count+'个':'')+'</span>';
    if(d.text_preview){
      html+='<div style="margin-top:8px;padding:8px 12px;background:var(--bg-s);border-radius:6px;'
        +'font-size:13px;max-height:200px;overflow-y:auto;white-space:pre-wrap">'
        +esc(d.text_preview)+'</div>';
    }
    html+='<div style="margin-top:8px;color:var(--text-2);font-size:12px">'
      +'文档内容已就绪，您可以在输入框中提问来分析此文档。</div>';
    html+='</div></div>';
    add(el(html));
  }else{
    toast('文档已解析：'+d.filename,'success');
  }
  _pendingUpload=null;
  _documentContext=d;
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

  // Preprocess info for Excel files
  const ppEl=$('ucPreprocessInfo');
  if(ppEl){
    const pp=d.preprocess_info;const sheets=d.sheets||[];
    const msgs=[];
    if(pp&&pp.title_rows_skipped>0)
      msgs.push('已自动跳过 '+pp.title_rows_skipped+' 行标题行');
    if(pp&&pp.header_levels>1)
      msgs.push('已合并 '+pp.header_levels+' 层表头');
    if(sheets.length>1&&d.sheets_concatenated)
      msgs.push('此文件包含 '+sheets.length+' 个工作表（结构相同），已自动合并（共 '+(d.row_estimate||0)+' 行）');
    else if(sheets.length>1&&!d.sheets_concatenated)
      msgs.push('<span style="color:var(--orange)">此文件包含 '+sheets.length+' 个工作表（结构不同），仅导入首张工作表「'+esc(sheets[0].name)+'」</span>');
    if(msgs.length){
      ppEl.innerHTML='<div class="uc-preprocess-info">'+msgs.map(m=>'<div>'+m+'</div>').join('')+'</div>';
      ppEl.style.display='';
    }else{
      ppEl.style.display='none';ppEl.innerHTML='';
    }
  }

  // Detection meta hint (LLM suggestion)
  const dmEl=$('ucDetectionHint');
  if(dmEl){
    const dm=d.detection_meta;
    if(dm&&dm.source==='llm'&&dm.llm_suggestion){
      dmEl.innerHTML='<div style="padding:6px 10px;background:var(--bg-s);border-radius:6px;font-size:12px;color:var(--text-2);margin-bottom:8px">'
        +'AI 识别建议：'+esc(dm.llm_suggestion)+'</div>';
      dmEl.style.display='';
    }else{
      dmEl.style.display='none';dmEl.innerHTML='';
    }
  }

  const cols=d.columns||[];const rows=d.preview_rows||[];
  let th='<tr>'+cols.map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr>';
  let tbody=rows.map(r=>'<tr>'+r.map(v=>'<td>'+esc(String(v))+'</td>').join('')+'</tr>').join('');
  $('ucPreview').innerHTML='<table class="preview-tbl"><thead>'+th+'</thead><tbody>'+tbody+'</tbody></table>';
  $('uploadConfirmOverlay').style.display='flex';
  $('uploadConfirmPanel').style.display='block';
}

async function confirmUploadFile(){
  if(!_pendingUpload)return;
  const tableName=$('ucTableName').value.trim();
  const tableType=$('ucType').value;
  const dateTag=$('ucDate').value.trim();
  $('uploadConfirmOverlay').style.display='none';
  $('uploadConfirmPanel').style.display='none';
  _uploadMsg('正在加载：<b>'+esc(tableName)+'</b>…','blue');

  const fromWorkdir=!!_pendingUpload.from_workdir;
  const endpoint=fromWorkdir?'/api/workdir/load':'/api/upload/confirm';
  const payload=fromWorkdir
    ?{filename:_pendingUpload.filename,table_type:tableType,date_tag:dateTag,table_name:tableName}
    :{file_path:_pendingUpload.file_path,filename:_pendingUpload.filename,table_type:tableType,date_tag:dateTag,table_name:tableName};

  try{
    const r=await fetch(endpoint,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    });
    const d=await r.json();
    if(d.ok){
      let msg='已加载：<b>'+esc(d.table_name)+'</b>（'+d.row_count+'行 × '+d.col_count+'列）';
      if(d.masking_info){
        msg+='<br><span style="color:var(--orange)">🔒 已脱敏字段：'+esc(d.masking_info.masked_fields.join('、'))
          +'（共 '+d.masking_info.total_values_masked+' 个值已脱敏）</span>';
      }
      _uploadMsg(msg,'green');
      if(ST.currentPage==='/chat'&&d.quality_report)renderQuality(d.quality_report,d.table_name);
      refreshSidebar();
      if(ST.currentPage==='/data')DataPage._renderTableList();
    }else{_uploadMsg('加载失败：'+esc(d.error),'red');}
  }catch(e){_uploadMsg('加载异常：'+esc(e.message),'red');}
  _pendingUpload=null;
}

function cancelUploadConfirm(){
  $('uploadConfirmOverlay').style.display='none';
  $('uploadConfirmPanel').style.display='none';
  _pendingUpload=null;
  _uploadMsg('已取消文件上传','orange');
  _upl=false;
  const fi=$('fileInput');if(fi)fi.value='';
}

// --- Batch upload (multiple files) ---

async function uploadBatch(files){
  _pendingBatch=[];
  const docFiles=[];
  let parseErrors=0;
  _uploadMsg('正在解析 '+files.length+' 个文件…','blue');

  for(const f of files){
    const fd=new FormData();fd.append('file',f);
    const ctrl=new AbortController();
    const timer=setTimeout(()=>ctrl.abort(),60000);
    try{
      const r=await fetch('/api/upload',{method:'POST',body:fd,signal:ctrl.signal});
      const d=await r.json();
      if(d.ok){
        if(d.file_kind==='document'){
          docFiles.push(d);
        }else{
          const stem=d.filename.replace(/\.[^.]+$/,'').replace(/[^a-zA-Z0-9一-鿿_\-]/g,'_');
          d._tableName=(d.detected_type||'unknown')+'_'+stem;
          _pendingBatch.push(d);
        }
      }else{parseErrors++;_uploadMsg('解析失败：'+esc(f.name)+' — '+esc(d.error),'red');}
    }catch(e){
      parseErrors++;
      if(e.name==='AbortError')_uploadMsg('解析超时：'+esc(f.name),'red');
      else _uploadMsg('解析异常：'+esc(f.name),'red');
    }finally{clearTimeout(timer);}
  }

  for(const doc of docFiles)showDocumentResult(doc);
  if(_pendingBatch.length>0){
    showBatchConfirm();
  }else if(!docFiles.length){
    _uploadMsg('没有可导入的数据文件','orange');
  }
}

function showBatchConfirm(){
  const n=_pendingBatch.length;
  $('batchSummary').textContent='共 '+n+' 个数据文件待导入，可调整表类型和日期后一键导入';
  const list=$('batchFileList');
  list.innerHTML=_pendingBatch.map((d,i)=>{
    const typeOpts=['holding','nav','rating_entity','rating_bond','monitoring','unknown'];
    const typeLabels={'holding':'持仓表','nav':'净值表','rating_entity':'主体评级',
      'rating_bond':'债券评级','monitoring':'监控数据','unknown':'未知类型'};
    const selHtml=typeOpts.map(v=>
      '<option value="'+v+'"'+(v===(d.detected_type||'unknown')?' selected':'')+'>'+typeLabels[v]+'</option>'
    ).join('');
    return '<div class="bf-card" id="bfCard'+i+'">'
      +'<div class="bf-card-header">'
      +'<span class="bf-card-name" title="'+esc(d.filename)+'">'+esc(d.filename)+'</span>'
      +'<span class="bf-card-meta">'+(d.row_estimate||0)+'行 × '+(d.col_count||0)+'列</span>'
      +'<span class="bf-card-status pending" id="bfStatus'+i+'">待导入</span>'
      +'<span class="bf-card-remove" onclick="removeBatchItem('+i+')" title="移除">×</span>'
      +'</div>'
      +'<div class="bf-card-fields">'
      +'<div><label>类型</label><br><select id="bfType'+i+'" onchange="updateBatchTableName('+i+')">'+selHtml+'</select></div>'
      +'<div><label>日期</label><br><input type="text" id="bfDate'+i+'" value="'+esc(d.detected_date||'')+'" placeholder="20260609"></div>'
      +'<div style="flex:1"><label>表名</label><br><input type="text" id="bfName'+i+'" value="'+esc(d._tableName)+'" style="width:100%"></div>'
      +'</div>'
      +'</div>';
  }).join('');
  $('batchConfirmBtn').disabled=false;
  $('batchConfirmBtn').textContent='全部导入（'+n+'）';
  $('batchUploadOverlay').style.display='flex';
  $('batchUploadPanel').style.display='block';
}

function updateBatchTableName(idx){
  const d=_pendingBatch[idx];if(!d)return;
  const newType=$('bfType'+idx).value;
  const stem=d.filename.replace(/\.[^.]+$/,'').replace(/[^a-zA-Z0-9一-鿿_\-]/g,'_');
  $('bfName'+idx).value=newType+'_'+stem;
}

function removeBatchItem(idx){
  const card=$('bfCard'+idx);
  if(card)card.style.display='none';
  _pendingBatch[idx]=null;
  const remaining=_pendingBatch.filter(Boolean).length;
  if(remaining===0){
    cancelBatchUpload();
    return;
  }
  $('batchConfirmBtn').textContent='全部导入（'+remaining+'）';
}

function cancelBatchUpload(){
  $('batchUploadOverlay').style.display='none';
  $('batchUploadPanel').style.display='none';
  _pendingBatch=[];
  _uploadMsg('已取消批量上传','orange');
  _upl=false;
  const fi=$('fileInput');if(fi)fi.value='';
}

async function confirmBatchUpload(){
  const items=_pendingBatch.map((d,i)=>d?{data:d,idx:i}:null).filter(Boolean);
  if(!items.length){cancelBatchUpload();return;}
  $('batchConfirmBtn').disabled=true;
  $('batchConfirmBtn').textContent='导入中…';
  let successCount=0,failCount=0;

  for(const item of items){
    const {data:d,idx:i}=item;
    const tableName=($('bfName'+i)||{}).value||d._tableName;
    const tableType=($('bfType'+i)||{}).value||d.detected_type||'unknown';
    const dateTag=($('bfDate'+i)||{}).value||'';
    const statusEl=$('bfStatus'+i);
    if(statusEl){statusEl.textContent='导入中…';statusEl.className='bf-card-status loading';}

    const fromWorkdir=!!d.from_workdir;
    const endpoint=fromWorkdir?'/api/workdir/load':'/api/upload/confirm';
    const payload=fromWorkdir
      ?{filename:d.filename,table_type:tableType,date_tag:dateTag,table_name:tableName}
      :{file_path:d.file_path,filename:d.filename,table_type:tableType,date_tag:dateTag,table_name:tableName};

    try{
      const r=await fetch(endpoint,{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload)
      });
      const res=await r.json();
      if(res.ok){
        successCount++;
        let statusText='已加载（'+res.row_count+'行）';
        if(res.masking_info)statusText+=' 🔒 已脱敏'+res.masking_info.masked_fields.length+'个字段';
        if(statusEl){statusEl.textContent=statusText;statusEl.className='bf-card-status done';}
      }else{
        failCount++;
        if(statusEl){statusEl.textContent='失败';statusEl.className='bf-card-status error';}
      }
    }catch(e){
      failCount++;
      if(statusEl){statusEl.textContent='异常';statusEl.className='bf-card-status error';}
    }
  }

  refreshSidebar();
  if(ST.currentPage==='/data')DataPage._renderTableList();

  if(failCount===0){
    setTimeout(()=>{
      $('batchUploadOverlay').style.display='none';
      $('batchUploadPanel').style.display='none';
      _pendingBatch=[];
      _uploadMsg('批量导入完成：'+successCount+' 个文件已加载','green');
    },800);
  }else{
    $('batchConfirmBtn').textContent='完成（'+successCount+'成功 / '+failCount+'失败）';
    $('batchConfirmBtn').disabled=false;
    $('batchConfirmBtn').onclick=function(){
      $('batchUploadOverlay').style.display='none';
      $('batchUploadPanel').style.display='none';
      _pendingBatch=[];
    };
  }
}

function guessType(fn){
  const n=fn.toLowerCase();
  if(n.includes('持仓')||n.includes('holding'))return'holding';
  if(n.includes('净值')||n.includes('nav'))return'nav';
  if(n.includes('评级')&&n.includes('主体'))return'rating_entity';
  if(n.includes('评级')&&n.includes('债券'))return'rating_bond';
  return'unknown';
}
