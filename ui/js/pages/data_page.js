// data_page.js — Data source management page lifecycle

const DataPage = {
  onEnter() {
    loadTables().then(() => this._renderTableList());
    this._loadWorkdir();
    this._loadRemoteDB();
    this._loadVendorAPI();
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
      const batchBtn = '<div style="margin-bottom:8px">'
        + '<button class="dp-btn" style="font-size:12px;padding:5px 14px" onclick="dpLoadAllWorkdir()">'
        + '全部加载（' + files.length + '个）</button>'
        + '<span id="wdBatchStatus" style="font-size:12px;color:var(--text-3);margin-left:10px"></span>'
        + '</div>';
      list.innerHTML = batchBtn + files.map(f =>
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

  async _loadRemoteDB() {
    const list = $('dataPageRemoteDBList');
    if (!list) return;
    try {
      const d = await api('GET', '/api/datasource/connections');
      const conns = d.connections || [];
      if (!conns.length) {
        list.innerHTML = '<div class="s-item" style="color:var(--text-3)">未配置远程连接。点击「+ 添加」配置数据库。</div>';
        return;
      }
      const typeLabels = {mysql:'MySQL',postgresql:'PostgreSQL',sqlite:'SQLite',sqlserver:'SQL Server',oracle:'Oracle'};
      list.innerHTML = conns.map(c => {
        const label = typeLabels[c.db_type] || c.db_type;
        const dot = c.driver_available
          ? '<span style="color:var(--green)">●</span>'
          : '<span style="color:var(--text-3)" title="' + esc(c.driver_error) + '">○</span>';
        return '<div class="s-item">'
          + dot + ' '
          + '<span class="s-text" title="' + esc(c.name) + '">' + esc(c.name) + '</span>'
          + '<span class="s-meta">' + label + (c.host ? ' @ ' + esc(c.host) : '') + '</span>'
          + '<span class="act" style="font-size:11px;margin-left:auto" onclick="dpBrowseRemoteTables(\'' + esc(c.name) + '\')">浏览</span>'
          + '<span class="act" style="font-size:11px;margin-left:4px" onclick="dpEditConnection(\'' + esc(c.name) + '\')">编辑</span>'
          + '<span class="act" style="font-size:11px;margin-left:4px;color:var(--red,#e74c3c)" onclick="dpDeleteConnection(\'' + esc(c.name) + '\')">删除</span>'
          + '</div>';
      }).join('');
    } catch (e) {
      list.innerHTML = '<div class="s-item" style="color:var(--text-3)">加载失败</div>';
    }
  },

  async _loadVendorAPI() {
    const list = $('dataPageVendorList');
    if (!list) return;
    try {
      const d = await api('GET', '/api/vendor/status');
      const vendors = d.vendors || [];
      if (!vendors.length) {
        list.innerHTML = '<div class="s-item" style="color:var(--text-3)">无可用资讯 API</div>';
        return;
      }
      const nameLabels = {choice:'东方财富 Choice',ifind:'同花顺 iFinD',wind:'万得 Wind'};
      list.innerHTML = vendors.map(v => {
        const label = nameLabels[v.name] || v.name;
        const avail = v.available;
        const dot = avail
          ? '<span style="color:var(--green)">●</span>'
          : '<span style="color:var(--text-3)">○</span>';
        const reason = v.reason ? ' <span style="font-size:11px;color:var(--text-3)">(' + esc(v.reason) + ')</span>' : '';
        const actions = avail
          ? '<span class="act" style="font-size:11px;margin-left:auto" onclick="dpConnectVendor(\'' + esc(v.name) + '\')">连接</span>'
            + '<span class="act" style="font-size:11px;margin-left:4px;color:var(--primary)" onclick="dpFetchVendor(\'' + esc(v.name) + '\')">获取数据</span>'
          : '';
        return '<div class="s-item">'
          + dot + ' '
          + '<span class="s-text">' + label + reason + '</span>'
          + actions
          + '</div>';
      }).join('');
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
    const typeColors = {holding:'var(--green)',nav:'var(--blue)',rating_entity:'var(--orange,#e67e22)',rating_bond:'var(--purple,#9b59b6)',monitoring:'#888',unknown:'var(--text-3)'};
    const typeLabels = {holding:'持仓表',nav:'净值表',rating_entity:'主体评级',rating_bond:'债券评级',monitoring:'监控数据',unknown:'其他'};
    const types = [...new Set(tables.map(t => t.type || 'unknown'))];

    // Filter bar
    const filterHtml = '<div class="dp-filter-bar">'
      + '<span class="dp-filter-chip dp-fc-active" data-type="" onclick="dpFilterType(this,\'\')">全部 ' + tables.length + '</span>'
      + types.map(tp => '<span class="dp-filter-chip" data-type="' + tp + '" onclick="dpFilterType(this,\'' + tp + '\')">'
          + esc(typeLabels[tp] || tp) + ' ' + tables.filter(t => (t.type || 'unknown') === tp).length
          + '</span>').join('')
      + '</div>';

    // Compact table rows
    const rowsHtml = '<div class="dp-compact-table">'
      + '<div class="dp-ct-head"><span>表名</span><span>类型</span><span>行数</span><span>日期</span><span style="text-align:right">操作</span></div>'
      + '<div id="dpTableRows">'
      + tables.map(t => {
          const tp = t.type || 'unknown';
          const color = typeColors[tp] || 'var(--text-3)';
          const label = typeLabels[tp] || tp;
          const date = t.date_tag ? t.date_tag.replace(/^\d{4}/, '').replace(/^-?/, '') : '—';
          return '<div class="dp-ct-row" data-type="' + tp + '">'
            + '<span class="dp-ct-name" title="' + esc(t.name) + '">'
            + '<span class="dp-tc-dot" style="background:' + color + ';width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:5px;flex-shrink:0"></span>'
            + esc(t.name) + '</span>'
            + '<span><span class="dp-type-tag" style="color:' + color + ';background:' + color + '1a">' + esc(label) + '</span></span>'
            + '<span style="color:var(--text-3)">' + t.rows.toLocaleString() + '</span>'
            + '<span style="color:var(--text-3)">' + esc(date) + '</span>'
            + '<span style="display:flex;gap:4px;justify-content:flex-end">'
            + '<button class="dp-btn" onclick="openProfile(\'' + esc(t.name) + '\')">剖析</button>'
            + '<button class="dp-btn dp-btn-del" onclick="deleteTable(\'' + esc(t.name) + '\')">移除</button>'
            + '</span>'
            + '</div>';
        }).join('')
      + '</div></div>';

    container.innerHTML = filterHtml + rowsHtml;
  }
};

function dpTriggerUpload() {
  $('fileInput').click();
}

function dpRefreshTableList() {
  loadTables().then(() => DataPage._renderTableList());
}

function dpFilterType(chip, type) {
  document.querySelectorAll('.dp-filter-chip').forEach(c => c.classList.remove('dp-fc-active'));
  chip.classList.add('dp-fc-active');
  document.querySelectorAll('.dp-ct-row').forEach(row => {
    row.style.display = (!type || row.dataset.type === type) ? '' : 'none';
  });
}

async function dpLoadAllWorkdir() {
  const btn = document.querySelector('button[onclick="dpLoadAllWorkdir()"]');
  const status = $('wdBatchStatus');
  if (btn) { btn.disabled = true; btn.textContent = '加载中…'; }
  if (status) status.textContent = '';
  try {
    const d = await api('POST', '/api/workdir/load_all', {});
    if (!d.ok) {
      if (status) status.textContent = '失败：' + (d.error || '');
      if (btn) { btn.disabled = false; btn.textContent = '全部加载'; }
      return;
    }
    const msg = '完成：' + d.success + ' 成功'
      + (d.skipped ? ' / ' + d.skipped + ' 已跳过' : '')
      + (d.failed ? ' / ' + d.failed + ' 失败' : '');
    if (status) status.textContent = msg;
    if (btn) { btn.disabled = false; btn.textContent = '全部加载'; }
    loadTables().then(() => { DataPage._renderTableList(); DataPage._loadWorkdir(); });
  } catch (e) {
    if (status) status.textContent = '请求失败';
    if (btn) { btn.disabled = false; btn.textContent = '全部加载'; }
  }
}

function dpRefreshWorkdir() {
  DataPage._loadWorkdir();
}

function dpRefreshRemoteDB() {
  DataPage._loadRemoteDB();
}

// --- Remote DB dialog functions ---

let _rdbEditMode = false;

function dpOnDBTypeChange() {
  const t = $('rdbType').value;
  const hostRow = $('rdbHostRow');
  const authRow = $('rdbAuthRow');
  if (t === 'sqlite') {
    if (hostRow) hostRow.style.display = 'none';
    if (authRow) authRow.style.display = 'none';
  } else {
    if (hostRow) hostRow.style.display = 'flex';
    if (authRow) authRow.style.display = 'flex';
  }
}

function dpShowAddConnection() {
  _rdbEditMode = false;
  $('remoteDBDialogTitle').textContent = '添加远程数据库连接';
  $('rdbName').value = '';
  $('rdbType').value = 'mysql';
  $('rdbHost').value = '';
  $('rdbPort').value = '';
  $('rdbDatabase').value = '';
  $('rdbUsername').value = '';
  $('rdbPassword').value = '';
  $('rdbSchema').value = '';
  $('rdbTestResult').textContent = '';
  $('rdbName').disabled = false;
  dpOnDBTypeChange();
  $('remoteDBOverlay').style.display = 'flex';
}

function dpEditConnection(name) {
  _rdbEditMode = true;
  $('remoteDBDialogTitle').textContent = '编辑连接：' + name;
  api('GET', '/api/datasource/connections').then(d => {
    const c = (d.connections || []).find(x => x.name === name);
    if (!c) return;
    $('rdbName').value = c.name;
    $('rdbName').disabled = true;
    $('rdbType').value = c.db_type;
    $('rdbHost').value = c.host || '';
    $('rdbPort').value = c.port || '';
    $('rdbDatabase').value = c.database || '';
    $('rdbUsername').value = '';
    $('rdbPassword').value = '';
    $('rdbSchema').value = '';
    $('rdbTestResult').textContent = '';
    dpOnDBTypeChange();
    $('remoteDBOverlay').style.display = 'flex';
  });
}

function dpCloseRemoteDBDialog() {
  $('remoteDBOverlay').style.display = 'none';
}

async function dpTestRemoteDB() {
  const el = $('rdbTestResult');
  el.textContent = '测试中…';
  el.style.color = 'var(--text-2)';
  try {
    const d = await api('POST', '/api/datasource/test', _rdbFormData());
    if (d.ok) {
      el.textContent = '连接成功';
      el.style.color = 'var(--green)';
    } else {
      el.textContent = '连接失败：' + (d.error || '未知错误');
      el.style.color = 'var(--red,#e74c3c)';
    }
  } catch (e) {
    el.textContent = '测试异常：' + e.message;
    el.style.color = 'var(--red,#e74c3c)';
  }
}

async function dpSaveRemoteDB() {
  const data = _rdbFormData();
  if (!data.name) { toast('连接名称不能为空', 'error'); return; }
  try {
    const d = await api('POST', '/api/datasource/save', data);
    if (d.ok) {
      toast('连接已保存', 'success');
      dpCloseRemoteDBDialog();
      DataPage._loadRemoteDB();
    } else {
      toast('保存失败：' + (d.error || ''), 'error');
    }
  } catch (e) {
    toast('保存异常：' + e.message, 'error');
  }
}

async function dpDeleteConnection(name) {
  if (!confirm('确定删除连接「' + name + '」？')) return;
  try {
    const d = await api('DELETE', '/api/datasource/connection/' + encodeURIComponent(name));
    if (d.ok) {
      toast('已删除', 'success');
      DataPage._loadRemoteDB();
    } else {
      toast('删除失败：' + (d.error || ''), 'error');
    }
  } catch (e) {
    toast('删除异常', 'error');
  }
}

function _rdbFormData() {
  return {
    name: ($('rdbName') || {}).value || '',
    db_type: ($('rdbType') || {}).value || 'mysql',
    host: ($('rdbHost') || {}).value || '',
    port: parseInt(($('rdbPort') || {}).value) || 0,
    database: ($('rdbDatabase') || {}).value || '',
    username: ($('rdbUsername') || {}).value || '',
    password: ($('rdbPassword') || {}).value || '',
    default_schema: ($('rdbSchema') || {}).value || '',
  };
}

// --- Remote table browser ---

async function dpBrowseRemoteTables(connName) {
  $('remoteDBTablesTitle').textContent = '浏览：' + connName;
  const list = $('remoteDBTablesList');
  list.innerHTML = '<div style="color:var(--text-3);padding:12px">加载中…</div>';
  $('remoteDBPreview').style.display = 'none';
  $('remoteDBTablesOverlay').style.display = 'flex';
  try {
    const d = await api('GET', '/api/datasource/tables?conn=' + encodeURIComponent(connName));
    if (!d.ok) {
      list.innerHTML = '<div style="color:var(--red,#e74c3c);padding:12px">' + esc(d.error) + '</div>';
      return;
    }
    const tables = d.tables || [];
    if (!tables.length) {
      list.innerHTML = '<div style="color:var(--text-3);padding:12px">无可用表</div>';
      return;
    }
    list.innerHTML = tables.map(t =>
      '<div class="s-item">'
      + '<span class="s-text">' + esc(t.name) + '</span>'
      + '<span class="act" style="font-size:11px;margin-left:auto" onclick="dpPreviewRemoteTable(\'' + esc(connName) + '\',\'' + esc(t.name) + '\')">预览</span>'
      + '<span class="act" style="font-size:11px;margin-left:4px;color:var(--primary)" onclick="dpImportRemoteTable(\'' + esc(connName) + '\',\'' + esc(t.name) + '\')">导入</span>'
      + '</div>'
    ).join('');
  } catch (e) {
    list.innerHTML = '<div style="color:var(--red,#e74c3c);padding:12px">请求失败</div>';
  }
}

async function dpPreviewRemoteTable(conn, table) {
  const prev = $('remoteDBPreview');
  prev.innerHTML = '<div style="color:var(--text-3)">加载预览…</div>';
  prev.style.display = 'block';
  try {
    const d = await api('POST', '/api/datasource/preview', {conn, table, limit: 5});
    if (!d.ok) {
      prev.innerHTML = '<div style="color:var(--red,#e74c3c)">' + esc(d.error) + '</div>';
      return;
    }
    const cols = d.columns || [];
    const rows = d.preview_rows || [];
    let th = '<tr>' + cols.map(c => '<th>' + esc(c) + '</th>').join('') + '</tr>';
    let tbody = rows.map(r => '<tr>' + r.map(v => '<td>' + esc(String(v == null ? '' : v)) + '</td>').join('') + '</tr>').join('');
    prev.innerHTML = '<div style="font-size:12px;color:var(--text-2);margin-bottom:4px">'
      + d.row_count + ' 行 × ' + d.col_count + ' 列（' + d.query_time_ms + 'ms）</div>'
      + '<div style="overflow-x:auto"><table class="preview-tbl"><thead>' + th + '</thead><tbody>' + tbody + '</tbody></table></div>';
  } catch (e) {
    prev.innerHTML = '<div style="color:var(--red,#e74c3c)">预览失败</div>';
  }
}

async function dpImportRemoteTable(conn, table) {
  const tableName = prompt('请输入本地表名：', 'remote_' + table.replace(/[^a-zA-Z0-9_]/g, '_'));
  if (!tableName) return;
  const tableType = prompt('表类型（holding/nav/rating_entity/rating_bond/unknown）：', 'unknown');
  toast('正在导入…', '');
  try {
    const d = await api('POST', '/api/datasource/import', {
      conn, table, table_name: tableName, table_type: tableType || 'unknown'
    });
    if (d.ok) {
      toast('已导入：' + d.table_name + '（' + d.row_count + '行）', 'success');
      dpCloseTablesBrowser();
      dpRefreshTableList();
    } else {
      toast('导入失败：' + (d.error || ''), 'error');
    }
  } catch (e) {
    toast('导入异常', 'error');
  }
}

function dpCloseTablesBrowser() {
  $('remoteDBTablesOverlay').style.display = 'none';
}

// --- Vendor API functions ---

function dpRefreshVendorAPI() {
  DataPage._loadVendorAPI();
}

async function dpConnectVendor(vendor) {
  toast('正在连接 ' + vendor + '…', '');
  try {
    const d = await api('POST', '/api/vendor/connect', {vendor});
    if (d.ok) {
      toast('已连接 ' + vendor, 'success');
      DataPage._loadVendorAPI();
    } else {
      toast('连接失败：' + (d.error || ''), 'error');
    }
  } catch (e) {
    toast('连接异常：' + e.message, 'error');
  }
}

let _vfVendor = '';

function dpFetchVendor(vendor) {
  _vfVendor = vendor;
  const nameLabels = {choice:'Choice',ifind:'iFinD',wind:'Wind'};
  $('vendorFetchTitle').textContent = '获取数据 — ' + (nameLabels[vendor] || vendor);
  $('vfCodes').value = '';
  $('vfFields').value = '';
  $('vfStart').value = '';
  $('vfEnd').value = '';
  $('vfTableName').value = 'vendor_' + vendor;
  $('vfResult').textContent = '';
  $('vendorFetchOverlay').style.display = 'flex';
}

function dpCloseVendorFetch() {
  $('vendorFetchOverlay').style.display = 'none';
}

async function dpImportVendorData() {
  const codes = $('vfCodes').value.trim();
  const fields = $('vfFields').value.trim();
  const startDate = $('vfStart').value.trim();
  const endDate = $('vfEnd').value.trim();
  const tableName = $('vfTableName').value.trim();
  if (!codes) { toast('请输入证券代码', 'error'); return; }
  if (!fields) { toast('请输入字段名', 'error'); return; }
  const el = $('vfResult');
  el.textContent = '获取中…';
  el.style.color = 'var(--text-2)';
  try {
    const d = await api('POST', '/api/vendor/import', {
      vendor: _vfVendor,
      codes: codes.split(/[,，]/).map(s => s.trim()).filter(Boolean),
      fields: fields.split(/[,，]/).map(s => s.trim()).filter(Boolean),
      start_date: startDate,
      end_date: endDate,
      table_name: tableName || 'vendor_' + _vfVendor
    });
    if (d.ok) {
      el.textContent = '导入成功：' + d.table_name + '（' + d.row_count + '行）';
      el.style.color = 'var(--green)';
      toast('已导入：' + d.table_name, 'success');
      dpCloseVendorFetch();
      dpRefreshTableList();
    } else {
      el.textContent = '失败：' + (d.error || '未知错误');
      el.style.color = 'var(--red,#e74c3c)';
    }
  } catch (e) {
    el.textContent = '异常：' + e.message;
    el.style.color = 'var(--red,#e74c3c)';
  }
}
