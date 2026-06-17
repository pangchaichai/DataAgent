/**
 * Dashboard page — KPI cards, charts, tasks, alerts.
 */
const DashboardPage = (() => {
  let _mounted = false;

  function render(root) {
    root.innerHTML = `
      <div class="p-gutter h-full overflow-y-auto custom-scrollbar">
        <h1 class="text-headline-md font-semibold mb-6">仪表盘</h1>

        <!-- KPI Cards -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8" id="dash-kpis">
          ${_kpiCard('table_chart', '已加载数据表', '--', '', 'kpi-tables')}
          ${_kpiCard('dataset', '数据总行数', '--', '', 'kpi-rows')}
          ${_kpiCard('smart_toy', 'LLM 状态', '--', '', 'kpi-llm')}
        </div>

        <div class="grid grid-cols-12 gap-6">
          <!-- Active Tasks -->
          <div class="col-span-12 lg:col-span-7 stitch-card">
            <div class="p-6 border-b border-surface-container">
              <h3 class="text-headline-md font-semibold">近期会话</h3>
            </div>
            <div id="dash-sessions" class="p-4 text-body-sm text-on-surface-variant">
              加载中...
            </div>
          </div>

          <!-- Alerts -->
          <div class="col-span-12 lg:col-span-5 stitch-card flex flex-col">
            <div class="px-6 py-4 border-b border-surface-container flex justify-between items-center">
              <h3 class="text-headline-md font-semibold">系统告警</h3>
              <span class="status-badge processing" id="dash-alert-count">--</span>
            </div>
            <div id="dash-alerts" class="flex-1 overflow-y-auto custom-scrollbar p-4 text-body-sm text-on-surface-variant">
              加载中...
            </div>
          </div>
        </div>
      </div>`;

    _mounted = true;
    _loadData();
  }

  function _kpiCard(icon, label, value, sub, id) {
    return `<div class="kpi-card group">
      <div class="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition">
        <span class="material-symbols-outlined text-[48px]">${icon}</span>
      </div>
      <p class="label-caps text-on-surface-variant mb-2">${label}</p>
      <div class="flex items-baseline gap-2" id="${id}">
        <span class="text-display-lg">${value}</span>
        ${sub ? `<span class="label-caps text-secondary">${sub}</span>` : ''}
      </div>
    </div>`;
  }

  async function _loadData() {
    try {
      const [health, tables] = await Promise.all([
        api('GET', '/api/health').catch(() => null),
        api('GET', '/api/tables').catch(() => null)
      ]);

      if (!_mounted) return;

      const kpiTables = document.getElementById('kpi-tables');
      const kpiRows = document.getElementById('kpi-rows');
      const kpiLlm = document.getElementById('kpi-llm');

      if (tables && kpiTables) {
        const count = Array.isArray(tables) ? tables.length : (tables.tables || []).length;
        const tlist = Array.isArray(tables) ? tables : (tables.tables || []);
        const totalRows = tlist.reduce((s, t) => s + (t.rows || t.row_count || 0), 0);
        kpiTables.innerHTML = `<span class="text-display-lg">${count}</span><span class="label-caps text-secondary">张表</span>`;
        kpiRows.innerHTML = `<span class="text-display-lg">${totalRows.toLocaleString()}</span><span class="label-caps text-on-surface-variant">行</span>`;
      }

      if (health && kpiLlm) {
        const online = health.llm_ok || health.llm_status === 'online';
        const status = online ? '在线' : '离线';
        const cls = online ? 'text-success' : 'text-error';
        kpiLlm.innerHTML = `<span class="text-display-lg ${cls}">${status}</span>`;
      }

      _loadSessions();
    } catch (e) {
      console.error('[Dashboard]', e);
    }
  }

  async function _loadSessions() {
    try {
      const data = await api('GET', '/api/sessions');
      const el = document.getElementById('dash-sessions');
      if (!el) return;
      const sessions = Array.isArray(data) ? data : (data.sessions || []);
      if (!sessions.length) {
        el.innerHTML = '<p class="text-on-surface-variant p-4">暂无会话记录</p>';
        return;
      }
      el.innerHTML = `<table class="stitch-table">
        <thead><tr>
          <th>会话名称</th><th>时间</th><th>消息数</th>
        </tr></thead>
        <tbody>${sessions.slice(0, 10).map(s => `<tr>
          <td class="font-medium">${esc(s.title || s.id || '--')}</td>
          <td class="data-mono">${s.updated_at || s.created_at || '--'}</td>
          <td class="data-mono">${s.message_count || '--'}</td>
        </tr>`).join('')}</tbody>
      </table>`;
    } catch (e) {
      const el = document.getElementById('dash-sessions');
      if (el) el.innerHTML = '<p class="text-on-surface-variant p-4">无法加载会话</p>';
    }
  }

  return { render };
})();
