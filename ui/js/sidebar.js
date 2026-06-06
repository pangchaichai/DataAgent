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
