// data_page.js — Data source management page lifecycle

const DataPage = {
  onEnter() {
    loadTables().then(() => this._renderTableList());
    this._loadWorkdir();
    this._initDragDrop();
  },

  _initDragDrop() {
    const page = $('page-data');
    if (!page || page._dragInited) return;
    page._dragInited = true;
    page.addEventListener('dragover', e => { e.preventDefault(); page.classList.add('dragover'); });
    page.addEventListener('dragleave', e => {
      if (!page.contains(e.relatedTarget)) page.classList.remove('dragover');
    });
    page.addEventListener('drop', e => {
      e.preventDefault(); page.classList.remove('dragover');
      handleFiles(e.dataTransfer.files);
    });
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
    const groups = _groupTablesByType(tables);
    const typeColors = {holding:'var(--green)',nav:'var(--blue)',rating_entity:'var(--orange)',rating_bond:'var(--purple,#9b59b6)',monitoring:'var(--text-3)'};
    const typeLabels = {holding:'持仓表',nav:'净值表',rating_entity:'主体评级',rating_bond:'债券评级',monitoring:'监控数据',unknown:'其他'};

    container.innerHTML = groups.map(g => {
      const color = typeColors[g.type] || 'var(--text-3)';
      const label = typeLabels[g.type] || g.type;
      const sorted = g.tables.slice().sort((a, b) => (b.date_tag || '').localeCompare(a.date_tag || ''));
      const cards = sorted.map(t => {
        const dateBadge = t.date_tag
          ? '<span class="dp-date-badge">' + esc(t.date_tag.replace(/^\d{4}/, '').replace(/^-?/, '')) + '</span>'
          : '';
        return '<div class="dp-table-card">'
          + '<div class="dp-tc-header">'
          + '<span class="dp-tc-dot" style="background:' + color + '"></span>'
          + '<span class="dp-tc-name">' + esc(t.name) + '</span>'
          + dateBadge
          + '<span class="dp-tc-meta">' + t.rows + '行</span>'
          + '<div class="dp-tc-actions">'
          + '<button class="dp-btn" onclick="openProfile(\'' + esc(t.name) + '\')">剖析</button>'
          + '<button class="dp-btn dp-btn-del" onclick="deleteTable(\'' + esc(t.name) + '\')">移除</button>'
          + '</div>'
          + '</div>'
          + '</div>';
      }).join('');
      return '<div class="dp-type-group">'
        + '<div class="dp-type-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">'
        + '<span class="dp-type-dot" style="background:' + color + '"></span>'
        + '<span class="dp-type-label">' + esc(label) + '</span>'
        + '<span class="dp-type-count">(' + g.tables.length + ')</span>'
        + '<span class="dp-type-chevron">▾</span>'
        + '</div>'
        + '<div class="dp-type-body">' + cards + '</div>'
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
