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
      +'<div class="welcome-header"><h2>DataAgent</h2><p>金融资管数据分析助手</p></div>'
      +'<div class="welcome-cards">'
      +'<div class="wc-card" onclick="triggerUpload()">'
        +'<div class="wc-icon">📂</div>'
        +'<div class="wc-card-body"><div class="wc-title">上传数据</div>'
        +'<div class="wc-desc">CSV/Excel 持仓、净值、评级文件</div></div>'
      +'</div>'
      +'<div class="wc-card" onclick="sendQuick(\'帮我检查主体集中度是否有超标情况\')">'
        +'<div class="wc-icon">✅</div>'
        +'<div class="wc-card-body"><div class="wc-title">合规检查</div>'
        +'<div class="wc-desc">主体/单券集中度自动监控</div></div>'
      +'</div>'
      +'<div class="wc-card" onclick="sendQuick(\'生成产品运作报告\')">'
        +'<div class="wc-icon">📄</div>'
        +'<div class="wc-card-body"><div class="wc-title">生成报告</div>'
        +'<div class="wc-desc">产品运作报告、持仓分析报告</div></div>'
      +'</div>'
      +'<div class="wc-card" onclick="$(\'input\').focus()">'
        +'<div class="wc-icon">💬</div>'
        +'<div class="wc-card-body"><div class="wc-title">自由提问</div>'
        +'<div class="wc-desc">金融知识、数据查询、文档分析</div></div>'
      +'</div>'
      +'</div>'
      +'<div style="margin-top:16px;font-size:12px;color:var(--text-3);text-align:center">'
      +'上传数据后可解锁基于真实数据的分析'
      +'</div>'
      +'<div id="welcomeExamples" class="welcome-examples" style="margin-top:16px"></div>'
      +'</div>';
  }
  const n=tables.length;
  const hasHolding=tables.find(t=>t.type==='holding');
  const hasNav=tables.find(t=>t.type==='nav');
  const hasRating=tables.find(t=>t.type==='rating_entity'||t.type==='rating_bond');
  const typeCount={};
  tables.forEach(t=>{typeCount[t.type]=(typeCount[t.type]||0)+1;});
  const _tl={'holding':'持仓','nav':'净值','rating_entity':'主体评级','rating_bond':'债券评级','monitoring':'监控','unknown':'其他'};
  const typeSummary=Object.entries(typeCount)
    .map(([k,v])=>'<span style="display:inline-block;font-size:12px;padding:1px 8px;border-radius:10px;background:var(--blue-bg);color:var(--blue);margin:0 2px">'+(_tl[k]||k)+(v>1?' ×'+v:'')+'</span>')
    .join('');
  const skills=[];
  if(hasHolding)skills.push('<span class="wc-skill-btn" onclick="sendQuick(\'帮我检查主体集中度\')">✅ 合规检查</span>');
  if(hasHolding)skills.push('<span class="wc-skill-btn" onclick="sendQuick(\'查询持仓情况，按市值降序\')">📊 持仓查询</span>');
  if(hasNav)skills.push('<span class="wc-skill-btn" onclick="sendQuick(\'净值最近变动情况\')">📈 净值分析</span>');
  if(hasHolding&&hasNav)skills.push('<span class="wc-skill-btn" onclick="sendQuick(\'生成产品运作报告\')">📄 运作报告</span>');
  if(hasRating&&hasHolding)skills.push('<span class="wc-skill-btn" onclick="sendQuick(\'查看信用评级分布情况\')">🏷 评级分布</span>');
  const examples=[];
  if(hasHolding)examples.push('@'+hasHolding.name+' 按主体统计持仓市值前10');
  if(hasNav)examples.push('@'+hasNav.name+' 最近净值变动如何');
  if(hasRating)examples.push('检查信用评级分布，重点关注AA以下');
  if(!examples.length)examples.push('已加载的数据有哪些？各表结构是什么？');
  return '<div class="welcome" id="welcomePanel">'
    +'<div class="welcome-header">'
    +'<h2>就绪</h2>'
    +'<p>已加载 <strong>'+n+'</strong> 张数据表 &nbsp;'+typeSummary+'</p>'
    +'</div>'
    +(skills.length?'<div class="welcome-skills">'+skills.join('')+'</div>':'')
    +'<div class="welcome-divider"></div>'
    +'<div class="welcome-section-title">试试这样问</div>'
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
  onEnter() {
    scrollBottom();
    setTimeout(()=>$('input').focus(),100);
    loadTables();
    loadChatSkills();
  }
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
  if(typeof renderChatTableList==='function')renderChatTableList(tables);
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
