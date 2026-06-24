// data_tables.js — Table management, profile, quality, workdir, table actions

function _groupTablesByType(tables) {
  const order = ['holding','nav','rating_entity','rating_bond','monitoring','unknown'];
  const map = {};
  tables.forEach(t => {
    const type = t.type || 'unknown';
    if (!map[type]) map[type] = [];
    map[type].push(t);
  });
  const result = [];
  order.forEach(k => { if (map[k]) { result.push({type:k, tables:map[k]}); delete map[k]; } });
  Object.keys(map).forEach(k => result.push({type:k, tables:map[k]}));
  return result;
}

async function loadTables(){
  try{
    const d=await api('GET','/api/tables');
    const tables=d.tables||[];
    window._cachedTables=tables;
    const cnt=$('tableCountH');if(cnt)cnt.textContent=tables.length;
    const list=$('tableList');
    if(!tables.length){list.innerHTML='<div class="s-item" style="color:var(--text-3)">暂无数据</div>';
      if(typeof updateWelcomeExamples==='function')updateWelcomeExamples([]);
      return;}
    list.innerHTML=tables.map(t=>{
      const color=t.type==='holding'?'var(--green)':t.type==='nav'?'var(--blue)':'var(--text-3)';
      const dateMeta=t.date_tag?' · '+t.date_tag:'';
      return '<div class="s-item">'
        +'<span class="dot" style="background:'+color+'"></span>'
        +'<span class="s-text s-clickable" onclick="openProfile(\''+esc(t.name)+'\')" title="查看表结构">'+esc(t.name)+'</span>'
        +'<span class="s-meta">'+t.rows+'行'+esc(dateMeta)+'</span>'
        +'<span class="item-del" onclick="deleteTable(\''+esc(t.name)+'\')" title="移除此表">×</span>'
        +'</div>';
    }).join('');
    if(typeof updateWelcomeExamples==='function')updateWelcomeExamples(tables);
  }catch(e){}
}
async function deleteTable(name){
  if(!confirm('确定要移除表「'+name+'」吗？数据文件不会被删除。'))return;
  const r=await api('DELETE','/api/tables/'+encodeURIComponent(name));
  if(r.ok){loadTables();toast('已移除：'+name);}
  else toast('移除失败：'+(r.error||''),'error');
}

// Work Directory
async function loadWorkdir(){
  const list=$('workdirList');
  try{
    const d=await api('GET','/api/workdir/files');
    if(!d.work_dir){
      list.innerHTML='<div class="s-item" style="color:var(--text-3)">未配置（在设置中添加目录路径）</div>';
      return;
    }
    const files=d.files||[];
    if(!files.length){
      list.innerHTML='<div class="s-item" style="color:var(--text-3)">目录为空（无 CSV/Excel 文件）</div>';
      return;
    }
    list.innerHTML=files.map(f=>
      '<div class="s-item">'
      +'<span class="s-text" title="'+esc(f.filename)+'">'+esc(f.filename)+'</span>'
      +'<span class="s-meta">'+f.size_kb+'KB</span>'
      +'<span class="act" style="font-size:11px" onclick="loadWorkdirFile(\''+esc(f.filename)+'\')">加载</span>'
      +'</div>'
    ).join('');
  }catch(e){
    list.innerHTML='<div class="s-item" style="color:var(--text-3)">加载失败</div>';
  }
}
function refreshWorkdir(){openSec('workdir');loadWorkdir();}

async function loadWorkdirFile(filename){
  _uploadMsg('正在预览工作目录文件：<b>'+esc(filename)+'</b>…','blue');
  try{
    const d=await api('POST','/api/workdir/preview',{filename});
    if(!d.ok){_uploadMsg('预览失败：'+esc(d.error),'red');return;}
    showUploadConfirm(d);
  }catch(e){_uploadMsg('预览请求失败：'+esc(e.message),'red');}
}

// Table actions
function sortTbl(th,col){
  const tbody=th.closest('table').querySelector('tbody');
  const rows=Array.from(tbody.querySelectorAll('tr'));
  const asc=th.dataset.sort!=='asc';
  rows.sort((a,b)=>{
    const va=a.children[col]?.textContent||'',vb=b.children[col]?.textContent||'';
    const na=parseFloat(va.replace(/,/g,'')),nb=parseFloat(vb.replace(/,/g,''));
    if(!isNaN(na)&&!isNaN(nb))return asc?na-nb:nb-na;
    return asc?va.localeCompare(vb):vb.localeCompare(va);
  });
  th.dataset.sort=asc?'asc':'desc';
  rows.forEach(r=>tbody.appendChild(r));
}
function exportCSV(btn){
  const table=btn.closest('.table-card')?.querySelector('table');
  if(!table)return;
  let csv='';
  table.querySelectorAll('tr').forEach(r=>{
    const cells=[];
    r.querySelectorAll('th,td').forEach(c=>cells.push('"'+c.textContent.replace(/"/g,'""')+'"'));
    csv+=cells.join(',')+'\n';
  });
  const blob=new Blob(['﻿'+csv],{type:'text/csv;charset=utf-8'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='export_'+Date.now()+'.csv';a.click();
}
function copyTable(btn){
  const table=btn.closest('.table-card')?.querySelector('table');
  if(!table)return;
  let text='';
  table.querySelectorAll('tr').forEach(r=>{
    const cells=[];r.querySelectorAll('th,td').forEach(c=>cells.push(c.textContent.trim()));
    text+=cells.join('\t')+'\n';
  });
  navigator.clipboard.writeText(text).then(()=>{
    const orig=btn.textContent;btn.textContent='已复制✓';
    setTimeout(()=>{btn.textContent=orig;},1500);
  });
}
function chartFromTable(btn){
  const card=btn.closest('.table-card');
  const title=card?.querySelector('.tc-title')?.textContent||'';
  const table=card?.querySelector('table');if(!table)return;
  const ths=[...table.querySelectorAll('thead th')].map(t=>t.textContent.trim());
  const rows=[...table.querySelectorAll('tbody tr')].map(r=>
    [...r.querySelectorAll('td')].map(c=>c.textContent.trim()));
  if(ths.length<2||rows.length===0){addSysMsg('数据列数不足，无法自动生成图表','orange');return;}
  const cats=rows.map(r=>r[0]);
  const vals=rows.map(r=>Number(r[1].replace(/,/g,''))||0);
  const opt={title:{text:title,left:'center',textStyle:{fontSize:13}},
    tooltip:{},xAxis:{type:'category',data:cats,axisLabel:{rotate:30,fontSize:11}},
    yAxis:{type:'value'},series:[{type:'bar',data:vals,barMaxWidth:40}]};
  add(renderChart(opt));scrollBottom();
}

// Table Profile
async function openProfile(tableName){
  _profileTable=tableName;
  $('profileOverlay').classList.add('show');
  $('pmTitle').textContent=tableName;
  $('pmTabStruct').classList.add('active');
  $('pmTabQuality').classList.remove('active');
  $('pmBody').style.display='';
  $('pmBodyQuality').style.display='none';
  $('pmBody').innerHTML='<div style="text-align:center;padding:30px;color:var(--text-3)">加载中…</div>';
  $('pmBodyQuality').innerHTML='';
  try{
    const d=await api('GET','/api/tables/'+encodeURIComponent(tableName)+'/profile');
    if(d.error){$('pmBody').innerHTML='<div style="color:var(--red)">'+esc(d.error)+'</div>';return;}
    let html='<div style="margin-bottom:10px;font-size:13px;color:var(--text-2)">'
      +d.row_count+'行 × '+d.columns.length+'列</div>';
    if(d.field_map&&Object.keys(d.field_map).length){
      html+='<div style="margin-bottom:10px;padding:8px 10px;background:var(--bg-2);border-radius:6px;font-size:12px;color:var(--text-2)">'
        +'<b>字段映射：</b>'+Object.entries(d.field_map).map(([k,v])=>esc(k)+' → '+esc(v)).join('、')
        +'</div>';
    }
    try{
      const mc=await api('GET','/api/config');
      const masking=mc.config&&mc.config.masking;
      if(masking&&masking.enabled&&masking.fields){
        html+='<div style="margin-bottom:10px;padding:8px 10px;background:var(--orange-bg,#fff3e0);border-radius:6px;font-size:12px;color:var(--orange,#e67e22)">'
          +'<b>脱敏字段：</b>'+esc(masking.fields)
          +'</div>';
      }
    }catch(e){}
    html+='<div class="pm-col">';
    html+='<div class="pm-hdr">列名</div><div class="pm-hdr">类型</div>'
      +'<div class="pm-hdr">空值率</div><div class="pm-hdr">去重</div><div class="pm-hdr">样本值</div>';
    (d.columns||[]).forEach(c=>{
      const nullPct=Math.round((c.null_rate||0)*100);
      const nullCls=nullPct>5?'pm-null':'pm-null ok';
      html+='<div title="'+esc(c.name)+'">'+esc(c.name)+'</div>';
      html+='<div style="color:var(--text-3)">'+esc(c.dtype)+'</div>';
      html+='<div class="'+nullCls+'">'+nullPct+'%</div>';
      html+='<div>'+(c.distinct_count||'-')+'</div>';
      const samples=(c.samples||[]).join(', ')||(c.min!=null?c.min+'~'+c.max:'—');
      html+='<div class="pm-samples" title="'+esc(samples)+'">'+esc(samples)+'</div>';
    });
    html+='</div>';
    $('pmBody').innerHTML=html;
  }catch(e){$('pmBody').innerHTML='<div style="color:var(--red)">加载失败：'+esc(e.message)+'</div>';}
}
function closeProfile(){$('profileOverlay').classList.remove('show');}
function switchProfileTab(tab){
  if(tab==='struct'){
    $('pmTabStruct').classList.add('active');$('pmTabQuality').classList.remove('active');
    $('pmBody').style.display='';$('pmBodyQuality').style.display='none';
  }else{
    $('pmTabStruct').classList.remove('active');$('pmTabQuality').classList.add('active');
    $('pmBody').style.display='none';$('pmBodyQuality').style.display='';
    loadQualityTab(_profileTable);
  }
}
async function loadQualityTab(tableName){
  const body=$('pmBodyQuality');
  body.innerHTML='<div style="text-align:center;padding:30px;color:var(--text-3)">分析中…</div>';
  try{
    const d=await api('GET','/api/tables/'+encodeURIComponent(tableName)+'/quality');
    if(d.error){body.innerHTML='<div style="color:var(--red)">'+esc(d.error)+'</div>';return;}
    const q=d.report||d;
    const nullRates=q.null_rates||{};
    const cols=Object.keys(nullRates);
    const avgNull=cols.length?cols.reduce((s,k)=>s+nullRates[k],0)/cols.length:0;
    const completeness=Math.round((1-avgNull)*100);
    const compCls=completeness>=95?'good':completeness>=80?'warn':'bad';
    const highNullCols=cols.filter(k=>nullRates[k]>0.05);
    let html='<div class="pm-quality-grid">';
    html+='<div class="pm-q-card"><h4>数据完整度</h4><div class="pm-q-val '+compCls+'">'+completeness+'%</div></div>';
    html+='<div class="pm-q-card"><h4>总列数</h4><div class="pm-q-val">'+cols.length+'</div></div>';
    html+='<div class="pm-q-card"><h4>高空值列</h4><div class="pm-q-val '+(highNullCols.length?'warn':'good')+'">'
      +highNullCols.length+'</div></div>';
    const critCount=(q.critical_issues||[]).length;
    html+='<div class="pm-q-card"><h4>严重问题</h4><div class="pm-q-val '+(critCount?'bad':'good')+'">'
      +critCount+'</div></div>';
    html+='</div>';
    if(highNullCols.length){
      html+='<div style="margin-top:14px"><div style="font-size:12px;font-weight:600;color:var(--text-2);margin-bottom:6px">需关注列（空值率>5%）</div>';
      highNullCols.sort((a,b)=>nullRates[b]-nullRates[a]).forEach(col=>{
        const pct=Math.round(nullRates[col]*100);
        html+='<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:12px">'
          +'<span style="flex:1;color:var(--text)">'+esc(col)+'</span>'
          +'<span style="color:var(--orange)">'+pct+'% 空值</span></div>';
      });
      html+='</div>';
    }
    if(q.critical_issues&&q.critical_issues.length){
      html+='<div style="margin-top:12px;padding:8px 10px;background:var(--red-bg);border-radius:6px;font-size:12px;color:var(--red)">';
      q.critical_issues.forEach(c=>{html+='<div>✕ '+esc(c)+'</div>';});
      html+='</div>';
    }
    if(q.warnings&&q.warnings.length){
      html+='<div style="margin-top:12px;padding:8px 10px;background:var(--orange-bg);border-radius:6px;font-size:12px;color:var(--orange)">';
      q.warnings.forEach(w=>{html+='<div>⚠ '+esc(w)+'</div>';});
      html+='</div>';
    }
    if(!critCount&&!highNullCols.length&&!(q.warnings||[]).length){
      html+='<div style="margin-top:14px;text-align:center;color:var(--green);font-size:13px">数据质量良好，无异常发现</div>';
    }
    body.innerHTML=html;
  }catch(e){body.innerHTML='<div style="color:var(--text-3)">质量检查不可用</div>';}
}
