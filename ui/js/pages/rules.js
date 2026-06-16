/**
 * Analysis Rules page — skill templates, entity groups, parameters.
 */
const RulesPage = (() => {
  const _grpMap = {};

  function render(root) {
    root.innerHTML = `
      <div class="p-gutter h-full overflow-y-auto custom-scrollbar">
        <div class="flex items-center justify-between mb-6">
          <div>
            <h1 class="text-headline-md font-semibold">分析规则配置</h1>
            <p class="text-body-sm text-on-surface-variant mt-1">定义自动化资产分析的逻辑和参数</p>
          </div>
          <button class="btn-primary" onclick="RulesPage.openBuilder()">
            <span class="material-symbols-outlined text-[18px]">add</span>
            创建规则
          </button>
        </div>

        <!-- Analysis Templates -->
        <div class="mb-8">
          <h2 class="label-caps text-on-surface-variant mb-4">分析模板</h2>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4" id="rules-templates">
            <p class="text-body-sm text-on-surface-variant col-span-3">加载中...</p>
          </div>
        </div>

        <div class="grid grid-cols-12 gap-6 mb-8">
          <!-- Custom Parameters -->
          <div class="col-span-12 lg:col-span-6 stitch-card">
            <div class="p-6 border-b border-surface-container">
              <h3 class="text-headline-md font-semibold">自定义参数</h3>
            </div>
            <div class="p-6" id="rules-params">
              <p class="text-body-sm text-on-surface-variant">加载中...</p>
            </div>
          </div>

          <!-- Entity Groups -->
          <div class="col-span-12 lg:col-span-6 stitch-card">
            <div class="px-6 py-4 border-b border-surface-container flex justify-between items-center">
              <h3 class="text-headline-md font-semibold">集团系管理</h3>
              <button class="btn-ghost text-body-sm" onclick="RulesPage.createGroup()">
                <span class="material-symbols-outlined text-[18px]">group_add</span>
                新建
              </button>
            </div>
            <div class="p-4 max-h-[400px] overflow-y-auto custom-scrollbar" id="rules-groups">
              <p class="text-body-sm text-on-surface-variant">加载中...</p>
            </div>
          </div>
        </div>
      </div>`;

    _loadSkills();
    _loadParams();
    _loadGroups();
  }

  async function _loadSkills() {
    try {
      const data = await api('GET', '/api/skills/status');
      const el = document.getElementById('rules-templates');
      if (!el) return;
      const skills = data.skills || data || [];
      if (!skills.length) {
        el.innerHTML = '<p class="text-body-sm text-on-surface-variant col-span-3">暂无可用分析模板</p>';
        return;
      }

      const iconMap = {
        concentration_monitor: 'security',
        fund_nav_report: 'trending_up',
        liquidity: 'water_drop',
        position_query: 'search',
        weekly_report_generator: 'summarize',
        meeting_report: 'groups',
        flexible_stats: 'query_stats',
      };
      const labelMap = {
        concentration_monitor: '风险敞口',
        fund_nav_report: '业绩分析',
        liquidity: '流动性',
      };

      el.innerHTML = skills.map(s => {
        const name = s.name || s.skill_name || '';
        const icon = iconMap[name] || 'analytics';
        const label = labelMap[name] || s.description || name;
        const ready = s.ready !== false;
        return `<div class="stitch-card p-6 hover:border-secondary transition-colors cursor-pointer ${ready ? '' : 'opacity-60'}"
                     onclick="${ready ? `executeSkill('${esc(name)}')` : ''}">
          <div class="flex items-center gap-3 mb-3">
            <div class="w-10 h-10 rounded-lg bg-secondary/10 flex items-center justify-center">
              <span class="material-symbols-outlined text-secondary">${icon}</span>
            </div>
            <span class="status-badge ${ready ? 'ready' : 'processing'}">${ready ? '就绪' : '缺少数据'}</span>
          </div>
          <h4 class="text-body-md font-semibold mb-1">${esc(label)}</h4>
          <p class="text-body-sm text-on-surface-variant">${esc(s.description || '')}</p>
        </div>`;
      }).join('');
    } catch (e) {
      const el = document.getElementById('rules-templates');
      if (el) el.innerHTML = '<p class="text-body-sm text-error col-span-3">加载失败</p>';
    }
  }

  async function _loadParams() {
    try {
      const data = await api('GET', '/api/config');
      const el = document.getElementById('rules-params');
      if (!el) return;
      const cc = data.calculation_config || {};
      const conc = cc.concentration || {};
      el.innerHTML = `
        <div class="space-y-4">
          <div>
            <h4 class="label-caps text-on-surface-variant mb-3">集中度监控</h4>
            <div class="space-y-3">
              <div class="flex justify-between items-center">
                <span class="text-body-sm">主体集中度阈值</span>
                <span class="data-mono font-semibold">${conc.threshold_entity || 10}%</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-body-sm">单券集中度阈值</span>
                <span class="data-mono font-semibold">${conc.threshold_single_bond || 10}%</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-body-sm">市值字段</span>
                <span class="data-mono text-body-sm">${esc(conc.market_value_field || '穿透后市值')}</span>
              </div>
            </div>
          </div>
          <div>
            <h4 class="label-caps text-on-surface-variant mb-3">其他配置</h4>
            <div class="space-y-3">
              <div class="flex justify-between items-center">
                <span class="text-body-sm">集团合并计算</span>
                <span class="data-mono font-semibold">${conc.use_group_merge ? '开启' : '关闭'}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-body-sm">数据最大天龄</span>
                <span class="data-mono font-semibold">${conc.data_max_age_days || 1} 天</span>
              </div>
            </div>
          </div>
        </div>`;
    } catch (e) {
      const el = document.getElementById('rules-params');
      if (el) el.innerHTML = '<p class="text-body-sm text-on-surface-variant">无法加载配置</p>';
    }
  }

  async function _loadGroups() {
    const el = document.getElementById('rules-groups');
    if (!el) return;
    try {
      const r = await api('GET', '/api/groups');
      const groups = r.groups || {};
      const entries = Object.entries(groups);
      Object.keys(_grpMap).forEach(k => delete _grpMap[k]);

      if (!entries.length) {
        el.innerHTML = '<p class="text-body-sm text-on-surface-variant">暂无集团系，点击"新建"添加</p>';
        return;
      }

      el.innerHTML = entries.map(([name, members]) => {
        const sid = 'rg_' + name.replace(/[^a-zA-Z0-9一-鿿]/g, '_');
        _grpMap[sid] = name;
        const ms = (members || []).map(m =>
          `<div class="flex items-center justify-between py-1.5 px-2 rounded hover:bg-surface-container-low group">
            <span class="text-body-sm">${esc(m)}</span>
            <button class="opacity-0 group-hover:opacity-100 text-error text-body-sm transition-opacity"
                    onclick="RulesPage.removeMember('${esc(name)}','${esc(m)}')">
              <span class="material-symbols-outlined text-[16px]">close</span>
            </button>
          </div>`
        ).join('');

        return `<div class="mb-4 last:mb-0">
          <div class="flex items-center justify-between cursor-pointer py-2 px-2 rounded hover:bg-surface-container-low"
               onclick="document.getElementById('${sid}-body').classList.toggle('hidden')">
            <div class="flex items-center gap-2">
              <span class="material-symbols-outlined text-[18px] text-secondary">corporate_fare</span>
              <span class="text-body-md font-semibold">${esc(name)}</span>
              <span class="status-badge ready">${(members || []).length} 个主体</span>
            </div>
            <div class="flex items-center gap-1">
              <button class="btn-ghost p-1" onclick="event.stopPropagation();RulesPage.deleteGroup('${esc(name)}')" title="删除集团">
                <span class="material-symbols-outlined text-[18px] text-error">delete</span>
              </button>
              <span class="material-symbols-outlined text-[18px]">expand_more</span>
            </div>
          </div>
          <div id="${sid}-body" class="ml-8 mt-1 hidden">
            ${ms}
            <div class="flex gap-2 mt-2 items-center">
              <input type="text" id="${sid}-add"
                     class="flex-1 px-3 py-1.5 rounded-lg border border-outline-variant bg-surface-container-lowest text-body-sm"
                     placeholder="输入主体名称"
                     onkeydown="if(event.key==='Enter')RulesPage.addMember('${sid}')">
              <button class="btn-ghost text-body-sm" onclick="RulesPage.addMember('${sid}')">
                <span class="material-symbols-outlined text-[18px]">add</span>
              </button>
            </div>
          </div>
        </div>`;
      }).join('');
    } catch (e) {
      el.innerHTML = '<p class="text-body-sm text-error">加载失败</p>';
    }
  }

  function createGroup() {
    const name = prompt('输入新集团系名称：');
    if (!name || !name.trim()) return;
    api('POST', '/api/groups', { name: name.trim(), members: [] }).then(r => {
      if (r.ok) { _loadGroups(); toast('已创建：' + name.trim(), 'success'); }
      else toast('创建失败：' + (r.error || ''), 'error');
    });
  }

  async function addMember(sid) {
    const groupName = _grpMap[sid];
    if (!groupName) return;
    const inp = document.getElementById(sid + '-add');
    if (!inp) return;
    const entity = inp.value.trim();
    if (!entity) return;
    const r = await api('POST', '/api/groups/' + encodeURIComponent(groupName) + '/members', { entity });
    if (r.ok) { inp.value = ''; _loadGroups(); toast('已添加：' + entity, 'success'); }
    else toast('添加失败：' + (r.error || ''), 'error');
  }

  async function removeMember(groupName, entity) {
    const r = await api('DELETE', '/api/groups/' + encodeURIComponent(groupName) + '/members', { entity });
    if (r.ok) { _loadGroups(); toast('已移除：' + entity); }
    else toast('移除失败：' + (r.error || ''), 'error');
  }

  async function deleteGroup(name) {
    if (!confirm('确定要删除集团系「' + name + '」及其所有主体吗？')) return;
    const r = await api('DELETE', '/api/groups/' + encodeURIComponent(name));
    if (r.ok) { _loadGroups(); toast('已删除：' + name, 'success'); }
    else toast('删除失败：' + (r.error || ''), 'error');
  }

  function openBuilder() {
    if (typeof openSkillBuilder === 'function') openSkillBuilder();
  }

  return { render, openBuilder, createGroup, addMember, removeMember, deleteGroup };
})();
