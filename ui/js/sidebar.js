// sidebar.js — Sidebar core, sessions, skills, @mention, suggestions, resize

function toggleSidebar(){
  const bw=$('bodyWrap');
  bw.classList.toggle('collapsed');
  if(bw.classList.contains('collapsed')){
    localStorage.setItem('da_sidebar_collapsed','1');
  }else{
    localStorage.removeItem('da_sidebar_collapsed');
    const saved=localStorage.getItem('da_sidebar_w');
    if(saved)bw.style.setProperty('--sidebar-w',saved+'px');
  }
}

(function initSidebarResize(){
  const handle=$('resizeHandle');
  const bw=$('bodyWrap');
  if(!handle||!bw)return;
  const MIN_W=120,MAX_W=480,COLLAPSE_THRESHOLD=60,DEFAULT_W=240;
  let startX,startW,dragging=false;

  const saved=localStorage.getItem('da_sidebar_w');
  if(saved)bw.style.setProperty('--sidebar-w',saved+'px');
  if(localStorage.getItem('da_sidebar_collapsed')==='1')bw.classList.add('collapsed');

  handle.addEventListener('mousedown',e=>{
    e.preventDefault();
    if(bw.classList.contains('collapsed')){
      toggleSidebar();
      return;
    }
    dragging=true;
    startX=e.clientX;
    startW=parseInt(getComputedStyle(bw).getPropertyValue('--sidebar-w'))||DEFAULT_W;
    bw.classList.add('resizing');
    handle.classList.add('active');
    document.addEventListener('mousemove',onMove);
    document.addEventListener('mouseup',onUp);
  });
  handle.addEventListener('dblclick',()=>toggleSidebar());

  function onMove(e){
    if(!dragging)return;
    const diff=e.clientX-startX;
    const newW=Math.min(MAX_W,Math.max(0,startW+diff));
    if(newW<COLLAPSE_THRESHOLD){
      bw.classList.add('collapsed');
    }else{
      bw.classList.remove('collapsed');
      bw.style.setProperty('--sidebar-w',Math.max(MIN_W,newW)+'px');
    }
  }
  function onUp(){
    dragging=false;
    bw.classList.remove('resizing');
    handle.classList.remove('active');
    document.removeEventListener('mousemove',onMove);
    document.removeEventListener('mouseup',onUp);
    if(bw.classList.contains('collapsed')){
      localStorage.setItem('da_sidebar_collapsed','1');
    }else{
      localStorage.removeItem('da_sidebar_collapsed');
      const cur=parseInt(getComputedStyle(bw).getPropertyValue('--sidebar-w'))||DEFAULT_W;
      localStorage.setItem('da_sidebar_w',cur);
    }
  }
})();
async function refreshSidebar(){
  if(ST.currentPage==='/chat'){loadSessions();loadSuggestions();}
  loadTables();updateStatus();
  if(ST.currentPage==='/data')DataPage._renderTableList();
  if(ST.currentPage==='/rules'){RulesPage._renderSkills();RulesPage._renderGroups();}
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
  const _typeLabel={'holding':'持仓','nav':'净值','rating_entity':'主体评级','rating_bond':'债券评级','monitoring':'监控','unknown':'其他'};
  const _typeColor={'holding':'var(--green)','nav':'var(--blue)','rating_entity':'var(--orange,#e67e22)','rating_bond':'var(--orange,#e67e22)','monitoring':'var(--purple,#9b59b6)'};
  popup.innerHTML=tables.slice(0,8).map(t=>{
    const color=_typeColor[t.type]||'var(--text-3)';
    const label=_typeLabel[t.type]||t.type||'其他';
    return '<div class="mention-item" data-name="'+esc(t.name)+'" onclick="mentionSelect(\''+esc(t.name)+'\')">'
    +'<span class="dot" style="background:'+color+'"></span>'
    +'<span class="mi-name">'+esc(t.name)+'</span>'
    +'<span class="mi-meta" style="margin-left:auto">'+label+' · '+t.rows+'行</span></div>';
  }).join('');
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

// Append @tablename at end of chat input (click from sidebar)
function insertMention(name){
  const ta=$('input');
  if(!ta)return;
  const cur=ta.value;
  ta.value=(cur&&!cur.endsWith(' ')?cur+' ':cur)+'@'+name+' ';
  ta.selectionStart=ta.selectionEnd=ta.value.length;
  if(typeof $!=='undefined')$('mentionPopup').classList.remove('show');
  ta.focus();
  if(typeof autoResize==='function')autoResize(ta);
}

// Render table list in chat sidebar — all types including unknown, click inserts @mention
function renderChatTableList(tables){
  const list=$('chatTableList');
  if(!list)return;
  if(!tables||!tables.length){
    list.innerHTML='<div class="s-item" style="color:var(--text-3)">暂无数据 — <span class="s-clickable" onclick="triggerUpload()" style="cursor:pointer">上传文件</span></div>';
    return;
  }
  const _typeLabel={'holding':'持仓','nav':'净值','rating_entity':'主体评级','rating_bond':'债券评级','monitoring':'监控','unknown':'其他'};
  const _typeColor={'holding':'var(--green)','nav':'var(--blue)','rating_entity':'var(--orange,#e67e22)','rating_bond':'var(--orange,#e67e22)','monitoring':'var(--purple,#9b59b6)'};
  list.innerHTML=tables.map(t=>{
    const color=_typeColor[t.type]||'var(--text-3)';
    const label=_typeLabel[t.type]||'其他';
    return '<div class="s-item">'
      +'<span class="dot" style="background:'+color+'"></span>'
      +'<span class="s-text s-clickable" onclick="insertMention(\''+esc(t.name)+'\')" title="点击插入 @提及">'+esc(t.name)+'</span>'
      +'<span class="s-meta">'+label+' · '+t.rows+'行</span>'
      +'</div>';
  }).join('');
}
