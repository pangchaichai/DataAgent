// skill_builder.js — Skill self-service creation, draft management, publish flow

let _sbStep=0;

function openSkillBuilder(){
  _sbStep=0;
  $('sbDescInput').value='';
  $('sbEditor').value='';
  sbGoStep(0);
  sbLoadDrafts();
  $('sbOverlay').classList.add('show');
  $('sbPanel').classList.add('show');
}
function closeSkillBuilder(){
  $('sbOverlay').classList.remove('show');
  $('sbPanel').classList.remove('show');
}
function sbGoStep(n){
  _sbStep=n;
  for(let i=0;i<4;i++){
    const step=$('sbStep'+i),dot=$('sbDot'+i);
    if(!step)continue;
    step.classList.toggle('active',i===n);
    dot.classList.toggle('active',i===n);
    dot.classList.toggle('done',i<n);
  }
}
function sbReset(){
  $('sbDescInput').value='';
  $('sbEditor').value='';
  $('sbValResult').innerHTML='';
  sbGoStep(0);
  sbLoadDrafts();
}

async function sbLoadDrafts(){
  const container=$('sbDraftList');
  try{
    const d=await api('GET','/api/skill-builder/drafts');
    const drafts=d.drafts||[];
    if(!drafts.length){container.innerHTML='';return;}
    container.innerHTML='<div class="sb-label">已有草稿</div>'
      +drafts.map(dr=>'<div class="sb-draft-item" onclick="sbLoadDraft(\''+esc(dr.name)+'\')">'
        +'<span class="sb-draft-name">'+esc(dr.name)+'</span>'
        +'<span class="sb-draft-desc">'+esc((dr.description||'').slice(0,40))+'</span>'
        +'<span class="sb-draft-del" onclick="event.stopPropagation();sbDeleteDraft(\''+esc(dr.name)+'\')">删除</span>'
        +'</div>').join('');
  }catch(e){container.innerHTML='';}
}

async function sbLoadDraft(name){
  try{
    const d=await api('GET','/api/skill-builder/draft/'+encodeURIComponent(name));
    if(d.content){
      $('sbEditor').value=d.content;
      sbGoStep(1);
    }else{toast('草稿内容为空','error');}
  }catch(e){toast('加载草稿失败','error');}
}

async function sbDeleteDraft(name){
  if(!confirm('确定删除草稿 "'+name+'" 吗？'))return;
  try{
    await api('DELETE','/api/skill-builder/draft/'+encodeURIComponent(name));
    toast('草稿已删除','success');
    sbLoadDrafts();
  }catch(e){toast('删除失败','error');}
}

async function sbGenerate(){
  const desc=$('sbDescInput').value.trim();
  if(!desc){toast('请先描述 Skill 功能','error');return;}
  $('sbStep0').innerHTML='<div class="sb-loading">AI 正在生成 Skill 配置…</div>';
  try{
    const d=await api('POST','/api/skill-builder/generate',{description:desc});
    sbRestoreStep0();
    if(d.content){
      $('sbEditor').value=d.content;
      sbGoStep(1);
      toast('Skill 配置已生成','success');
    }else{
      toast('生成失败：'+(d.error||'未知错误'),'error');
    }
  }catch(e){
    sbRestoreStep0();
    toast('生成请求失败','error');
  }
}

function sbRestoreStep0(){
  $('sbStep0').innerHTML=
    '<div id="sbDraftList" style="margin-bottom:16px"></div>'
    +'<label class="sb-label">描述你想创建的 Skill 功能</label>'
    +'<textarea class="sb-textarea" id="sbDescInput"'
    +' placeholder="例如：我想查询每只债券的到期日和剩余期限，以表格形式展示持仓中即将到期的债券，按到期日排序"></textarea>'
    +'<div class="sp-hint" style="margin-top:6px">用自然语言描述即可，AI 会帮你生成 Skill 配置</div>'
    +'<div class="sb-actions">'
    +'<button class="btn primary" onclick="sbGenerate()">AI 生成</button>'
    +'<button class="btn ghost" onclick="sbGoStep(1)">手动编写</button>'
    +'</div>';
  sbLoadDrafts();
}

async function sbValidate(){
  const content=$('sbEditor').value.trim();
  if(!content){toast('内容不能为空','error');return;}
  try{
    const d=await api('POST','/api/skill-builder/validate',{content:content});
    const v=d;  // backend returns flat {ok, issues, error_count, warning_count}
    const issues=v.issues||[];
    let html='';
    if(v.ok){
      html='<div class="sb-issue" style="background:var(--green-bg,#e6f9ee);color:var(--green)">'
        +'<span class="sb-i-icon">✓</span><span class="sb-i-msg">校验通过，可以发布</span></div>';
      $('sbPublishBtn').disabled=false;
    }else{
      $('sbPublishBtn').disabled=true;
    }
    html+=issues.map(is=>'<div class="sb-issue '+esc(is.level)+'">'
      +'<span class="sb-i-icon">'+(is.level==='error'?'✕':'⚠')+'</span>'
      +'<span class="sb-i-msg">'+(is.field?'<b>'+esc(is.field)+'</b>：':'')+esc(is.message)+'</span>'
      +'</div>').join('');
    $('sbValResult').innerHTML=html;
    sbGoStep(2);
  }catch(e){toast('校验请求失败','error');}
}

async function sbSaveDraft(){
  const content=$('sbEditor').value.trim();
  if(!content){toast('内容不能为空','error');return;}
  const nameMatch=content.match(/name:\s*(\S+)/);
  const name=nameMatch?nameMatch[1]:'draft_'+Date.now();
  try{
    const d=await api('POST','/api/skill-builder/save-draft',{name:name,content:content});
    if(d.ok){toast('草稿已保存','success');}
    else{toast('保存失败：'+(d.error||''),'error');}
  }catch(e){toast('保存失败','error');}
}

async function sbPublish(){
  const content=$('sbEditor').value.trim();
  if(!content)return;
  try{
    const d=await api('POST','/api/skill-builder/publish',{content:content});
    if(d.ok){
      $('sbSuccessName').textContent='Skill "'+esc(d.name)+'" 已发布';
      sbGoStep(3);
      toast('Skill 发布成功','success');
    }else{
      const v=d.validation||{};
      const msgs=(v.issues||[]).map(i=>i.message).join('；');
      toast('发布失败：'+(msgs||d.error||'校验未通过'),'error');
    }
  }catch(e){toast('发布请求失败','error');}
}
