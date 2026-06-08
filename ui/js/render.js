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

// Bubble helpers
function addUserBubble(text){
  add(el('<div class="msg-row user"><div class="bubble user">'+esc(text)+'</div></div>'));
}
function addAgentHTML(html){
  add(el('<div class="msg-row">'
    +'<div class="agent-avatar">DA</div>'
    +'<div class="bubble-outer">'
    +'<div class="bubble agent">'+html+'</div>'
    +'<div class="msg-actions">'
    +'<button class="msg-action-btn" onclick="copyBubble(this)">复制</button>'
    +'</div></div></div>'));
}
function addSysMsg(html,color){
  const c=color==='red'?'var(--red)':color==='green'?'var(--green)':color==='orange'?'var(--orange)':'var(--blue)';
  add(el('<div class="msg-row"><div class="agent-avatar">DA</div>'
    +'<div class="bubble agent" style="border-left:3px solid '+c+';font-size:13px;">'
    +html+'</div></div>'));
}

// Table card
function renderTable(d){
  const cols=d.columns||[],rows=d.rows||[];
  let h='<div class="table-card"><div class="tc-head">'
    +'<span class="tc-title">'+esc(d.title||'查询结果')+'</span>'
    +'<span class="tc-meta">'+rows.length+'行</span></div>'
    +'<div class="dt-wrap"><table class="dt"><thead><tr>'
    +cols.map((c,i)=>'<th onclick="sortTbl(this,'+i+')">'+esc(c)+'</th>').join('')
    +'</tr></thead><tbody>';
  rows.forEach(r=>{
    h+='<tr>';
    r.forEach(v=>{
      const isNum=typeof v==='number'||(typeof v==='string'&&v!==''&&!isNaN(Number(v)));
      h+='<td'+(isNum?' class="num"':'')+'>'
        +(isNum?Number(v).toLocaleString():esc(String(v??'')))+'</td>';
    });
    h+='</tr>';
  });
  h+='</tbody></table></div><div class="tc-actions">';
  if(d.sql)h+='<span class="tc-link" onclick="toggleSql(this)">查看SQL</span>'
    +'<pre style="display:none;margin-top:4px;font-size:12px;background:var(--bg-code);'
    +'padding:6px 8px;border-radius:4px">'+esc(d.sql)+'</pre>';
  h+='<span class="tc-link" onclick="exportCSV(this)">导出CSV</span>'
    +'<span class="tc-link" onclick="copyTable(this)">复制</span>'
    +'<span class="tc-link" onclick="chartFromTable(this)">生成图表</span>'
    +'</div></div>';
  return el(h);
}
function toggleSql(el){
  const pre=el.nextElementSibling;
  if(pre)pre.style.display=pre.style.display==='none'?'block':'none';
}

// Report card
function renderReport(d){
  const md=d.markdown||'';
  const wf=d.word_filename||'';
  let dlBtn='';
  if(wf)dlBtn='<a href="/api/report/download/'+encodeURIComponent(wf)+'" download class="btn ghost" style="margin-left:8px">下载 Word</a>';
  return el('<div class="report-card">'
    +'<div class="report-header">'
    +'<span style="font-weight:600">📄 报告已生成</span>'+dlBtn
    +'</div>'
    +'<div class="report-body">'+renderMd(md)+'</div>'
    +'</div>');
}

// Confirm / Ask cards
function renderConfirm(d){
  let tbl='';
  (d.summary||[]).forEach(s=>{
    tbl+='<tr><td>'+esc(s.label||'')+'</td><td>'+esc(String(s.value??''))+'</td></tr>';
  });
  if(tbl)tbl='<table class="summary-table">'+tbl+'</table>';
  let formula='';
  if(d.sql_or_formula)formula='<div style="margin:8px 0">'
    +'<span class="tc-link" onclick="toggleSql(this)">查看公式/SQL</span>'
    +'<pre style="display:none;margin-top:4px;font-size:12px">'+esc(d.sql_or_formula)+'</pre></div>';
  return el('<div class="action-card">'
    +'<h3>'+esc(d.title||'请确认')+'</h3>'
    +'<div class="sub">请确认以上数值与口径是否正确</div>'
    +tbl+formula
    +'<button class="btn primary" onclick="doConfirm(true)">确认，继续</button>'
    +'<button class="btn ghost" style="margin-left:8px" onclick="doConfirm(false)">取消</button>'
    +'</div>');
}
function renderAsk(d){
  const opts=(d.options||[]).map(o=>
    '<button class="btn opt" onclick="doAsk(\''+esc(o)+'\')">'+esc(o)+'</button>'
  ).join('');
  return el('<div class="action-card">'
    +'<h3>'+esc(d.question||'请选择')+'</h3>'
    +'<div class="sub">为保证数字正确，请选择一个选项</div>'
    +opts+'</div>');
}

// Quality report card
function renderQuality(qr,name){
  const crit=qr.critical_issues||[],warns=qr.warnings||[];
  let h='<div class="quality-card"><b>数据质量 · '+esc(name)+'</b>';
  if(crit.length){
    h+='<div style="color:var(--red);margin-top:4px">需要注意（'+crit.length+'项）</div>';
    crit.forEach(c=>{h+='<div class="q-row q-crit">• '+esc(c)+'</div>';});
  }
  if(warns.length)warns.slice(0,5).forEach(w=>{
    h+='<div class="q-row" style="color:var(--text-2)">• '+esc(w)+'</div>';
  });
  if(!crit.length&&!warns.length)
    h+='<div style="color:var(--green);margin-top:4px">数据质量正常</div>';
  h+='</div>';add(el(h));
}

// ECharts
function renderChart(opt){
  if(typeof echarts==='undefined'){console.warn('ECharts not loaded');return;}
  const id='ch_'+Math.random().toString(36).slice(2,8);
  add(el('<div class="table-card">'
    +'<div class="tc-head">'
    +'<span class="tc-title">'+esc(opt.title||'图表')+'</span>'
    +'<span class="tc-link" style="margin-left:auto" onclick="downloadChartPng(\''+id+'\',\''+esc(opt.title||'chart')+'\')">下载PNG</span>'
    +'<span class="tc-link" style="margin-left:8px" onclick="fullscreenChart(\''+id+'\')">全屏</span>'
    +'</div>'
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

// Plan progress card
function renderPlanCard(plan){
  const steps=plan.steps||[];
  let rows=steps.map(s=>
    '<div class="plan-step" id="ps-'+esc(s.id)+'">'
    +'<span class="ps-dot">○</span>'
    +'<span class="ps-name">'+esc(s.name)+'</span>'
    +'<span class="ps-obj" style="color:var(--text-3);font-size:12px"> — '+esc(s.objective)+'</span>'
    +'</div>'
  ).join('');
  return el('<div class="table-card" style="padding:12px 16px">'
    +'<div style="font-weight:600;margin-bottom:8px">📋 执行计划（'+steps.length+'步）</div>'
    +rows+'</div>');
}
function updatePlanStep(stepId,status){
  const el=$('ps-'+stepId);
  if(!el)return;
  const dot=el.querySelector('.ps-dot');
  if(dot){
    dot.textContent=status==='running'?'◉':status==='done'?'●':'✗';
    dot.style.color=status==='done'?'var(--green)':status==='failed'?'var(--red)':'var(--blue)';
  }
}
async function exportWordFromBubble(btn){
  const bubble=btn.closest('.bubble-outer')?.querySelector('.bubble');
  if(!bubble){toast('找不到报告内容','error');return;}
  const content=bubble.innerText||bubble.textContent;
  if(!content||content.length<10){toast('内容为空','error');return;}
  btn.disabled=true;btn.textContent='导出中…';
  try{
    const r=await api('POST','/api/report/export-word',{content:content,report_name:'report'});
    if(r.ok&&r.filename){
      toast('Word 文档已生成：'+r.filename,'success');
      const a=document.createElement('a');
      a.href='/api/report/download/'+encodeURIComponent(r.filename);
      a.download=r.filename;a.click();
    }else{toast('导出失败：'+(r.error||'未知错误'),'error');}
  }catch(e){toast('导出失败：'+e.message,'error');}
  btn.disabled=false;btn.textContent='⬇ 导出 Word';
}
function showChartPicker(btn){
  const card=btn.closest('.table-card');
  if(!card)return;
  const picker=card.querySelector('.chart-picker');
  if(!picker)return;
  if(picker.classList.contains('show')){picker.classList.remove('show');return;}
  const types=[['柱状图','bar'],['折线图','line'],['饼图','pie'],['散点图','scatter']];
  picker.innerHTML=types.map(([label,type])=>
    '<button class="chart-type-btn" onclick="renderTableChart(this.closest(\'.table-card\'),\''+type+'\',this.closest(\'.table-card\').querySelector(\'.chart-area\'))">'+label+'</button>'
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
