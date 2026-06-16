// chat.js — SSE send/receive, process wrapper, stream management

// Process wrapper (tool execution progress)
function getPW(){
  if(_pw)return _pw;
  const w=document.createElement('div');
  w.className='pw-wrap open';
  w.innerHTML='<div class="pw-hd" onclick="this.parentElement.classList.toggle(\'open\')">'
    +'<span class="pw-icon spin"><span class="material-symbols-outlined text-[14px]">sync</span></span>'
    +'<span class="pw-lbl">正在处理…</span>'
    +'<span class="pw-arr"><span class="material-symbols-outlined text-[12px]">expand_more</span></span></div>'
    +'<div class="pw-bd"></div>';
  _pwBd=w.querySelector('.pw-bd');
  _pwN=0;add(w);_pw=w;return w;
}
function finPW(){
  if(!_pw)return;
  const lbl=_pw.querySelector('.pw-lbl'),icon=_pw.querySelector('.pw-icon');
  if(lbl)lbl.textContent='执行过程（'+_pwN+'步）';
  if(icon){icon.innerHTML='<span class="material-symbols-outlined text-[14px]">check_circle</span>';icon.classList.remove('spin');}
  _pw.classList.remove('open');
  _pw=null;_pwBd=null;
}
function updatePWLabel(){
  if(!_pw)return;
  const lbl=_pw.querySelector('.pw-lbl');
  if(lbl)lbl.textContent='正在执行… 第'+_pwN+'步';
}

function stopStream(){
  if(ST._es){ST._es.close();ST._es=null;}
  finPW();endStream();
  addSysMsg('已停止','orange');
  if(typeof AgentStatus!=='undefined')AgentStatus.onStop();
}

function _getInput(){return $('input')||$('userInput');}

// Send message
async function sendMessage(){
  const inp=_getInput();
  if(!inp)return;
  const msg=inp.value.trim();
  if(!msg||ST.locked||inp.readOnly)return;
  inp.value='';autoResize(inp);
  const c=getChat();
  const w=c?c.querySelector('.welcome')||c.querySelector('#welcomePanel'):null;
  if(w)w.remove();
  addUserBubble(msg);
  const ct=$('chatTitle');if(ct)ct.textContent=msg.slice(0,40);
  setSendMode('stream');setBusy(true);
  if(typeof AgentStatus!=='undefined')AgentStatus.onNewMessage();
  try{
    const body={message:msg};
    if(_documentContext){body.document_context=_documentContext;}
    const r=await fetch('/api/chat',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),
    });
    const d=await r.json();
    if(!d.ok){setSendMode('idle');setBusy(false);addSysMsg(d.error||'请求失败','red');return;}
    ST.streamId=d.stream_id;
    const es=new EventSource('/api/stream/'+ST.streamId);
    ST._es=es;
    es.onmessage=function(e){try{handleChunk(JSON.parse(e.data));}catch(ex){console.error(ex);}};
    es.onerror=function(){
      if(!ST._es)return;
      es.close();ST._es=null;finPW();endStream();
    };
  }catch(e){setSendMode('idle');setBusy(false);addSysMsg('请求失败：'+esc(e.message),'red');}
}

// SSE chunk handler
function handleChunk(chunk){
  const t=chunk.type,d=chunk.data;
  if(t==='text'){
    finPW();
    if(!d)return;
    if(!streamEl){
      streamBuf='';streamConf=chunk.confidence||null;
      const row=document.createElement('div');
      row.className='flex gap-3 max-w-full';
      row.innerHTML='<div class="w-8 h-8 rounded bg-primary-container flex items-center justify-center flex-shrink-0 mt-1">'
        +'<span class="material-symbols-outlined text-[16px] text-on-secondary-container" style="font-variation-settings:\'FILL\' 1">neurology</span></div>'
        +'<div class="flex-1 min-w-0 max-w-[min(78%,720px)]">'
        +'<div class="flex items-center gap-2 mb-1">'
        +'<span class="label-caps text-on-surface-variant">DataAgent AI</span>'
        +'<span class="status-badge processing">生成中</span></div>'
        +'<div class="bubble-ai text-body-md leading-relaxed streaming"></div>'
        +'<div class="flex gap-2 mt-1.5">'
        +'<button class="text-body-sm text-outline hover:text-secondary transition-colors cursor-pointer bg-transparent border-none p-0 flex items-center gap-1" onclick="copyBubble(this)">'
        +'<span class="material-symbols-outlined text-[14px]">content_copy</span> 复制</button>'
        +'<button class="text-body-sm text-outline hover:text-secondary transition-colors cursor-pointer bg-transparent border-none p-0 flex items-center gap-1" onclick="exportWordFromBubble(this)">'
        +'<span class="material-symbols-outlined text-[14px]">download</span> 导出</button>'
        +'</div></div>';
      streamEl=row.querySelector('.bubble-ai');add(row);
    }
    if(chunk.confidence)streamConf=chunk.confidence;
    streamBuf+=d;streamEl.innerHTML=renderMd(streamBuf);scrollBottom();
  }
  else if(t==='thinking'){
    getPW();
    if(_pwBd){
      const line=document.createElement('div');
      line.className='proc-line';
      line.innerHTML='<span class="p-icon"><span class="material-symbols-outlined text-[14px]">psychology</span></span>'
        +'<span class="p-label">'+esc((d||'').slice(0,100))+'</span>';
      _pwBd.appendChild(line);_pwN++;updatePWLabel();
    }
    if(typeof AgentStatus!=='undefined')AgentStatus.onThinking(d||'');
    scrollBottom();
  }
  else if(t==='tool_start'){
    getPW();
    if(_pwBd){
      const line=document.createElement('div');
      line.className='proc-line';line.id='tool-'+d.id;
      line.innerHTML='<span class="p-icon"><span class="material-symbols-outlined text-[14px]">bolt</span></span>'
        +'<span class="p-name">'+esc(d.tool||'')+'</span>'
        +'<span class="p-label">'+esc(d.label||'')+'</span>'
        +'<span class="p-st running">…</span>';
      _pwBd.appendChild(line);_pwN++;updatePWLabel();
    }
    if(typeof AgentStatus!=='undefined')AgentStatus.onToolStart(d.tool,d.label);
    scrollBottom();
  }
  else if(t==='tool_end'){
    const line=$('tool-'+d.id);
    if(line){
      const st=line.querySelector('.p-st'),icon=line.querySelector('.p-icon');
      if(d.success){
        if(st){st.className='p-st ok';st.innerHTML='<span class="material-symbols-outlined text-[12px]">check_circle</span>';}
        if(icon)icon.innerHTML='<span class="material-symbols-outlined text-[14px]">check_circle</span>';
      }else{
        if(st){st.className='p-st warn';st.innerHTML='<span class="material-symbols-outlined text-[12px]">error</span>';}
        if(icon)icon.innerHTML='<span class="material-symbols-outlined text-[14px]">error</span>';
      }
    }
    if(typeof AgentStatus!=='undefined')AgentStatus.onToolEnd(d.success);
  }
  else if(t==='plan'){
    finPW();breakStream();
    const card=renderPlanCard(d);add(card);
    if(typeof AgentStatus!=='undefined')AgentStatus.onPlan(d);
  }
  else if(t==='plan_step'){
    updatePlanStep(d.step_id,d.status);
    if(typeof AgentStatus!=='undefined')AgentStatus.onPlanStep(d.step_id,d.status,d.name);
  }
  else if(t==='plan_done'){}
  else if(t==='table'){breakStream();add(renderTable(d));}
  else if(t==='report'){breakStream();add(renderReport(d));}
  else if(t==='confirm'){
    finPW();breakStream();ST.locked=true;lockInput(true);
    const card=renderConfirm(d);add(card);
    if(typeof AgentStatus!=='undefined')AgentStatus.onConfirm();
    requestAnimationFrame(()=>{
      (card.querySelector('.btn-primary')||card.querySelector('.btn.primary'))?.focus();
      card.scrollIntoView({behavior:'smooth',block:'center'});
    });
  }
  else if(t==='ask'){
    finPW();breakStream();ST.locked=true;lockInput(true);
    const card=renderAsk(d);add(card);
    if(typeof AgentStatus!=='undefined')AgentStatus.onAsk(d.question);
    requestAnimationFrame(()=>{
      (card.querySelector('.suggestion-pill')||card.querySelector('.btn.opt'))?.focus();
      card.scrollIntoView({behavior:'smooth',block:'center'});
    });
  }
  else if(t==='error'){
    finPW();breakStream();addSysMsg(esc(d.message||d),'red');
    if(typeof AgentStatus!=='undefined')AgentStatus.onError(d.message||String(d));
  }
  else if(t==='chart'){ST.pendingCharts.push(d);}
  else if(t==='stream_end'){
    if(ST._es){ST._es.close();ST._es=null;}
    finPW();endStream();refreshSidebar();
    ST.pendingCharts.forEach(opt=>renderChart(opt));ST.pendingCharts=[];
    if(typeof AgentStatus!=='undefined')AgentStatus.onStreamEnd();
  }
}
function breakStream(){
  if(streamEl){
    streamEl.classList.remove('streaming');
    const badge=streamEl.closest('.flex-1')?.querySelector('.status-badge');
    if(badge){badge.className='status-badge ready';badge.textContent='就绪';}
    if(streamConf){
      const tag=document.createElement('span');
      tag.className='conf-tag conf-'+streamConf;
      const CONF_LABELS={auditable:'✓ 已审计',verify:'~ 需核实',ai_generated:'✧ AI生成'};
      tag.textContent=CONF_LABELS[streamConf]||streamConf;
      streamEl.appendChild(tag);
    }
  }
  streamEl=null;streamConf=null;
}
function endStream(){
  breakStream();streamBuf='';ST.streamId=null;
  setSendMode('idle');setBusy(false);
  setTimeout(()=>{if(!ST.locked){const inp=_getInput();if(inp)inp.focus();}},80);
}

// Confirm / Ask actions
async function doConfirm(confirmed){
  ST.locked=false;lockInput(false);
  if(typeof AgentStatus!=='undefined')AgentStatus.onResume();
  await api('POST','/api/confirm',{confirmed});
  if(!confirmed){addSysMsg('已取消本次操作','orange');return;}
  // 静默续跑：不在聊天中显示"确认继续"气泡
  setSendMode('stream');setBusy(true);
  if(typeof AgentStatus!=='undefined')AgentStatus.onNewMessage();
  try{
    const r=await fetch('/api/chat',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:'confirmed'}),
    });
    const d=await r.json();
    if(!d.ok){setSendMode('idle');setBusy(false);addSysMsg(d.error||'续跑失败','red');return;}
    ST.streamId=d.stream_id;
    const es=new EventSource('/api/stream/'+ST.streamId);
    ST._es=es;
    es.onmessage=function(e){try{handleChunk(JSON.parse(e.data));}catch(ex){console.error(ex);}};
    es.onerror=function(){if(!ST._es)return;es.close();ST._es=null;finPW();endStream();};
  }catch(e){setSendMode('idle');setBusy(false);addSysMsg('续跑失败：'+esc(e.message),'red');}
}
function doAsk(choice){
  ST.locked=false;lockInput(false);
  if(typeof AgentStatus!=='undefined')AgentStatus.onResume();
  const inp=_getInput();if(inp)inp.value=choice;sendMessage();
}
function sendQuick(cmd){const inp=_getInput();if(inp)inp.value=cmd;sendMessage();}

async function executeSkill(skillName){
  if(ST.locked)return;
  const c=getChat();const w=c?c.querySelector('.welcome')||c.querySelector('#welcomePanel'):null;if(w)w.remove();
  addUserBubble('执行 Skill：'+skillName);
  setSendMode('stream');setBusy(true);
  if(typeof AgentStatus!=='undefined')AgentStatus.onNewMessage();
  try{
    const r=await fetch('/api/skills/'+encodeURIComponent(skillName)+'/execute',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({}),
    });
    const d=await r.json();
    if(!d.ok){setSendMode('idle');setBusy(false);addSysMsg(d.error||'执行失败','red');return;}
    ST.streamId=d.stream_id;
    const es=new EventSource('/api/stream/'+ST.streamId);
    ST._es=es;
    es.onmessage=function(e){try{handleChunk(JSON.parse(e.data));}catch(ex){console.error(ex);}};
    es.onerror=function(){
      if(!ST._es)return;
      es.close();ST._es=null;finPW();endStream();
    };
  }catch(e){setSendMode('idle');setBusy(false);addSysMsg('执行请求失败：'+esc(e.message),'red');}
}
