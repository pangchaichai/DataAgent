// sidebar.js — Sidebar core, sessions, skills, @mention, suggestions

function toggleSidebar(){$('bodyWrap').classList.toggle('collapsed');}
async function refreshSidebar(){
  if(ST.currentPage==='/chat'){loadSessions();loadSuggestions();}
  loadTables();loadSkills();loadGroups();loadWorkdir();updateStatus();
}
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
    if(ST.currentPage!=='/chat')Router.navigateTo('/chat');
    const d=await api('GET','/api/sessions/'+id);
    clearChat();ST.sessionId=id;
    $('chatTitle').textContent=d.title||'历史会话';
    (d.messages||[]).forEach(m=>{
      if(m.skip_display)return;
      const text=m.display_content||m.content;
      if(m.role==='user'&&text)addUserBubble(text);
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

// Skills
async function loadSkills(){
  try{
    const d=await api('GET','/api/skills/status');
    const list=$('skillList'),skills=d.skills||[];
    if(!skills.length){list.innerHTML='<div class="s-item" style="color:var(--text-3)">无可用技能</div>';return;}
    list.innerHTML=skills.map(s=>{
      const readyCls=s.ready?'skill-ready':'skill-missing';
      const readyLabel=s.ready?'就绪':'缺数据';
      const desc=(s.description||'').slice(0,55)+(s.description&&s.description.length>55?'…':'');
      return '<div class="skill-card">'
        +'<div class="skill-card-hd">'
        +'<span class="s-text">'+esc(s.name)+'</span>'
        +'<span class="skill-badge '+readyCls+'">'+readyLabel+'</span>'
        +'</div>'
        +(desc?'<div class="skill-desc">'+esc(desc)+'</div>':'')
        +'<div class="skill-card-ft">'
        +(s.ready
          ?'<button class="skill-exec-btn" onclick="executeSkill(\''+esc(s.name)+'\')">执行</button>'
          :'<span class="skill-hint">缺：'+esc((s.missing_files||[]).slice(0,2).join('、'))+'</span>')
        +'</div>'
        +'</div>';
    }).join('');
  }catch(e){}
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

// @mention autocomplete
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
