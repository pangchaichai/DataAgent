// main.js — App init, keyboard/drag-drop handlers, theme, health polling

// Keyboard shortcuts
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){
    if(ST._es)stopStream();
    else if($('sbPanel').classList.contains('show'))closeSkillBuilder();
    else if($('settingsPanel').classList.contains('show'))closeSettings();
  }
});

function onKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();}}
function triggerUpload(){openSec('tables');$('fileInput').click();}
function clearChat(){chat.innerHTML='';}

async function resetChat(){
  if(ST._es){ST._es.close();ST._es=null;}
  ST.locked=false;lockInput(false);endStream();finPW();
  clearChat();
  chat.innerHTML='<div class="welcome"><h2>DataAgent</h2>'
    +'<p>上传资管数据文件，用中文提问即可分析</p>'
    +'<p class="sub">合规/报告数字使用固化口径计算，需要您确认后输出</p>'
    +'<div class="wq">'
    +'<button class="wq-btn" onclick="triggerUpload()">📂 上传数据</button>'
    +'<button class="wq-btn" onclick="sendQuick(\'/tables\')">/tables</button>'
    +'<button class="wq-btn" onclick="sendQuick(\'/skills\')">/skills</button>'
    +'<button class="wq-btn" onclick="sendQuick(\'/health\')">/health</button>'
    +'</div></div>';
  try{await api('POST','/api/reset');}catch(e){}
  $('chatTitle').textContent='新对话';
  ST.sessionId='';refreshSidebar();
  setTimeout(()=>$('input').focus(),100);
}

function toggleTheme(){
  const h=document.documentElement;
  h.dataset.theme=h.dataset.theme==='dark'?'light':'dark';
}

// Drag & drop onto input bar
const ibar=$('inputbar');
ibar.addEventListener('dragover',e=>{e.preventDefault();ibar.classList.add('dragover');});
ibar.addEventListener('dragleave',()=>ibar.classList.remove('dragover'));
ibar.addEventListener('drop',e=>{
  e.preventDefault();ibar.classList.remove('dragover');
  handleFiles(e.dataTransfer.files);
});
$('uploadLink').addEventListener('click',()=>{openSec('tables');$('fileInput').click();});

// Health polling
async function pollHealth(){
  try{
    const d=await api('GET','/api/health');
    $('ramMb').textContent=d.ram_mb||'--';
    $('tokenUsed').textContent=d.token_used||0;
    $('tokenLimit').textContent=Math.round((d.token_limit||64000)/1000)+'K';
    $('llmName').textContent=d.llm_name||'--';
    if(d.llm_name&&d.llm_name!=='--')$('llmDot').className='dot on';
  }catch(e){}
}

// Init
AgentStatus.init();
refreshSidebar();
setTimeout(()=>$('input').focus(),200);
pollHealth();
setInterval(async()=>{
  try{
    const d=await api('GET','/api/health');
    $('ramMb').textContent=d.ram_mb||'--';
    $('tokenUsed').textContent=d.token_used||0;
    $('tokenLimit').textContent=Math.round((d.token_limit||64000)/1000)+'K';
    $('llmName').textContent=d.llm_name||'--';
  }catch(e){}
},15000);

function updateWelcomeExamples(tables){
  const el=$('welcomeExamples');if(!el)return;
  if(!tables.length){el.innerHTML='';return;}
  const examples=[];
  const hasHolding=tables.find(t=>t.type==='holding');
  const hasNav=tables.find(t=>t.type==='nav');
  if(hasHolding)examples.push(
    {text:'@'+hasHolding.name+' 按主体统计持仓市值排名前10',icon:'📊'},
    {text:'@'+hasHolding.name+' 检查主体集中度是否超标',icon:'✅'}
  );
  if(hasNav)examples.push(
    {text:'@'+hasNav.name+' 最近一周净值变动如何',icon:'📈'}
  );
  if(tables.length>1)examples.push(
    {text:'已加载的数据有哪些表？各表结构是什么？',icon:'🔍'}
  );
  if(!examples.length)examples.push({text:'帮我分析已加载的数据',icon:'💡'});
  el.innerHTML='<div style="margin-top:12px;font-size:12px;color:var(--text-3)">试试这些：</div>'
    +examples.slice(0,3).map(ex=>
      '<div class="wex-item" onclick="sendQuick(\''+esc(ex.text)+'\')">'
      +ex.icon+' '+esc(ex.text)+'</div>'
    ).join('');
}
