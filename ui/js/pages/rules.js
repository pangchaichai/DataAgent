/**
 * Analysis Rules page — skill templates, logic builder, parameters.
 */
const RulesPage = (() => {
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

        <!-- Custom Parameters -->
        <div class="stitch-card">
          <div class="p-6 border-b border-surface-container">
            <h3 class="text-headline-md font-semibold">自定义参数</h3>
          </div>
          <div class="p-6" id="rules-params">
            <p class="text-body-sm text-on-surface-variant">加载中...</p>
          </div>
        </div>
      </div>`;

    _loadSkills();
    _loadParams();
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
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
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

  function openBuilder() {
    if (typeof openSkillBuilder === 'function') openSkillBuilder();
  }

  return { render, openBuilder };
})();
