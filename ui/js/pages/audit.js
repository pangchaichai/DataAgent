/**
 * Audit Log page — session browser with detail view.
 */
const AuditPage = (() => {
  let _selectedSession = null;

  function render(root) {
    root.innerHTML = `
      <div class="flex h-full overflow-hidden">
        <!-- Left: Session List -->
        <aside class="w-72 bg-surface-container-lowest border-r border-surface-container-highest flex flex-col">
          <div class="p-4 border-b border-surface-container-highest">
            <h2 class="text-body-md font-semibold">系统审计日志</h2>
            <p class="text-body-sm text-on-surface-variant mt-1">完整的分析会话和数据请求记录</p>
          </div>
          <!-- Filters -->
          <div class="p-3 border-b border-surface-container-highest flex gap-2 flex-wrap">
            <select class="text-body-sm bg-surface-container-low border-none rounded px-2 py-1" id="audit-filter-days">
              <option value="30">近 30 天</option>
              <option value="7">近 7 天</option>
              <option value="1">今天</option>
            </select>
          </div>
          <div class="flex-1 overflow-y-auto custom-scrollbar" id="audit-session-list">
            <p class="p-4 text-body-sm text-on-surface-variant">加载中...</p>
          </div>
        </aside>

        <!-- Center: Detail -->
        <div class="flex-1 overflow-y-auto custom-scrollbar p-gutter" id="audit-detail">
          <div class="flex flex-col items-center justify-center h-full text-on-surface-variant">
            <span class="material-symbols-outlined text-[48px] text-outline-variant mb-4">history</span>
            <p class="text-body-md">选择一个会话查看详情</p>
          </div>
        </div>
      </div>`;

    _loadSessions();
  }

  async function _loadSessions() {
    try {
      const data = await api('GET', '/api/sessions');
      const list = document.getElementById('audit-session-list');
      if (!list) return;
      const sessions = Array.isArray(data) ? data : (data.sessions || []);
      if (!sessions.length) {
        list.innerHTML = '<p class="p-4 text-body-sm text-on-surface-variant">暂无审计记录</p>';
        return;
      }

      list.innerHTML = sessions.map(s => `
        <div class="p-3 border-b border-surface-container hover:bg-surface-container-low transition-colors cursor-pointer"
             onclick="AuditPage.selectSession('${esc(s.id)}')">
          <div class="text-body-sm font-medium truncate">${esc(s.title || s.id || '会话')}</div>
          <div class="label-caps text-outline mt-1">${s.updated_at || s.created_at || '--'}</div>
        </div>`).join('');
    } catch (e) {
      const list = document.getElementById('audit-session-list');
      if (list) list.innerHTML = '<p class="p-4 text-body-sm text-error">加载失败</p>';
    }
  }

  async function selectSession(id) {
    _selectedSession = id;
    const detail = document.getElementById('audit-detail');
    if (!detail) return;
    detail.innerHTML = '<p class="text-body-sm text-on-surface-variant">加载中...</p>';

    try {
      const data = await api('GET', `/api/sessions/${encodeURIComponent(id)}`);
      const session = data.session || data;
      const messages = session.messages || [];

      let html = `
        <div class="max-w-4xl">
          <div class="flex items-center justify-between mb-6">
            <h2 class="text-headline-md font-semibold">${esc(session.title || session.id || '会话详情')}</h2>
            <div class="flex gap-2">
              <span class="status-badge ready">${esc(session.id || '--')}</span>
            </div>
          </div>

          <div class="stitch-card mb-6">
            <div class="p-4 border-b border-surface-container">
              <h3 class="label-caps text-on-surface-variant">会话概览</h3>
            </div>
            <div class="p-4 grid grid-cols-3 gap-4">
              <div>
                <div class="label-caps text-outline mb-1">创建时间</div>
                <div class="data-mono text-body-sm">${session.created_at || '--'}</div>
              </div>
              <div>
                <div class="label-caps text-outline mb-1">消息数</div>
                <div class="data-mono text-body-sm">${messages.length}</div>
              </div>
              <div>
                <div class="label-caps text-outline mb-1">状态</div>
                <div class="text-body-sm font-semibold text-success">已完成</div>
              </div>
            </div>
          </div>

          <!-- Messages Timeline -->
          <div class="space-y-4">
            <h3 class="label-caps text-on-surface-variant">对话记录</h3>`;

      messages.forEach(m => {
        const isUser = m.role === 'user';
        const icon = isUser ? 'person' : 'neurology';
        const label = isUser ? '用户' : 'DataAgent AI';
        const content = typeof m.content === 'string' ? m.content : JSON.stringify(m.content);
        html += `
            <div class="flex gap-3">
              <div class="w-8 h-8 rounded ${isUser ? 'bg-secondary-fixed' : 'bg-primary-container'} flex items-center justify-center flex-shrink-0">
                <span class="material-symbols-outlined text-[16px] ${isUser ? 'text-secondary' : 'text-on-secondary-container'}">${icon}</span>
              </div>
              <div class="flex-1 min-w-0">
                <div class="label-caps text-on-surface-variant mb-1">${label}</div>
                <div class="text-body-sm text-on-surface whitespace-pre-wrap break-words">${esc(content.substring(0, 500))}${content.length > 500 ? '...' : ''}</div>
              </div>
            </div>`;
      });

      html += `</div></div>`;
      detail.innerHTML = html;
    } catch (e) {
      detail.innerHTML = '<p class="text-body-sm text-error">加载会话详情失败</p>';
    }
  }

  return { render, selectSession };
})();
