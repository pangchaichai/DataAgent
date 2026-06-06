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
