/**
 * Data Sources page — upload zone, connected sources list, entity groups, work directory, data preview.
 */
const SourcesPage = (() => {
  let _selectedTable = null;
  const _grpMap = {};

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

        <!-- Entity Groups -->
        <div class="mt-6 stitch-card">
          <div class="px-6 py-4 border-b border-surface-container flex justify-between items-center">
            <div class="flex items-center gap-2">
              <span class="material-symbols-outlined text-[20px] text-secondary">corporate_fare</span>
              <h3 class="text-body-md font-semibold">集团系管理</h3>
            </div>
            <button class="btn-ghost text-body-sm" onclick="SourcesPage.createGroup()">
              <span class="material-symbols-outlined text-[18px]">group_add</span>
              新建
            </button>
          </div>
          <div class="p-4 max-h-[400px] overflow-y-auto custom-scrollbar" id="sources-groups">
            <p class="text-body-sm text-on-surface-variant">加载中...</p>
          </div>
        </div>

        <!-- Work Directory -->
        <div class="mt-6 stitch-card" id="sources-workdir-card">
          <div class="px-6 py-4 border-b border-surface-container flex justify-between items-center">
            <div class="flex items-center gap-2">
              <span class="material-symbols-outlined text-[20px] text-secondary">folder_special</span>
              <h3 class="text-body-md font-semibold">工作目录</h3>
            </div>
            <button class="btn-ghost text-body-sm" onclick="SourcesPage.refreshWorkdir()">
              <span class="material-symbols-outlined text-[18px]">refresh</span>
            </button>
          </div>
          <div id="sources-workdir" class="p-4 max-h-[300px] overflow-y-auto custom-scrollbar">
            <p class="text-body-sm text-on-surface-variant">加载中...</p>
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
    _loadGroups();
    _loadWorkdir();
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
              <div class="label-caps text-outline mt-0.5">${(t.rows || t.row_count || 0).toLocaleString()} 行 · ${(t.cols || t.columns || t.col_count || 0)} 列</div>
            </div>
          </div>
          <span class="status-badge ready">已连接</span>
        </div>`).join('');
    } catch (e) {
      const el = document.getElementById('sources-list');
      if (el) el.innerHTML = '<p class="p-6 text-body-sm text-error">加载失败</p>';
    }
  }

  async function _loadGroups() {
    const el = document.getElementById('sources-groups');
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
        const sid = 'sg_' + name.replace(/[^a-zA-Z0-9一-鿿]/g, '_');
        _grpMap[sid] = name;
        const ms = (members || []).map(m =>
          `<div class="flex items-center justify-between py-1.5 px-2 rounded hover:bg-surface-container-low group">
            <span class="text-body-sm">${esc(m)}</span>
            <button class="opacity-0 group-hover:opacity-100 text-error text-body-sm transition-opacity"
                    onclick="SourcesPage.removeMember('${esc(name)}','${esc(m)}')">
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
              <button class="btn-ghost p-1" onclick="event.stopPropagation();SourcesPage.deleteGroup('${esc(name)}')" title="删除集团">
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
                     onkeydown="if(event.key==='Enter')SourcesPage.addMember('${sid}')">
              <button class="btn-ghost text-body-sm" onclick="SourcesPage.addMember('${sid}')">
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

  async function _loadWorkdir() {
    const el = document.getElementById('sources-workdir');
    if (!el) return;
    try {
      const d = await api('GET', '/api/workdir/files');
      if (!d.work_dir) {
        el.innerHTML = `<div class="text-center py-4">
          <span class="material-symbols-outlined text-[32px] text-outline-variant mb-2">folder_off</span>
          <p class="text-body-sm text-on-surface-variant">未配置工作目录</p>
          <p class="text-body-sm text-on-surface-variant mt-1">在 <button class="text-secondary underline" onclick="openSettings()">设置</button> 中配置目录路径</p>
        </div>`;
        return;
      }
      const files = d.files || [];
      if (!files.length) {
        el.innerHTML = `<div class="text-center py-4">
          <span class="material-symbols-outlined text-[32px] text-outline-variant mb-2">folder_open</span>
          <p class="text-body-sm text-on-surface-variant">目录为空（无 CSV/Excel 文件）</p>
          <p class="label-caps text-outline mt-1">${esc(d.work_dir)}</p>
        </div>`;
        return;
      }

      el.innerHTML = `<p class="label-caps text-outline mb-3">${esc(d.work_dir)} · ${files.length} 个文件</p>`
        + files.map(f => `
        <div class="flex items-center justify-between py-2 px-3 rounded hover:bg-surface-container-low transition-colors group">
          <div class="flex items-center gap-2">
            <span class="material-symbols-outlined text-[18px] text-on-surface-variant">description</span>
            <span class="text-body-sm" title="${esc(f.filename)}">${esc(f.filename)}</span>
            <span class="label-caps text-outline">${f.size_kb} KB</span>
          </div>
          <button class="btn-ghost text-body-sm opacity-0 group-hover:opacity-100 transition-opacity"
                  onclick="SourcesPage.loadWorkdirFile('${esc(f.filename)}')">
            <span class="material-symbols-outlined text-[18px]">download</span>
            加载
          </button>
        </div>`).join('');
    } catch (e) {
      el.innerHTML = '<p class="text-body-sm text-error">加载失败</p>';
    }
  }

  async function loadWorkdirFile(filename) {
    if (typeof addSysMsg === 'function')
      addSysMsg('正在预览工作目录文件：<b>' + esc(filename) + '</b>…', 'blue');
    try {
      const d = await api('POST', '/api/workdir/preview', { filename });
      if (!d.ok) {
        toast('预览失败：' + (d.error || ''), 'error');
        return;
      }
      if (typeof showUploadConfirm === 'function') showUploadConfirm(d);
    } catch (e) {
      toast('预览请求失败：' + e.message, 'error');
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
            <td class="data-mono text-body-sm">${esc(String(Array.isArray(c.samples) ? c.samples[0] : (c.sample || c.example || '--')).substring(0, 40))}</td>
            <td class="data-mono">${c.null_rate != null ? (c.null_rate * 100).toFixed(1) + '%' : (c.null_pct != null ? c.null_pct + '%' : '--')}</td>
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

  function refresh() { _loadTables(); _loadGroups(); _loadWorkdir(); }
  function refreshWorkdir() { _loadWorkdir(); }

  return { render, selectTable, refresh, refreshWorkdir, loadWorkdirFile, createGroup, addMember, removeMember, deleteGroup };
})();
