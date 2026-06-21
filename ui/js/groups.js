// groups.js — Group (集团系) CRUD operations

const _grpMap={};
function grpSid(name){return'g_'+String(name||'').replace(/[^a-zA-Z0-9㐀-鿿豈-﫿]/g,'_');}

async function loadGroups(){
  try{
    const r=await fetch('/api/groups');if(!r.ok)return;
    const d=await r.json();const groups=d.groups||{};
    const list=$('groupList');
    const entries=Object.entries(groups);
    if(!entries.length){
      list.innerHTML='<div class="s-item" style="color:var(--text-3)">暂无集团系</div>';return;
    }
    Object.keys(_grpMap).forEach(k=>delete _grpMap[k]);
    list.innerHTML=entries.map(([name,members])=>{
      const sid=grpSid(name);
      _grpMap[sid]=name;
      const ms=(members||[]).map(m=>
        '<div class="grp-member" data-group="'+esc(name)+'" data-member="'+esc(m)+'">'
        +'<span class="m-name">'+esc(m)+'</span>'
        +'<span class="m-del" onclick="removeMemberEl(this)">×</span>'
        +'</div>'
      ).join('');
      return '<div class="grp-item" id="'+sid+'">'
        +'<div class="grp-hd" onclick="toggleGrp(\''+sid+'\')">'
        +'<span class="grp-arr">▸</span>'
        +'<span class="grp-name">'+esc(name)+'</span>'
        +'<span class="grp-cnt">'+(members||[]).length+'</span>'
        +'<span class="grp-del" onclick="event.stopPropagation();confirmDeleteGroup(\''+sid+'\')" title="删除集团">×</span>'
        +'</div>'
        +'<div class="grp-bd">'+ms
        +'<div class="grp-add">'
        +'<input type="text" id="addm-'+sid+'" placeholder="添加主体名称"'
        +' onkeydown="if(event.key===\'Enter\')addMember(\''+sid+'\')" />'
        +'<button onclick="addMember(\''+sid+'\')">+</button>'
        +'</div></div></div>';
    }).join('');
  }catch(e){}
}
function toggleGrp(sid){
  const item=document.getElementById(sid);
  if(item)item.classList.toggle('open');
}
async function addMember(sid){
  const groupName=_grpMap[sid];if(!groupName)return;
  const inp=document.getElementById('addm-'+sid);if(!inp)return;
  const entity=inp.value.trim();if(!entity)return;
  const r=await api('POST','/api/groups/'+encodeURIComponent(groupName)+'/members',{entity});
  if(r.ok){inp.value='';loadGroups();toast('已添加：'+entity,'success');}
  else toast('添加失败：'+(r.error||''),'error');
}
function removeMemberEl(btn){
  const item=btn.closest('.grp-member');if(!item)return;
  removeMember(item.dataset.group,item.dataset.member);
}
async function removeMember(groupName,entity){
  const r=await api('DELETE','/api/groups/'+encodeURIComponent(groupName)+'/members',{entity});
  if(r.ok){loadGroups();toast('已移除：'+entity);}
  else toast('移除失败：'+(r.error||''),'error');
}
async function confirmDeleteGroup(sid){
  const name=_grpMap[sid];if(!name)return;
  if(!confirm('确定要删除集团系「'+name+'」及其所有主体吗？'))return;
  const r=await api('DELETE','/api/groups/'+encodeURIComponent(name));
  if(r.ok){loadGroups();toast('已删除：'+name,'success');}
  else toast('删除失败：'+(r.error||''),'error');
}
function showCreateGroup(){
  const name=prompt('输入新集团系名称：');
  if(!name||!name.trim())return;
  createGroup(name.trim());
}
async function createGroup(name){
  const r=await api('POST','/api/groups',{name,members:[]});
  if(r.ok){loadGroups();toast('已创建：'+name,'success');openSec('groups');}
  else toast('创建失败：'+(r.error||''),'error');
}
