// render.js — Message rendering: markdown, tables, charts, reports, ask/confirm cards

// Markdown renderer
function renderMd(raw){
  if(!raw)return'';
  const lines=raw.split('\n');
  let html='',inCode=false,code=[],inList=false,listTag='',inTable=false,tableRows=[];
  for(let i=0;i<lines.length;i++){
    const L=lines[i];
    if(L.startsWith('```')){
      if(inCode){
        html+='<div class="code-wrap">'
          +'<button class="copy-btn" onclick="copyCodeBlock(this)">复制</button>'
          +'<pre><code>'+esc(code.join('\n'))+'</code></pre></div>';
        inCode=false;code=[];
      }else{closeList();closeTable();inCode=true;}
      continue;
    }
    if(inCode){code.push(L);continue;}
    if(L.match(/^\|.*\|$/)){closeList();if(!inTable){inTable=true;tableRows=[];}tableRows.push(L);continue;}
    if(inTable)closeTable();
    if(!L.trim()){closeList();html+='<br>';continue;}
    if(L.startsWith('### ')){closeList();html+='<h4>'+inline(L.slice(4))+'</h4>';continue;}
    if(L.startsWith('## ')){closeList();html+='<h4>'+inline(L.slice(3))+'</h4>';continue;}
    if(L.startsWith('# ')){closeList();html+='<h3>'+inline(L.slice(2))+'</h3>';continue;}
    if(L.startsWith('> ')){closeList();html+='<blockquote>'+inline(L.slice(2))+'</blockquote>';continue;}
    const ul=L.match(/^\s*[-*]\s+(.*)/);
    if(ul){if(!inList||listTag!=='ul'){closeList();html+='<ul>';inList=true;listTag='ul';}
      html+='<li>'+inline(ul[1])+'</li>';continue;}
    const ol=L.match(/^\s*\d+\.\s+(.*)/);
    if(ol){if(!inList||listTag!=='ol'){closeList();html+='<ol>';inList=true;listTag='ol';}
      html+='<li>'+inline(ol[1])+'</li>';continue;}
    closeList();html+='<p>'+inline(L)+'</p>';
  }
  if(inCode)html+='<div class="code-wrap">'
    +'<button class="copy-btn" onclick="copyCodeBlock(this)">复制</button>'
    +'<pre><code>'+esc(code.join('\n'))+'</code></pre></div>';
  closeList();closeTable();
  return html;
  function closeList(){if(inList){html+=listTag==='ul'?'</ul>':'</ol>';inList=false;}}
  function closeTable(){
    if(!inTable)return;inTable=false;
    if(tableRows.length<2){tableRows.forEach(r=>{html+='<p>'+inline(r)+'</p>';});tableRows=[];return;}
    const hdr=tableRows[0].split('|').filter(c=>c.trim());
    let t='<div class="md-table-wrap"><table class="md-table"><thead><tr>';
    hdr.forEach(c=>{t+='<th>'+inline(c.trim())+'</th>';});
    t+='</tr></thead><tbody>';
    for(let j=2;j<tableRows.length;j++){
      const cells=tableRows[j].split('|').filter(c=>c.trim());
      t+='<tr>';cells.forEach(c=>{t+='<td>'+inline(c.trim())+'</td>';});t+='</tr>';
    }
    t+='</tbody></table></div>';html+=t;tableRows=[];
  }
}
function inline(text){
  let s=esc(text);
  s=s.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  s=s.replace(/\*(.+?)\*/g,'<em>$1</em>');
  s=s.replace(/`(.+?)`/g,'<code>$1</code>');
  s=s.replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" target="_blank">$1</a>');
  return s;
}

// Bubble helpers — Stitch asymmetric radius design
function addUserBubble(text){
  add(el('<div class="flex justify-end gap-3 max-w-full">'
    +'<div class="max-w-[min(78%,720px)]">'
    +'<div class="flex items-center gap-2 mb-1 justify-end">'
    +'<span class="label-caps text-on-surface-variant">你</span>'
    +'<div class="w-6 h-6 rounded bg-secondary-fixed flex items-center justify-center flex-shrink-0">'
    +'<span class="material-symbols-outlined text-[14px] text-secondary">person</span></div>'
    +'</div>'
    +'<div class="bubble-user text-body-md leading-relaxed whitespace-pre-wrap break-words">'+esc(text)+'</div>'
    +'</div></div>'));
}
function addAgentHTML(html){
  add(el('<div class="flex gap-3 max-w-full">'
    +'<div class="w-8 h-8 rounded bg-primary-container flex items-center justify-center flex-shrink-0 mt-1">'
    +'<span class="material-symbols-outlined text-[16px] text-on-secondary-container" style="font-variation-settings:\'FILL\' 1">neurology</span></div>'
    +'<div class="flex-1 min-w-0 max-w-[min(78%,720px)]">'
    +'<div class="flex items-center gap-2 mb-1">'
    +'<span class="label-caps text-on-surface-variant">DataAgent AI</span>'
    +'<span class="status-badge ready">就绪</span></div>'
    +'<div class="bubble-ai text-body-md leading-relaxed">'+html+'</div>'
    +'<div class="flex gap-2 mt-1.5">'
    +'<button class="text-body-sm text-outline hover:text-secondary transition-colors cursor-pointer bg-transparent border-none p-0 flex items-center gap-1" onclick="copyBubble(this)">'
    +'<span class="material-symbols-outlined text-[14px]">content_copy</span> 复制</button>'
    +'<button class="text-body-sm text-outline hover:text-secondary transition-colors cursor-pointer bg-transparent border-none p-0 flex items-center gap-1" onclick="exportWordFromBubble(this)">'
    +'<span class="material-symbols-outlined text-[14px]">download</span> 导出</button>'
    +'</div></div></div>'));
}
function addSysMsg(html,color){
  const cls=color==='red'?'text-error border-error':color==='green'?'text-success border-success':color==='orange'?'text-warning border-warning':'text-secondary border-secondary';
  add(el('<div class="flex gap-3 max-w-full">'
    +'<div class="w-8 h-8 rounded bg-primary-container flex items-center justify-center flex-shrink-0">'
    +'<span class="material-symbols-outlined text-[16px] text-on-secondary-container">info</span></div>'
    +'<div class="flex-1 min-w-0 text-body-sm border-l-2 pl-3 py-1 '+cls+'">'+html+'</div>'
    +'</div>'));
}

// Table card — Stitch design
function renderTable(d){
  const cols=d.columns||[],rows=d.rows||[];
  let h='<div class="stitch-card my-2 ml-11 max-w-[min(96%,800px)]">'
    +'<div class="flex items-center justify-between px-4 py-3 border-b border-surface-container">'
    +'<div class="flex items-center gap-2">'
    +'<span class="material-symbols-outlined text-secondary text-[18px]">table_chart</span>'
    +'<span class="text-body-md font-semibold">'+esc(d.title||'查询结果')+'</span></div>'
    +'<span class="label-caps text-outline">'+rows.length+' 行</span></div>'
    +'<div class="overflow-x-auto max-h-[400px] overflow-y-auto">'
    +'<table class="stitch-table"><thead><tr>'
    +cols.map((c,i)=>'<th onclick="sortTbl(this,'+i+')" class="cursor-pointer hover:text-secondary">'+esc(c)+'</th>').join('')
    +'</tr></thead><tbody>';
  rows.forEach(r=>{
    h+='<tr>';
    r.forEach(v=>{
      const isNum=typeof v==='number'||(typeof v==='string'&&v!==''&&!isNaN(Number(v)));
      h+='<td'+(isNum?' class="text-right font-mono tabular-nums"':'')+'>'
        +(isNum?Number(v).toLocaleString():esc(String(v??'')))+'</td>';
    });
    h+='</tr>';
  });
  h+='</tbody></table></div>'
    +'<div class="flex items-center gap-4 px-4 py-2 border-t border-surface-container">';
  if(d.sql)h+='<span class="text-body-sm text-secondary cursor-pointer hover:underline flex items-center gap-1" onclick="toggleSql(this)">'
    +'<span class="material-symbols-outlined text-[14px]">code</span> SQL</span>'
    +'<pre style="display:none" class="mt-2 text-body-sm bg-surface-container-low p-2 rounded font-mono">'+esc(d.sql)+'</pre>';
  h+='<span class="text-body-sm text-secondary cursor-pointer hover:underline flex items-center gap-1" onclick="exportCSV(this)">'
    +'<span class="material-symbols-outlined text-[14px]">download</span> CSV</span>'
    +'<span class="text-body-sm text-secondary cursor-pointer hover:underline flex items-center gap-1" onclick="copyTable(this)">'
    +'<span class="material-symbols-outlined text-[14px]">content_copy</span> 复制</span>'
    +'<span class="text-body-sm text-secondary cursor-pointer hover:underline flex items-center gap-1" onclick="chartFromTable(this)">'
    +'<span class="material-symbols-outlined text-[14px]">bar_chart</span> 图表</span>'
    +'</div></div>';
  return el(h);
}
function toggleSql(el){
  const pre=el.nextElementSibling;
  if(pre)pre.style.display=pre.style.display==='none'?'block':'none';
}

// Report card — Stitch design
function renderReport(d){
  const md=d.markdown||'';
  const wf=d.word_filename||'';
  let dlBtn='';
  if(wf)dlBtn='<a href="/api/report/download/'+encodeURIComponent(wf)+'" download class="btn-ghost text-body-sm">'
    +'<span class="material-symbols-outlined text-[14px]">download</span> Word</a>';
  return el('<div class="stitch-card my-2 ml-11 max-w-[min(96%,800px)]">'
    +'<div class="flex items-center justify-between px-4 py-3 border-b border-surface-container">'
    +'<div class="flex items-center gap-2">'
    +'<span class="material-symbols-outlined text-secondary text-[18px]">description</span>'
    +'<span class="text-body-md font-semibold">报告已生成</span></div>'
    +dlBtn+'</div>'
    +'<div class="p-4 text-body-md leading-relaxed bubble agent">'+renderMd(md)+'</div>'
    +'</div>');
}

// Confirm / Ask cards — Stitch design
function renderConfirm(d){
  let tbl='';
  (d.summary||[]).forEach(s=>{
    tbl+='<tr><td class="text-body-sm py-1 pr-4 text-on-surface-variant">'+esc(s.label||'')+'</td>'
      +'<td class="text-body-sm py-1 font-semibold text-right tabular-nums">'+esc(String(s.value??''))+'</td></tr>';
  });
  if(tbl)tbl='<table class="w-full my-3">'+tbl+'</table>';
  let formula='';
  if(d.sql_or_formula)formula='<div class="my-2">'
    +'<span class="text-body-sm text-secondary cursor-pointer hover:underline flex items-center gap-1" onclick="toggleSql(this)">'
    +'<span class="material-symbols-outlined text-[14px]">code</span> 查看计算过程</span>'
    +'<pre style="display:none" class="mt-2 text-body-sm bg-surface-container-low p-2 rounded font-mono">'+esc(d.sql_or_formula)+'</pre></div>';
  return el('<div class="stitch-card my-2 ml-11 max-w-[600px] border-l-4 border-l-secondary">'
    +'<div class="p-4">'
    +'<div class="flex items-center gap-2 mb-2">'
    +'<span class="material-symbols-outlined text-secondary text-[20px]">task_alt</span>'
    +'<h3 class="text-body-md font-semibold">'+esc(d.title||'请确认')+'</h3></div>'
    +'<p class="text-body-sm text-on-surface-variant mb-3">请确认以上数值与口径是否正确</p>'
    +tbl+formula
    +'<div class="flex gap-3 mt-4">'
    +'<button class="btn-primary text-body-sm" onclick="doConfirm(true)">'
    +'<span class="material-symbols-outlined text-[16px]">check</span> 确认，继续</button>'
    +'<button class="btn-secondary text-body-sm" onclick="doConfirm(false)">取消</button>'
    +'</div></div></div>');
}
function renderAsk(d){
  const opts=(d.options||[]).map(o=>
    '<button class="suggestion-pill" onclick="doAsk(\''+esc(o)+'\')">'+esc(o)+'</button>'
  ).join('');
  return el('<div class="stitch-card my-2 ml-11 max-w-[600px] border-l-4 border-l-secondary">'
    +'<div class="p-4">'
    +'<div class="flex items-center gap-2 mb-2">'
    +'<span class="material-symbols-outlined text-secondary text-[20px]">help</span>'
    +'<h3 class="text-body-md font-semibold">'+esc(d.question||'请选择')+'</h3></div>'
    +'<p class="text-body-sm text-on-surface-variant mb-3">为保证数字正确，请选择一个选项</p>'
    +'<div class="flex flex-wrap gap-2">'+opts+'</div>'
    +'</div></div>');
}

// Quality report card — Stitch design
function renderQuality(qr,name){
  const crit=qr.critical_issues||[],warns=qr.warnings||[];
  let h='<div class="stitch-card my-2 ml-11 max-w-[600px] border-l-4 border-l-warning">'
    +'<div class="p-4">'
    +'<div class="flex items-center gap-2 mb-2">'
    +'<span class="material-symbols-outlined text-warning text-[20px]">verified</span>'
    +'<span class="text-body-md font-semibold">数据质量 · '+esc(name)+'</span></div>';
  if(crit.length){
    h+='<div class="text-body-sm text-error mt-2 mb-1 font-semibold">需要注意（'+crit.length+'项）</div>';
    crit.forEach(c=>{h+='<div class="text-body-sm text-error flex items-start gap-1.5 py-0.5">'
      +'<span class="material-symbols-outlined text-[14px] mt-0.5">error</span> '+esc(c)+'</div>';});
  }
  if(warns.length)warns.slice(0,5).forEach(w=>{
    h+='<div class="text-body-sm text-on-surface-variant flex items-start gap-1.5 py-0.5">'
      +'<span class="material-symbols-outlined text-[14px] mt-0.5">warning</span> '+esc(w)+'</div>';
  });
  if(!crit.length&&!warns.length)
    h+='<div class="text-body-sm text-success flex items-center gap-1.5 mt-2">'
      +'<span class="material-symbols-outlined text-[14px]">check_circle</span> 数据质量正常</div>';
  h+='</div></div>';add(el(h));
}

// ECharts
function renderChart(opt){
  if(typeof echarts==='undefined'){console.warn('ECharts not loaded');return;}
  const id='ch_'+Math.random().toString(36).slice(2,8);
  add(el('<div class="stitch-card my-2 ml-11 max-w-[min(96%,800px)]">'
    +'<div class="flex items-center justify-between px-4 py-3 border-b border-surface-container">'
    +'<div class="flex items-center gap-2">'
    +'<span class="material-symbols-outlined text-secondary text-[18px]">bar_chart</span>'
    +'<span class="text-body-md font-semibold">'+esc(opt.title||'图表')+'</span></div>'
    +'<div class="flex gap-3">'
    +'<span class="text-body-sm text-secondary cursor-pointer hover:underline flex items-center gap-1" onclick="downloadChartPng(\''+id+'\',\''+esc(opt.title||'chart')+'\')">'
    +'<span class="material-symbols-outlined text-[14px]">download</span> PNG</span>'
    +'<span class="text-body-sm text-secondary cursor-pointer hover:underline flex items-center gap-1" onclick="fullscreenChart(\''+id+'\')">'
    +'<span class="material-symbols-outlined text-[14px]">fullscreen</span></span>'
    +'</div></div>'
    +'<div id="'+id+'" style="width:100%;height:350px"></div></div>'));
  requestAnimationFrame(()=>{
    const dom=$(id);
    if(dom){
      try{
        const inst=echarts.init(dom);
        inst.setOption(opt.option||opt);
        dom._echartsInst=inst;
      }catch(e){console.error(e);}
    }
  });
}
function downloadChartPng(id,title){
  const dom=$(id);
  if(!dom||!dom._echartsInst)return;
  const url=dom._echartsInst.getDataURL({type:'png',pixelRatio:2,backgroundColor:'#fff'});
  const a=document.createElement('a');
  a.href=url;a.download=(title||'chart')+'.png';a.click();
}
function fullscreenChart(id){
  const dom=$(id);
  if(!dom)return;
  if(!document.fullscreenElement){
    dom.requestFullscreen?.();
    dom.style.height='100vh';
    if(dom._echartsInst)dom._echartsInst.resize();
  }else{
    document.exitFullscreen?.();
    dom.style.height='350px';
    if(dom._echartsInst)dom._echartsInst.resize();
  }
}

// Plan progress card — Stitch design
function renderPlanCard(plan){
  const steps=plan.steps||[];
  let rows=steps.map(s=>
    '<div class="flex items-center gap-3 py-2" id="ps-'+esc(s.id)+'">'
    +'<span class="material-symbols-outlined text-[18px] text-outline ps-dot">radio_button_unchecked</span>'
    +'<span class="text-body-sm font-medium">'+esc(s.name)+'</span>'
    +'<span class="text-body-sm text-on-surface-variant"> — '+esc(s.objective)+'</span>'
    +'</div>'
  ).join('');
  return el('<div class="stitch-card my-2 ml-11 max-w-[min(96%,800px)]">'
    +'<div class="flex items-center gap-2 px-4 py-3 border-b border-surface-container">'
    +'<span class="material-symbols-outlined text-secondary text-[18px]">checklist</span>'
    +'<span class="text-body-md font-semibold">执行计划（'+steps.length+'步）</span></div>'
    +'<div class="px-4 py-2 divide-y divide-surface-container">'+rows+'</div></div>');
}
function updatePlanStep(stepId,status){
  const el=$('ps-'+stepId);
  if(!el)return;
  const dot=el.querySelector('.ps-dot');
  if(!dot)return;
  if(status==='running'){
    dot.textContent='pending';dot.className='material-symbols-outlined text-[18px] text-secondary ps-dot animate-pulse';
  }else if(status==='done'){
    dot.textContent='check_circle';dot.className='material-symbols-outlined text-[18px] text-success ps-dot';
  }else{
    dot.textContent='cancel';dot.className='material-symbols-outlined text-[18px] text-error ps-dot';
  }
}
async function exportWordFromBubble(btn){
  const bubble=btn.closest('.flex-1')?.querySelector('.bubble-ai')||btn.closest('.bubble-outer')?.querySelector('.bubble');
  if(!bubble){toast('找不到报告内容','error');return;}
  const content=bubble.innerText||bubble.textContent;
  if(!content||content.length<10){toast('内容为空','error');return;}
  btn.disabled=true;const orig=btn.innerHTML;btn.innerHTML='<span class="material-symbols-outlined text-[14px]">hourglass_empty</span> 导出中…';
  try{
    const r=await api('POST','/api/report/export-word',{content:content,report_name:'report'});
    if(r.ok&&r.filename){
      toast('Word 文档已生成：'+r.filename,'success');
      const a=document.createElement('a');
      a.href='/api/report/download/'+encodeURIComponent(r.filename);
      a.download=r.filename;a.click();
    }else{toast('导出失败：'+(r.error||'未知错误'),'error');}
  }catch(e){toast('导出失败：'+e.message,'error');}
  btn.disabled=false;btn.innerHTML=orig;
}
function showChartPicker(btn){
  const card=btn.closest('.stitch-card')||btn.closest('.table-card');
  if(!card)return;
  const picker=card.querySelector('.chart-picker');
  if(!picker)return;
  if(picker.classList.contains('show')){picker.classList.remove('show');return;}
  const types=[['柱状图','bar'],['折线图','line'],['饼图','pie'],['散点图','scatter']];
  picker.innerHTML=types.map(([label,type])=>
    '<button class="chart-type-btn" onclick="renderTableChart(this.closest(\'.stitch-card\')||this.closest(\'.table-card\'),\''+type+'\',this.closest(\'.stitch-card\')?.querySelector(\'.chart-area\')||this.closest(\'.table-card\')?.querySelector(\'.chart-area\'))">'+label+'</button>'
  ).join('');
  picker.classList.add('show');
}
function renderTableChart(card,type,area){
  if(typeof echarts==='undefined'){toast('图表库未加载','error');return;}
  const table=card.querySelector('table');
  if(!table){toast('找不到数据表','error');return;}
  const headers=Array.from(table.querySelectorAll('thead th')).map(th=>th.textContent.trim());
  const rowEls=Array.from(table.querySelectorAll('tbody tr'));
  const rows=rowEls.map(r=>Array.from(r.querySelectorAll('td')).map(td=>td.textContent.trim()));
  if(!rows.length||headers.length<2){toast('数据不足，无法绘图','error');return;}
  const numCols=[];
  for(let c=1;c<headers.length;c++){
    const vals=rows.map(r=>parseFloat((r[c]||'').replace(/,/g,'')));
    if(vals.some(v=>!isNaN(v)))numCols.push(c);
  }
  if(!numCols.length){toast('无数值列，无法绘图','error');return;}
  const cats=rows.map(r=>r[0]||'');
  const id='ch_tbl_'+Math.random().toString(36).slice(2,8);
  if(!area){area=document.createElement('div');card.appendChild(area);}
  area.innerHTML='<div id="'+id+'" style="width:100%;height:280px"></div>';
  requestAnimationFrame(()=>{
    const dom=$(id);if(!dom)return;
    let option;
    if(type==='pie'){
      const col=numCols[0];
      const pieData=rows.map(r=>({name:r[0]||'',value:parseFloat((r[col]||'0').replace(/,/g,''))||0}));
      option={tooltip:{trigger:'item'},series:[{type:'pie',data:pieData,radius:'60%'}]};
    }else{
      const series=numCols.map(c=>({
        name:headers[c],type:type,
        data:rows.map(r=>parseFloat((r[c]||'0').replace(/,/g,''))||0)
      }));
      option={tooltip:{trigger:'axis'},legend:{},
        xAxis:{type:'category',data:cats,axisLabel:{rotate:30,fontSize:11}},
        yAxis:{type:'value'},series};
    }
    try{
      const ch=echarts.init(dom);ch.setOption(option);
      const picker=card.querySelector('.chart-picker');
      if(picker)picker.querySelectorAll('.chart-type-btn').forEach(b=>{
        b.classList.toggle('active',b.textContent.includes(
          type==='bar'?'柱':type==='line'?'折':type==='pie'?'饼':'散'));
      });
    }catch(e){console.error(e);}
  });
}
