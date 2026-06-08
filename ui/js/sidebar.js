// sidebar.js — Sidebar, sessions, tables, groups, skills, suggestions

function toggleSidebar(){$('bodyWrap').classList.toggle('collapsed');}
async function refreshSidebar(){loadSessions();loadTables();loadSkills();loadGroups();updateStatus();loadSuggestions();}
function toggleSec(name){const sec=$('sec-'+name);if(sec)sec.classList.toggle('open');}
function openSec(name){const sec=$('sec-'+name);if(sec&&!sec.classList.contains('open'))sec.classList.add('open');}

// Sessions
async function loadSessions(){
  try{
    const d=await api('GET','/api/sessions');
    const s=d.sessions||[];
    const list=$('sessionList');
    if(!s.length){list.innerHTML='<div class="s-item" style="color:var(--text-3)">暂无历史</div>';return;}
    list.innerHTML=s.slice(0,12).map(sess=>{
      const active=sess.id===ST.sessionId;
      return '<div class="s-item'+(active?' active':'')+'">'
        +'<span class="dot '+(active?'on':'off')+'"></span>'
        +'<span class="s-text" onclick="loadSes(\''+esc(sess.id)+'\')">'+esc(sess.title||'未命名')+'</span>'
        +'<span class="s-meta">'+((sess.updated_at||'').slice(5,16))+'</span>'
        +'<span class="item-del" onclick="deleteSession(\''+esc(sess.id)+'\',event)" title="删除">×</span>'
        +'</div>';
    }).join('');
  }catch(e){}
}
async function loadSes(id){
  try{
    const d=await api('GET','/api/sessions/'+id);
    clearChat();ST.sessionId=id;
    $('chatTitle').textContent=d.title||'历史会话';
    (d.messages||[]).forEach(m=>{
      if(m.role==='user'&&m.content)addUserBubble(m.content);
      else if(m.role==='assistant'&&m.content)addAgentHTML(renderMd(m.content));
    });
    addSysMsg('历史会话加载完成，可继续对话','blue');
    refreshSidebar();
  }catch(e){addSysMsg('加载失败：'+esc(e.message),'red');}
}
async function deleteSession(id,e){
  e.stopPropagation();
  if(!confirm('确定要删除这条会话记录吗？'))return;
  const r=await api('DELETE','/api/sessions/'+id);
  if(r.ok){
    if(ST.sessionId===id){ST.sessionId='';$('chatTitle').textContent='新对话';}
    loadSessions();toast('已删除会话');
  }else toast('删除失败：'+(r.error||''),'error');
}

// Tables
async function loadTables(){
  try{
    const d=await api('GET','/api/tables');
    const tables=d.tables||[];
    const cnt=$('tablesCount');if(cnt)cnt.textContent=tables.length;
    const list=$('tableList');
    if(!tables.length){list.innerHTML='<div class="s-item" style="color:var(--text-3)">暂无数据</div>';return;}
    list.innerHTML=tables.map(t=>{
      const color=t.type==='holding'?'var(--green)':t.type==='nav'?'var(--blue)':'var(--text-3)';
      return '<div class="s-item">'
        +'<span class="dot" style="background:'+color+'"></span>'
        +'<span class="s-text">'+esc(t.name)+'</span>'
        +'<span class="s-meta">'+t.rows+'行</span>'
        +'<span class="item-del" onclick="deleteTable(\''+esc(t.name)+'\')" title="卸载">×</span>'
        +'</div>';
    }).join('');
  }catch(e){}
}
async function deleteTable(name){
  if(!confirm('确定要卸载表「'+name+'」吗？数据文件不会被删除。'))return;
  const r=await api('DELETE','/api/tables/'+encodeURIComponent(name));
  if(r.ok){loadTables();toast('已卸载：'+name);}
  else toast('卸载失败：'+(r.error||''),'error');
}

// Skills
async function loadSkills(){
  try{
    const d=await api('GET','/api/skills');
    const list=$('skillList'),skills=d.skills||[];
    if(!skills.length){list.innerHTML='<div class="s-item" style="color:var(--text-3)">无可用技能</div>';return;}
    list.innerHTML=skills.map(s=>
      '<div class="s-item"><span class="s-text">'+esc(s.name)+'</span>'
      +'<span class="s-tag '+(s.calc_type==='fixed'?'fixed':'exp')+'">'
      +(s.calc_type==='fixed'?'固化':'探索')+'</span></div>'
    ).join('');
  }catch(e){}
}

// Groups
const _grpMap={};
function grpSid(name){return'g_'+String(name||'').replace(/[^a-zA-Z0-9㐀-鿿豈-﫿]/g,'_');}

async function loadGroups(){
  try{
    const r=await fetch('/api/groups');if(!r.ok)return;
    const d=await r.json();const groups=d.groups||{};
    const list=$('groupList');
    const entries=Object.entries(groups);
    if(!entries.length){
      list.innerHTML='<div class="s-item" style="color:var(--text-3)">暂无集团系</div>';return;
    }
    Object.keys(_grpMap).forEach(k=>delete _grpMap[k]);
    list.innerHTML=entries.map(([name,members])=>{
      const sid=grpSid(name);
      _grpMap[sid]=name;
      const ms=(members||[]).map(m=>
        '<div class="grp-member" data-group="'+esc(name)+'" data-member="'+esc(m)+'">'
        +'<span class="m-name">'+esc(m)+'</span>'
        +'<span class="m-del" onclick="removeMemberEl(this)">×</span>'
        +'</div>'
      ).join('');
      return '<div class="grp-item" id="'+sid+'">'
        +'<div class="grp-hd" onclick="toggleGrp(\''+sid+'\')">'
        +'<span class="grp-arr">▸</span>'
        +'<span class="grp-name">'+esc(name)+'</span>'
        +'<span class="grp-cnt">'+(members||[]).length+'</span>'
        +'<span class="grp-del" onclick="event.stopPropagation();confirmDeleteGroup(\''+sid+'\')" title="删除集团">×</span>'
        +'</div>'
        +'<div class="grp-bd">'+ms
        +'<div class="grp-add">'
        +'<input type="text" id="addm-'+sid+'" placeholder="添加主体名称"'
        +' onkeydown="if(event.key===\'Enter\')addMember(\''+sid+'\')" />'
        +'<button onclick="addMember(\''+sid+'\')">+</button>'
        +'</div></div></div>';
    }).join('');
  }catch(e){}
}
function toggleGrp(sid){
  const item=document.getElementById(sid);
  if(item)item.classList.toggle('open');
}
async function addMember(sid){
  const groupName=_grpMap[sid];if(!groupName)return;
  const inp=document.getElementById('addm-'+sid);if(!inp)return;
  const entity=inp.value.trim();if(!entity)return;
  const r=await api('POST','/api/groups/'+encodeURIComponent(groupName)+'/members',{entity});
  if(r.ok){inp.value='';loadGroups();toast('已添加：'+entity,'success');}
  else toast('添加失败：'+(r.error||''),'error');
}
function removeMemberEl(btn){
  const item=btn.closest('.grp-member');if(!item)return;
  removeMember(item.dataset.group,item.dataset.member);
}
async function removeMember(groupName,entity){
  const r=await api('DELETE','/api/groups/'+encodeURIComponent(groupName)+'/members',{entity});
  if(r.ok){loadGroups();toast('已移除：'+entity);}
  else toast('移除失败：'+(r.error||''),'error');
}
async function confirmDeleteGroup(sid){
  const name=_grpMap[sid];if(!name)return;
  if(!confirm('确定要删除集团系「'+name+'」及其所有主体吗？'))return;
  const r=await api('DELETE','/api/groups/'+encodeURIComponent(name));
  if(r.ok){loadGroups();toast('已删除：'+name,'success');}
  else toast('删除失败：'+(r.error||''),'error');
}
function showCreateGroup(){
  const name=prompt('输入新集团系名称：');
  if(!name||!name.trim())return;
  createGroup(name.trim());
}
async function createGroup(name){
  const r=await api('POST','/api/groups',{name,members:[]});
  if(r.ok){loadGroups();toast('已创建：'+name,'success');openSec('groups');}
  else toast('创建失败：'+(r.error||''),'error');
}

// Status & suggestions
async function updateStatus(){
  try{
    const d=await api('GET','/api/status');
    const cnt=$('tablesCount');if(cnt)cnt.textContent=d.tables_count||0;
    const dot=$('llmDot');
    if(dot){dot.className='dot '+(d.llm_ok?'on':'off');}
  }catch(e){}
}
async function loadSuggestions(){
  try{
    const d=await api('GET','/api/suggestions');
    const sug=d.suggestions||[];
    const bar=$('suggestionsBar');
    if(!sug.length||!bar){return;}
    bar.style.display='block';
    bar.innerHTML='<div style="display:flex;gap:6px;flex-wrap:wrap;padding-bottom:8px;">'
      +'<span style="font-size:11.5px;color:var(--text-3);align-self:center">推荐：</span>'
      +sug.map(s=>'<button class="q-btn" onclick="fillAndSend(\''+esc(s)+'\')" style="font-size:11.5px">'+esc(s)+'</button>').join('')
      +'</div>';
  }catch(e){}
}
function fillAndSend(text){
  const inp=$('input');if(!inp)return;
  inp.value=text;autoResize(inp);sendMessage();
}

// Quick examples
const _EXAMPLES={
  '数据分析':'查询各产品的主要持仓情况，按市值降序排列',
  '合规检查':'检查主体集中度是否有超标情况，阈值10%',
  '报告生成':'生成产品运作报告，包括净值分析和持仓分布',
  '图表':'生成持仓资产类型分布饼图',
};
function fillExample(cap){
  const inp=$('input');if(!inp)return;
  inp.value=_EXAMPLES[cap]||cap;
  autoResize(inp);inp.focus();
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

function checkMention(ta){
  const popup=$('mentionPopup');
  const val=ta.value,pos=ta.selectionStart;
  const before=val.slice(0,pos);
  const match=before.match(/@([^\s@]*)$/);
  if(!match){popup.classList.remove('show');return;}
  const query=match[1].toLowerCase();
  const tables=(window._cachedTables||[]).filter(t=>
    !query||t.name.toLowerCase().includes(query));
  if(!tables.length){popup.classList.remove('show');return;}
  _mentionIdx=-1;
  popup.innerHTML=tables.slice(0,8).map(t=>
    '<div class="mention-item" data-name="'+esc(t.name)+'" onclick="mentionSelect(\''+esc(t.name)+'\')">'
    +'<span class="dot" style="background:'+(t.type==='holding'?'var(--green)':t.type==='nav'?'var(--blue)':'var(--text-3)')+'"></span>'
    +'<span class="mi-name">'+esc(t.name)+'</span>'
    +'<span class="mi-meta">'+t.rows+'行</span></div>'
  ).join('');
  popup.classList.add('show');
}
function mentionNav(dir){
  const popup=$('mentionPopup');
  const items=[...popup.querySelectorAll('.mention-item')];
  if(!items.length)return;
  items.forEach(i=>i.classList.remove('active'));
  _mentionIdx=(_mentionIdx+dir+items.length)%items.length;
  items[_mentionIdx].classList.add('active');
}
function mentionSelect(name){
  const ta=$('input'),val=ta.value,pos=ta.selectionStart;
  const before=val.slice(0,pos),after=val.slice(pos);
  const atIdx=before.lastIndexOf('@');
  ta.value=before.slice(0,atIdx)+'@'+name+' '+after;
  ta.selectionStart=ta.selectionEnd=atIdx+name.length+2;
  $('mentionPopup').classList.remove('show');
  ta.focus();
}
function triggerSkill(name){
  $('input').value='@skill:'+name+' ';
  $('input').focus();
}
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
    if(d.field_map&&Object.keys(d.field_map).length){
      html+='<div style="margin-top:14px;font-size:12px;color:var(--text-2)">'
        +'<b>字段映射：</b>'+Object.entries(d.field_map).map(([k,v])=>esc(k)+'→'+esc(v)).join('、')
        +'</div>';
    }
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
