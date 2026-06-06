// dom.js — DOM helpers, API wrapper, clipboard, toast

const $=id=>document.getElementById(id);
const chat=$('chat');

function scrollBottom(){chat.scrollTop=chat.scrollHeight;}
function add(node){chat.appendChild(node);scrollBottom();return node;}
function el(h){const d=document.createElement('div');d.innerHTML=h.trim();return d.firstElementChild||d;}
function esc(s){
  if(s==null)return'';
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Scroll-to-bottom button
const scrollBtn=$('scrollBtn');
chat.addEventListener('scroll',()=>{
  const near=chat.scrollHeight-chat.scrollTop-chat.clientHeight<80;
  scrollBtn.classList.toggle('show',!near);
});

// API helper
async function api(method,path,body){
  const opts={method,headers:{}};
  if(body){opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(body);}
  const r=await fetch(path,opts);return r.json();
}

// Clipboard
function copyText(text,btn,label){
  const restore=()=>setTimeout(()=>{if(btn&&btn._orig)btn.textContent=btn._orig;},1500);
  if(btn){btn._orig=btn._orig||btn.textContent;btn.textContent=label||'✓ 已复制';}
  if(navigator.clipboard){
    navigator.clipboard.writeText(text).then(restore).catch(()=>{legacyCopy(text);restore();});
  }else{legacyCopy(text);restore();}
}
function legacyCopy(text){
  const ta=document.createElement('textarea');
  ta.value=text;ta.style.cssText='position:fixed;opacity:0';
  document.body.appendChild(ta);ta.focus();ta.select();
  try{document.execCommand('copy');}catch(e){}
  document.body.removeChild(ta);
}
function copyCodeBlock(btn){
  const code=btn.parentElement?.querySelector('code');
  if(code)copyText(code.textContent,btn);
}
function copyBubble(btn){
  const bubble=btn.closest('.bubble-outer')?.querySelector('.bubble');
  if(bubble)copyText(bubble.textContent.trim(),btn);
}

// Toast
function toast(msg,type,duration){
  const stack=$('toastStack');
  const t=document.createElement('div');
  t.className='toast'+(type&&type!=='info'?' '+type:'');
  t.textContent=msg;
  stack.appendChild(t);
  setTimeout(()=>{
    t.style.animation='toastOut .2s ease forwards';
    setTimeout(()=>t.remove(),200);
  },duration||2800);
}

// Send mode / busy / lock
function setSendMode(mode){
  const btn=$('sendBtn');
  if(mode==='stream'){
    btn.textContent='停止';btn.classList.add('stop');btn.onclick=stopStream;
  }else{
    btn.textContent='发送';btn.classList.remove('stop');btn.onclick=sendMessage;
  }
}
function setBusy(busy){$('input').readOnly=busy;}
function lockInput(lock){
  $('inrow').classList.toggle('disabled',lock);
  $('hint').classList.toggle('show',lock);
}
function autoResize(ta){ta.style.height='auto';ta.style.height=Math.min(ta.scrollHeight,120)+'px';}
