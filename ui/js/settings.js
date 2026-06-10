// settings.js — Settings panel, LLM config, memory, log settings

let _products=[];

async function openSettings(){
  await loadSettings();
  $('settingsOverlay').classList.add('show');
  $('settingsPanel').classList.add('show');
}
function closeSettings(){
  $('settingsOverlay').classList.remove('show');
  $('settingsPanel').classList.remove('show');
}
async function loadSettings(){
  try{
    const d=await api('GET','/api/config');
    const up=d.user_profile||{};
    $('cfg-name').value=up.name||'';
    $('cfg-dept').value=up.department||'';
    $('cfg-role').value=up.role||'';
    _products=(Array.isArray(up.managed_products)?up.managed_products:[]).filter(p=>p&&p.trim());
    renderProductTags();
    const cc=(d.calculation_config||{}).concentration||{};
    $('cfg-thresh-entity').value=cc.threshold_entity??10;
    $('cfg-thresh-bond').value=cc.threshold_single_bond??10;
    $('cfg-mkt-field').value=cc.market_value_field||'穿透后市值';
    $('cfg-group-merge').checked=cc.use_group_merge!==false;
    $('cfg-memory').checked=!!(d.memory||{}).enabled;
    $('cfg-scheduler').checked=!!(d.scheduler||{}).enabled;
    $('cfg-work-dir').value=d.work_dir||'';
    const keySet=d.api_key_set;
    $('apikeyStatus').textContent=keySet?'✓ API Key 已配置':'未配置';
    $('apikeyStatus').style.color=keySet?'var(--green)':'var(--text-3)';
  }catch(e){toast('加载配置失败','error');}
  try{
    const ms=await api('GET','/api/memory/stats');
    if(ms.enabled){
      $('memStats').textContent='已存 '+ms.count+' 条，'+ms.size_mb+'MB'+(ms.warning?' ⚠️ 超过阈值':'');
    }else{$('memStats').textContent='记忆功能未启用';}
  }catch(e){}
  try{
    const td=await api('GET','/api/tasks');
    const tasks=td.tasks||[];
    $('spTaskList').innerHTML=tasks.length
      ?tasks.map(t=>'<div style="font-size:12px;padding:3px 0;color:var(--text-2)">• '
        +esc(t.name||JSON.stringify(t))+(t.schedule?' ('+esc(t.schedule)+')':'')+'</div>').join('')
      :'<div style="font-size:12px;color:var(--text-3)">暂无定时任务</div>';
  }catch(e){}
  loadLLMProviders();
  loadLogSettings();
}

async function loadLLMProviders(){
  try{
    const d=await api('GET','/api/llm/providers');
    const sel=$('cfg-llm-provider');
    const providerNames={'lmstudio':'本地 LM Studio','deepseek':'DeepSeek（远程）','enterprise_internal':'企业内网 LLM'};
    sel.innerHTML='';
    (d.providers||[]).forEach(p=>{
      const opt=document.createElement('option');
      opt.value=p.name;
      opt.textContent=(providerNames[p.name]||p.name)+(p.is_local?' 🖥':'');
      if(p.name===d.current)opt.selected=true;
      sel.appendChild(opt);
    });
    if(!d.providers||d.providers.length===0){
      sel.innerHTML='<option value="">（未配置 provider）</option>';
    }
    updateLLMProviderHint(d.current,d.providers||[]);
  }catch(e){}
}
function onLLMProviderChange(){
  const sel=$('cfg-llm-provider');
  const provider=sel.value;
  $('llm-status-dot').textContent='⚪';
  const hints={'lmstudio':'本地推理，数据不出本机；请先在 LM Studio 中启动 Local Server','deepseek':'远程 API，问题文本将外发（须合规确认）','enterprise_internal':'企业内网 LLM（生产环境推荐）'};
  $('llm-provider-hint').textContent=hints[provider]||'';
}
function updateLLMProviderHint(current,providers){
  const p=providers.find(x=>x.name===current);
  if(!p)return;
  const hints={'lmstudio':'本地推理，数据不出本机；请先在 LM Studio 中启动 Local Server','deepseek':'远程 API，问题文本将外发（须合规确认）','enterprise_internal':'企业内网 LLM（生产环境推荐）'};
  $('llm-provider-hint').textContent=hints[current]||'';
}
async function testLLMConnection(){
  const provider=$('cfg-llm-provider').value;
  const dot=$('llm-status-dot');
  dot.textContent='🔄';
  try{
    const d=await api('POST','/api/llm/test',{provider});
    if(d.ok){
      dot.textContent='🟢';
      const modelTip=d.configured_model?(' | 模型: '+d.configured_model):'';
      $('llm-provider-hint').textContent='✓ 连接成功'+modelTip+(d.models&&d.models.length?' | 可用模型: '+d.models.slice(0,3).join(', '):'');
    }else{
      dot.textContent='🔴';
      $('llm-provider-hint').textContent='✗ 连接失败: '+(d.error||'未知错误');
    }
  }catch(e){
    dot.textContent='🔴';
    $('llm-provider-hint').textContent='✗ 请求失败';
  }
}

function renderProductTags(){
  $('productTags').innerHTML=_products.map((p,i)=>
    '<span class="ptag">'+esc(p)
    +'<span class="ptag-del" onclick="removeProduct('+i+')">×</span></span>'
  ).join('');
}
function addProduct(){
  const inp=$('newProduct'),v=inp.value.trim();
  if(!v)return;
  if(!_products.includes(v))_products.push(v);
  inp.value='';renderProductTags();
}
function removeProduct(i){_products.splice(i,1);renderProductTags();}

async function saveSettings(){
  const body={
    user_profile:{
      name:$('cfg-name').value.trim(),
      department:$('cfg-dept').value.trim(),
      role:$('cfg-role').value,
      managed_products:_products,
    },
    calculation_config:{concentration:{
      threshold_entity:parseFloat($('cfg-thresh-entity').value)||10,
      threshold_single_bond:parseFloat($('cfg-thresh-bond').value)||10,
      market_value_field:$('cfg-mkt-field').value.trim()||'穿透后市值',
      use_group_merge:$('cfg-group-merge').checked,
    }},
    memory:{enabled:$('cfg-memory').checked},
    scheduler:{enabled:$('cfg-scheduler').checked},
    work_dir:$('cfg-work-dir').value.trim(),
  };
  const apikey=$('cfg-apikey').value.trim();
  if(apikey)body.api_key=apikey;
  const provider=$('cfg-llm-provider');
  if(provider&&provider.value)body.llm_provider=provider.value;
  const llmUrl=$('cfg-llm-url').value.trim();
  if(llmUrl)body.llm_url=llmUrl;
  const llmModel=$('cfg-llm-model').value.trim();
  if(llmModel)body.llm_model=llmModel;
  try{
    const r=await api('POST','/api/config',body);
    if(r.ok){
      toast('配置已保存','success');
      if(apikey)$('cfg-apikey').value='';
      closeSettings();
    }else toast('保存失败：'+(r.error||''),'error');
  }catch(e){toast('保存失败','error');}
}

async function saveMemoryToggle(){
  try{
    const r=await api('POST','/api/config',{memory:{enabled:$('cfg-memory').checked}});
    if(r.ok){
      toast('记忆功能已'+($('cfg-memory').checked?'开启':'关闭'),'success');
      const ms=await api('GET','/api/memory/stats');
      if(ms.enabled){$('memStats').textContent='已存 '+ms.count+' 条，'+ms.size_mb+'MB';}
      else{$('memStats').textContent='记忆功能未启用';}
    }else{toast('切换失败：'+(r.error||''),'error');}
  }catch(e){toast('切换失败','error');}
}
async function clearMemory(){
  if(!confirm('确定要清空所有记忆记录吗？此操作不可恢复。'))return;
  const r=await api('POST','/api/memory/clear');
  if(r.ok){toast('记忆库已清空','success');loadSettings();}
  else toast('清空失败：'+(r.error||''),'error');
}

// Log settings
async function loadLogSettings(){
  try{
    const sel=$('cfg-log-mode');
    if(!sel)return;
    const d=await api('GET','/api/config');
    sel.value=(d.logging||{}).mode||'basic';
  }catch(e){}
  try{
    const s=await api('GET','/api/logs/stats');
    $('logStats').textContent='日志文件 '+s.file_count+'个，共 '+s.total_size_mb+'MB'
      +(s.mode?'  (模式: '+s.mode+')':'');
  }catch(e){$('logStats').textContent='';}
}
async function switchLogMode(){
  const mode=$('cfg-log-mode').value;
  try{
    const r=await api('POST','/api/logs/mode',{mode});
    if(r.ok){toast('日志模式已切换为 '+mode,'success');}
    else{toast('切换失败：'+(r.error||''),'error');}
  }catch(e){toast('切换失败','error');}
}
async function cleanupLogs(){
  if(!confirm('确定要清理过期日志文件吗？'))return;
  try{
    const r=await api('POST','/api/logs/cleanup');
    if(r.ok){
      toast('已清理 '+(r.deleted||0)+' 个过期日志文件','success');
      loadLogSettings();
    }else{toast('清理失败：'+(r.error||''),'error');}
  }catch(e){toast('清理失败','error');}
}
