// main.js — App init, router setup, keyboard/drag-drop handlers, theme, health polling

// Page title map
const _pageTitles = {
  '/dashboard': '仪表盘',
  '/sources': '数据源',
  '/rules': '分析规则',
  '/chat': '智能对话',
  '/audit': '审计日志',
};

// Keyboard shortcuts
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){
    if(ST._es)stopStream();
    else if($('sbPanel').classList.contains('show'))closeSkillBuilder();
    else if($('settingsPanel').classList.contains('show'))closeSettings();
  }
});

function onKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();}}
function triggerUpload(){$('fileInput').click();}
function clearChat(){const c=getChat();if(c)c.innerHTML='';}

function buildWelcomePanel(tables){
  const _icon=(name)=>'<span class="material-symbols-outlined text-[16px]">'+name+'</span>';
  if(!tables||!tables.length){
    return '<div class="welcome flex flex-col items-center justify-center py-16 text-center" id="welcomePanel">'
      +'<div class="w-16 h-16 bg-primary-container rounded-2xl flex items-center justify-center mb-4">'
      +'<span class="material-symbols-outlined text-on-secondary-container text-[32px]" style="font-variation-settings:\'FILL\' 1">neurology</span></div>'
      +'<h2 class="text-headline-md font-semibold mb-2">DataAgent</h2>'
      +'<p class="text-body-md text-on-surface-variant mb-8 max-w-md">专业的金融资管数据分析助手</p>'
      +'<div class="grid grid-cols-2 gap-3 max-w-lg w-full">'
      +'<div class="stitch-card p-5 cursor-pointer hover:border-secondary transition text-left" onclick="triggerUpload()">'
        +'<div class="w-10 h-10 rounded-lg bg-secondary/10 flex items-center justify-center mb-3">'+_icon('bar_chart')+'</div>'
        +'<div class="text-body-md font-semibold mb-1">上传数据分析</div>'
        +'<div class="text-body-sm text-on-surface-variant">上传 CSV/Excel 持仓、净值、评级文件，自然语言查询分析</div>'
      +'</div>'
      +'<div class="stitch-card p-5 cursor-pointer hover:border-secondary transition text-left" onclick="sendQuick(\'帮我检查主体集中度是否有超标情况\')">'
        +'<div class="w-10 h-10 rounded-lg bg-success/10 flex items-center justify-center mb-3">'+_icon('check_circle')+'</div>'
        +'<div class="text-body-md font-semibold mb-1">合规监控</div>'
        +'<div class="text-body-sm text-on-surface-variant">主体/单券集中度自动检查，固化口径确保数字准确</div>'
      +'</div>'
      +'<div class="stitch-card p-5 cursor-pointer hover:border-secondary transition text-left" onclick="openSkillBuilder()">'
        +'<div class="w-10 h-10 rounded-lg bg-warning/10 flex items-center justify-center mb-3">'+_icon('bolt')+'</div>'
        +'<div class="text-body-md font-semibold mb-1">创建分析</div>'
        +'<div class="text-body-sm text-on-surface-variant">用自然语言描述分析需求，AI 帮你生成可复用的分析技能</div>'
      +'</div>'
      +'<div class="stitch-card p-5 cursor-pointer hover:border-secondary transition text-left" onclick="($(\'input\')||$(\'userInput\')).focus()">'
        +'<div class="w-10 h-10 rounded-lg bg-secondary/10 flex items-center justify-center mb-3">'+_icon('chat_bubble')+'</div>'
        +'<div class="text-body-md font-semibold mb-1">通用问答</div>'
        +'<div class="text-body-sm text-on-surface-variant">无需数据也能使用：回答金融知识、分析文档、行业咨询</div>'
      +'</div>'
      +'</div>'
      +'<div id="welcomeExamples" class="mt-6 flex flex-wrap gap-2 justify-center"></div>'
      +'</div>';
  }
  const n=tables.length;
  const hasHolding=tables.find(t=>t.type==='holding');
  const hasNav=tables.find(t=>t.type==='nav');
  const skills=[];
  if(hasHolding)skills.push('<button class="suggestion-pill" onclick="sendQuick(\'帮我检查主体集中度\')">'+_icon('check_circle')+' 合规检查</button>');
  if(hasHolding)skills.push('<button class="suggestion-pill" onclick="sendQuick(\'查询持仓情况，按市值降序\')">'+_icon('bar_chart')+' 持仓查询</button>');
  if(hasNav)skills.push('<button class="suggestion-pill" onclick="sendQuick(\'净值最近变动情况\')">'+_icon('trending_up')+' 净值分析</button>');
  const examples=[];
  if(hasHolding)examples.push('@'+hasHolding.name+' 按主体统计持仓市值前10');
  if(hasNav)examples.push('@'+hasNav.name+' 最近净值变动如何');
  if(!examples.length)examples.push('已加载的数据有哪些？各表结构是什么？');
  return '<div class="welcome flex flex-col items-center justify-center py-12 text-center" id="welcomePanel">'
    +'<div class="w-16 h-16 bg-primary-container rounded-2xl flex items-center justify-center mb-4">'
    +'<span class="material-symbols-outlined text-on-secondary-container text-[32px]" style="font-variation-settings:\'FILL\' 1">neurology</span></div>'
    +'<h2 class="text-headline-md font-semibold mb-2">DataAgent</h2>'
    +'<p class="text-body-md text-on-surface-variant mb-4">已加载 '+n+' 张表，可以开始分析</p>'
    +(skills.length?'<div class="flex flex-wrap gap-2 justify-center mb-4">'+skills.join('')+'</div>':'')
    +'<div class="text-body-sm text-on-surface-variant mb-2">试试问我：</div>'
    +'<div id="welcomeExamples" class="flex flex-wrap gap-2 justify-center">'
    +examples.slice(0,3).map(ex=>'<button class="suggestion-pill" onclick="sendQuick(\''+esc(ex)+'\')">'+_icon('chat_bubble')+' '+esc(ex)+'</button>').join('')
    +'</div></div>';
}

async function resetChat(){
  if(ST._es){ST._es.close();ST._es=null;}
  ST.locked=false;lockInput(false);endStream();finPW();
  clearChat();
  const tables=window._lastLoadedTables||[];
  const c=getChat();
  if(c)c.innerHTML=buildWelcomePanel(tables);
  try{await api('POST','/api/reset');}catch(e){}
  const titleEl=$('chatTitle');
  if(titleEl)titleEl.textContent='新对话';
  ST.sessionId='';
  if(typeof refreshSidebar==='function')refreshSidebar();
  const inp=$('input')||$('userInput');
  if(inp)setTimeout(()=>inp.focus(),100);
}

function toggleTheme(){
  const h=document.documentElement;
  h.dataset.theme=h.dataset.theme==='dark'?'light':'dark';
}

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
    if(dotEl){
      dotEl.className = ready
        ? 'w-2 h-2 rounded-full bg-success'
        : 'w-2 h-2 rounded-full bg-error';
    }
  }
}
async function pollHealth(){
  try{const d=await api('GET','/api/health');_applyHealth(d);}catch(e){}
}

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

// ── Router setup ──
Router.register('/dashboard', root => DashboardPage.render(root));
Router.register('/sources', root => SourcesPage.render(root));
Router.register('/rules', root => RulesPage.render(root));
Router.register('/chat', root => {
  ChatPage.render(root);
  // Re-bind lazy chat reference after ChatPage creates #chat
  chat = $('chat');
  // Setup scroll detection for the legacy scroll button
  const scrollBtn = $('scrollBtn');
  if (chat && scrollBtn) {
    chat.addEventListener('scroll', () => {
      const near = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
      scrollBtn.classList.toggle('show', !near);
    });
  }
  // Show welcome panel if no messages yet
  if (!ChatPage._initialized_welcome) {
    ChatPage._initialized_welcome = true;
    const tables = window._lastLoadedTables || [];
    if (chat) chat.innerHTML = buildWelcomePanel(tables);
  }
  // Setup drag & drop on the chat input area
  const inputArea = $('chat-input-area') || $('inputbar');
  if (inputArea) {
    inputArea.addEventListener('dragover', e => { e.preventDefault(); inputArea.classList.add('dragover'); });
    inputArea.addEventListener('dragleave', () => inputArea.classList.remove('dragover'));
    inputArea.addEventListener('drop', e => {
      e.preventDefault(); inputArea.classList.remove('dragover');
      handleFiles(e.dataTransfer.files);
    });
  }
});
Router.register('/audit', root => AuditPage.render(root));

Router.onNavigate(route => {
  const titleEl = $('pageTitle');
  if (titleEl) titleEl.textContent = _pageTitles[route] || '';
});

// ── Init ──
AgentStatus.init();
Router.init('pageRoot', '#/chat');
pollHealth();
setInterval(()=>pollHealth(),15000);
