// data_page.js — Data source management page lifecycle

const DataPage = {
  onEnter() {
    loadTables().then(() => this._renderTableList());
    this._loadWorkdir();
  },

  async _loadWorkdir() {
    const list = $('dataPageWorkdirList');
    if (!list) return;
    try {
      const d = await api('GET', '/api/workdir/files');
      if (!d.work_dir) {
        list.innerHTML = '<div class="s-item" style="color:var(--text-3)">未配置（在设置中添加目录路径）</div>';
        return;
      }
      const files = d.files || [];
      if (!files.length) {
        list.innerHTML = '<div class="s-item" style="color:var(--text-3)">目录为空（无 CSV/Excel 文件）</div>';
        return;
      }
      list.innerHTML = files.map(f =>
        '<div class="s-item">'
        + '<span class="s-text" title="' + esc(f.filename) + '">' + esc(f.filename) + '</span>'
        + '<span class="s-meta">' + f.size_kb + 'KB</span>'
        + '<span class="act" style="font-size:11px" onclick="loadWorkdirFile(\'' + esc(f.filename) + '\')">加载</span>'
        + '</div>'
      ).join('');
    } catch (e) {
      list.innerHTML = '<div class="s-item" style="color:var(--text-3)">加载失败</div>';
    }
  },

  _renderTableList() {
    const container = $('dataPageTableList');
    if (!container) return;
    const tables = window._cachedTables || [];
    if (!tables.length) {
      container.innerHTML = '<div class="dp-empty">暂无已加载的数据表。点击上方「上传数据」导入 CSV/Excel 文件。</div>';
      return;
    }
    container.innerHTML = tables.map(t => {
      const color = t.type === 'holding' ? 'var(--green)' : t.type === 'nav' ? 'var(--blue)' : 'var(--text-3)';
      const typeLabel = {holding:'持仓表',nav:'净值表',rating_entity:'主体评级',rating_bond:'债券评级',monitoring:'监控数据'}[t.type] || t.type;
      return '<div class="dp-table-card">'
        + '<div class="dp-tc-header">'
        + '<span class="dp-tc-dot" style="background:' + color + '"></span>'
        + '<span class="dp-tc-name">' + esc(t.name) + '</span>'
        + '<span class="dp-tc-meta">' + typeLabel + ' · ' + t.rows + '行</span>'
        + '<div class="dp-tc-actions">'
        + '<button class="dp-btn" onclick="openProfile(\'' + esc(t.name) + '\')">剖析</button>'
        + '<button class="dp-btn dp-btn-del" onclick="deleteTable(\'' + esc(t.name) + '\')">移除</button>'
        + '</div>'
        + '</div>'
        + '</div>';
    }).join('');
  }
};

function dpTriggerUpload() {
  $('fileInput').click();
}

function dpRefreshTableList() {
  loadTables().then(() => DataPage._renderTableList());
}

function dpRefreshWorkdir() {
  DataPage._loadWorkdir();
}
