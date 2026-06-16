/**
 * Data Sources page — upload zone, connected sources list, data preview.
 */
const SourcesPage = (() => {
  let _selectedTable = null;

  function render(root) {
    root.innerHTML = `
      <div class="p-gutter h-full overflow-y-auto custom-scrollbar">
        <div class="flex items-center justify-between mb-6">
          <h1 class="text-headline-md font-semibold">数据源管理</h1>
          <button class="btn-secondary" onclick="SourcesPage.refresh()">
            <span class="material-symbols-outlined text-[18px]">refresh</span>
            刷新
          </button>
        </div>

        <div class="grid grid-cols-12 gap-6">
          <!-- Upload Zone -->
          <div class="col-span-12 lg:col-span-5">
            <div class="stitch-card p-8 text-center border-2 border-dashed border-outline-variant hover:border-secondary transition-colors"
                 id="sources-dropzone"
                 ondragover="event.preventDefault(); this.classList.add('border-secondary','bg-secondary/5')"
                 ondragleave="this.classList.remove('border-secondary','bg-secondary/5')"
                 ondrop="event.preventDefault(); this.classList.remove('border-secondary','bg-secondary/5'); handleFiles(event.dataTransfer.files)">
              <span class="material-symbols-outlined text-[48px] text-outline-variant mb-4">cloud_upload</span>
              <p class="text-body-md text-on-surface mb-2">拖放数据文件到此处</p>
              <p class="text-body-sm text-on-surface-variant mb-4">支持 CSV, XLSX, XLS, PDF, DOCX, TXT</p>
              <label class="btn-primary cursor-pointer">
                <span class="material-symbols-outlined text-[18px]">folder_open</span>
                浏览文件
                <input type="file" multiple accept=".csv,.xlsx,.xls,.pdf,.docx,.txt" class="hidden"
                       onchange="handleFiles(this.files)">
              </label>
            </div>
          </div>

          <!-- Connected Sources -->
          <div class="col-span-12 lg:col-span-7">
            <div class="stitch-card">
              <div class="px-6 py-4 border-b border-surface-container flex justify-between items-center">
                <h3 class="text-body-md font-semibold">已连接数据源</h3>
                <span class="label-caps text-on-surface-variant" id="sources-count">--</span>
              </div>
              <div id="sources-list" class="max-h-[400px] overflow-y-auto custom-scrollbar">
                <p class="p-6 text-body-sm text-on-surface-variant">加载中...</p>
              </div>
            </div>
          </div>
        </div>

        <!-- Data Preview -->
        <div class="mt-6" id="sources-preview-wrap" style="display:none">
          <div class="stitch-card">
            <div class="px-6 py-4 border-b border-surface-container flex justify-between items-center">
              <h3 class="text-body-md font-semibold" id="preview-title">数据预览</h3>
              <div class="flex gap-2">
                <button class="btn-ghost text-body-sm" id="preview-profile-btn">
                  <span class="material-symbols-outlined text-[18px]">analytics</span>
                  表结构
                </button>
                <button class="btn-ghost text-body-sm" id="preview-quality-btn">
                  <span class="material-symbols-outlined text-[18px]">verified</span>
                  数据质量
                </button>
              </div>
            </div>
            <div id="sources-preview" class="p-4 overflow-x-auto">
              <p class="text-body-sm text-on-surface-variant">选择数据源查看预览</p>
            </div>
          </div>
        </div>
      </div>`;

    _loadTables();
  }

  async function _loadTables() {
    try {
      const data = await api('GET', '/api/tables');
      const tables = Array.isArray(data) ? data : (data.tables || []);
      const countEl = document.getElementById('sources-count');
      const listEl = document.getElementById('sources-list');
      if (countEl) countEl.textContent = tables.length + ' 张表';
      if (!listEl) return;

      if (!tables.length) {
        listEl.innerHTML = '<p class="p-6 text-body-sm text-on-surface-variant">暂无数据表，请上传文件</p>';
        return;
      }

      listEl.innerHTML = tables.map(t => `
        <div class="flex items-center justify-between px-6 py-3 border-b border-surface-container hover:bg-surface-container-low transition-colors cursor-pointer"
             onclick="SourcesPage.selectTable('${esc(t.name || t.table_name)}')">
          <div class="flex items-center gap-3">
            <span class="material-symbols-outlined text-secondary text-[20px]">table_chart</span>
            <div>
              <div class="text-body-sm font-semibold">${esc(t.name || t.table_name)}</div>
              <div class="label-caps text-outline mt-0.5">${(t.rows || t.row_count || 0).toLocaleString()} 行 · ${(t.columns || t.col_count || 0)} 列</div>
            </div>
          </div>
          <span class="status-badge ready">已连接</span>
        </div>`).join('');
    } catch (e) {
      const el = document.getElementById('sources-list');
      if (el) el.innerHTML = '<p class="p-6 text-body-sm text-error">加载失败</p>';
    }
  }

  async function selectTable(name) {
    _selectedTable = name;
    const wrap = document.getElementById('sources-preview-wrap');
    const title = document.getElementById('preview-title');
    const preview = document.getElementById('sources-preview');
    if (wrap) wrap.style.display = '';
    if (title) title.textContent = '数据预览: ' + name;
    if (preview) preview.innerHTML = '<p class="text-body-sm text-on-surface-variant">加载中...</p>';

    try {
      const data = await api('GET', `/api/tables/${encodeURIComponent(name)}/profile`);
      if (!preview) return;
      if (data && data.columns) {
        let html = `<table class="stitch-table"><thead><tr>
          <th>列名</th><th>类型</th><th>示例</th><th>空值率</th>
        </tr></thead><tbody>`;
        data.columns.forEach(c => {
          html += `<tr>
            <td class="font-medium">${esc(c.name)}</td>
            <td class="data-mono">${esc(c.dtype || c.type || '--')}</td>
            <td class="data-mono text-body-sm">${esc(String(c.sample || c.example || '--').substring(0, 40))}</td>
            <td class="data-mono">${c.null_pct != null ? c.null_pct + '%' : '--'}</td>
          </tr>`;
        });
        html += '</tbody></table>';
        preview.innerHTML = html;
      } else {
        preview.innerHTML = '<p class="text-body-sm text-on-surface-variant">无法获取表结构</p>';
      }
    } catch (e) {
      if (preview) preview.innerHTML = '<p class="text-body-sm text-error">加载失败</p>';
    }
  }

  function refresh() { _loadTables(); }

  return { render, selectTable, refresh };
})();
