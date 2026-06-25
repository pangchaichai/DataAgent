// main.js — App init, keyboard/drag-drop handlers, theme, health polling

// Keyboard shortcuts
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){
    if(ST._es)stopStream();
    else if($('aboutPanel').style.display==='block')closeAbout();
    else if($('sbPanel').classList.contains('show'))closeSkillBuilder();
    else if($('settingsPanel').classList.contains('show'))closeSettings();
    else if(ST.currentPage && ST.currentPage !== '/chat')Router.navigateTo('/chat');
  }
});

function onKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();}}
function triggerUpload(){$('fileInput').click();}
function clearChat(){chat.innerHTML='';}

function buildWelcomePanel(tables){
  if(!tables||!tables.length){
    return '<div class="welcome" id="welcomePanel">'
      +'<div class="welcome-header"><h2>DataAgent</h2><p>专业的金融资管数据分析助手</p></div>'
      +'<div class="welcome-cards">'
      +'<div class="wc-card" onclick="triggerUpload()">'
        +'<div class="wc-icon">📊</div>'
        +'<div class="wc-card-body"><div class="wc-title">上传数据分析</div>'
        +'<div class="wc-desc">上传 CSV/Excel 持仓、净值、评级文件</div></div>'
      +'</div>'
      +'<div class="wc-card" onclick="sendQuick(\'帮我检查主体集中度是否有超标情况\')">'
        +'<div class="wc-icon">✅</div>'
        +'<div class="wc-card-body"><div class="wc-title">合规监控</div>'
        +'<div class="wc-desc">主体/单券集中度自动检查</div></div>'
      +'</div>'
      +'<div class="wc-card" onclick="openSkillBuilder()">'
        +'<div class="wc-icon">⚡</div>'
        +'<div class="wc-card-body"><div class="wc-title">创建分析技能</div>'
        +'<div class="wc-desc">自然语言描述，AI 生成可复用技能</div></div>'
      +'</div>'
      +'<div class="wc-card" onclick="$(\'input\').focus()">'
        +'<div class="wc-icon">💬</div>'
        +'<div class="wc-card-body"><div class="wc-title">通用问答</div>'
        +'<div class="wc-desc">金融知识、文档分析、行业咨询</div></div>'
      +'</div>'
      +'</div>'
      +'<div id="welcomeExamples" class="welcome-examples" style="margin-top:20px"></div>'
      +'</div>';
  }
  const n=tables.length;
  const hasHolding=tables.find(t=>t.type==='holding');
  const hasNav=tables.find(t=>t.type==='nav');
  const skills=[];
  if(hasHolding)skills.push('<span class="wc-skill-btn" onclick="sendQuick(\'帮我检查主体集中度\')">✅ 合规检查</span>');
  if(hasHolding)skills.push('<span class="wc-skill-btn" onclick="sendQuick(\'查询持仓情况，按市值降序\')">📊 持仓查询</span>');
  if(hasNav)skills.push('<span class="wc-skill-btn" onclick="sendQuick(\'净值最近变动情况\')">📈 净值分析</span>');
  const examples=[];
  if(hasHolding)examples.push('@'+hasHolding.name+' 按主体统计持仓市值前10');
  if(hasNav)examples.push('@'+hasNav.name+' 最近净值变动如何');
  if(!examples.length)examples.push('已加载的数据有哪些？各表结构是什么？');
  return '<div class="welcome" id="welcomePanel">'
    +'<div class="welcome-header"><h2>DataAgent</h2><p>已加载 '+n+' 张表，可以开始分析</p></div>'
    +(skills.length?'<div class="welcome-skills">'+skills.join('')+'</div>':'')
    +'<div class="welcome-divider"></div>'
    +'<div class="welcome-section-title">试试问我</div>'
    +'<div id="welcomeExamples" class="welcome-examples">'
    +examples.slice(0,3).map(ex=>'<div class="wex-item" onclick="sendQuick(\''+esc(ex)+'\')">'
      +'<span class="wex-icon">→</span>'+esc(ex)+'</div>').join('')
    +'</div></div>';
}

async function resetChat(){
  if(ST._es){ST._es.close();ST._es=null;}
  ST.locked=false;lockInput(false);endStream();finPW();
  clearChat();
  const tables=window._lastLoadedTables||[];
  chat.innerHTML=buildWelcomePanel(tables);
  try{await api('POST','/api/reset');}catch(e){}
  $('chatTitle').textContent='新对话';
  ST.sessionId='';refreshSidebar();
  setTimeout(()=>$('input').focus(),100);
}

function toggleTheme(){
  const h=document.documentElement;
  h.dataset.theme=h.dataset.theme==='dark'?'light':'dark';
}

function showAbout(){
  $('aboutOverlay').style.display='flex';
  $('aboutPanel').style.display='block';
}
function closeAbout(){
  $('aboutOverlay').style.display='none';
  $('aboutPanel').style.display='none';
}

// Drag & drop onto input bar
const ibar=$('inputbar');
ibar.addEventListener('dragover',e=>{e.preventDefault();ibar.classList.add('dragover');});
ibar.addEventListener('dragleave',()=>ibar.classList.remove('dragover'));
ibar.addEventListener('drop',e=>{
  e.preventDefault();ibar.classList.remove('dragover');
  handleFiles(e.dataTransfer.files);
});
const _ul=$('uploadLink');if(_ul)_ul.addEventListener('click',()=>{$('fileInput').click();});

function updateTableCountHeader(n){
  const chip=$('tableCountChip');if(!chip)return;
  if(n>0){chip.style.display='';chip.querySelector('#tableCountH').textContent=n;}
  else{chip.style.display='none';}
}

// Health polling
function _applyHealth(d){
  const statusEl=$('llmStatus');
  const dotEl=$('llmDot');
  if(statusEl){
    const ready=d.llm_name&&d.llm_name!=='--';
    statusEl.textContent=ready?'AI 就绪':'AI 离线';
    if(dotEl)dotEl.className=ready?'dot on':'dot off';
  }
}
async function pollHealth(){
  try{const d=await api('GET','/api/health');_applyHealth(d);}catch(e){}
}

// Router setup
Router.register('/home', {});
Router.register('/data', DataPage);
Router.register('/rules', RulesPage);
Router.register('/chat', {
  onEnter() { scrollBottom(); setTimeout(()=>$('input').focus(),100); }
});
Router.register('/audit', {});
Router.register('/settings', {
  onEnter() { loadSettings(); }
});

// Init
AgentStatus.init();
initNav();
Router.init();
// Render initial welcome panel (no data yet)
const _initWelcome=buildWelcomePanel([]);
const _chatEl=document.getElementById('chat');
if(_chatEl){_chatEl.insertAdjacentHTML('afterbegin',_initWelcome);}
refreshSidebar();
setTimeout(()=>$('input').focus(),200);
pollHealth();
setInterval(()=>pollHealth(),15000);

function updateWelcomeExamples(tables){
  window._lastLoadedTables=tables;
  updateTableCountHeader(tables.length);
  const panel=$('welcomePanel');
  if(panel){
    const parent=panel.parentNode;
    const next=panel.nextSibling;
    parent.removeChild(panel);
    const tmp=document.createElement('div');
    tmp.innerHTML=buildWelcomePanel(tables);
    parent.insertBefore(tmp.firstChild,next);
  }
}
