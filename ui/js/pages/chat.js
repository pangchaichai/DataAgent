/**
 * Chat Agent page — 3-column layout: sessions | chat | context.
 * Preserves and wraps existing chat/render/agent_status functionality.
 */
const ChatPage = (() => {
  let _chatEl = null;
  let _initialized = false;

  function render(root) {
    root.innerHTML = `
      <div class="flex h-full overflow-hidden">
        <!-- Left: Session History -->
        <aside class="w-72 bg-surface-container-lowest border-r border-surface-container-highest flex-col hidden lg:flex" id="chat-sessions-panel">
          <div class="p-4 border-b border-surface-container-highest flex justify-between items-center">
            <h2 class="text-body-md font-semibold">近期会话</h2>
            <span class="material-symbols-outlined text-outline cursor-pointer text-[20px]" onclick="ChatPage.newChat()">add</span>
          </div>
          <div class="flex-1 overflow-y-auto custom-scrollbar p-3 space-y-1" id="chat-session-list">
            <p class="text-body-sm text-on-surface-variant p-2">加载中...</p>
          </div>
        </aside>

        <!-- Center: Chat -->
        <div class="flex-1 flex flex-col relative bg-surface-bright" id="chat-main-col">
          <!-- Chat area -->
          <div class="flex-1 overflow-y-auto custom-scrollbar" id="chat-outer">
            <div id="chat" class="max-w-4xl mx-auto p-gutter space-y-6">
              <!-- Welcome or messages will be rendered here -->
            </div>
            <button class="fixed bottom-[140px] right-8 w-8 h-8 rounded-full bg-surface-container-lowest border border-outline-variant shadow-md flex items-center justify-center hover:bg-surface-container transition z-20"
                    id="scrollBtn" style="display:none" onclick="scrollBottom()">
              <span class="material-symbols-outlined text-[16px]">keyboard_arrow_down</span>
            </button>
          </div>

          <!-- Agent status bar -->
          <div id="agentStatusBar" class="agent-status-bar asb-hidden"></div>

          <!-- Suggestions -->
          <div id="chat-suggestions" class="px-gutter pb-2" style="display:none">
            <div class="max-w-4xl mx-auto flex flex-wrap gap-2" id="suggestion-pills"></div>
          </div>

          <!-- Input bar -->
          <div class="p-gutter pt-2 bg-surface-bright" id="chat-input-area">
            <div class="max-w-4xl mx-auto">
              <!-- Mention popup -->
              <div id="mention-popup" class="hidden absolute bottom-full mb-1 left-0 bg-surface-container-lowest border border-outline-variant rounded-lg shadow-lg p-2 max-h-48 overflow-y-auto z-30" style="display:none"></div>

              <!-- Hint bar -->
              <div id="hintBar" class="mb-2 text-body-sm text-on-surface-variant" style="display:none"></div>

              <!-- Quick buttons -->
              <div class="flex gap-2 mb-2 flex-wrap" id="quick-btns">
                <button class="suggestion-pill" onclick="document.getElementById('fileInput').click()">
                  <span class="material-symbols-outlined text-[16px]">upload_file</span> 上传
                </button>
                <button class="suggestion-pill" onclick="executeSkill('concentration_monitor')">
                  <span class="material-symbols-outlined text-[16px]">security</span> 合规检查
                </button>
                <button class="suggestion-pill" onclick="executeSkill('fund_nav_report')">
                  <span class="material-symbols-outlined text-[16px]">description</span> 报告
                </button>
              </div>

              <!-- Chat input -->
              <div class="chat-input-wrap">
                <div class="flex items-center px-4 py-2 gap-2 border-b border-surface-container-low">
                  <label class="cursor-pointer">
                    <span class="material-symbols-outlined text-outline text-[18px] hover:text-secondary transition-colors">attach_file</span>
                    <input type="file" id="fileInput" multiple accept=".csv,.xlsx,.xls,.pdf,.docx,.txt" class="hidden"
                           onchange="handleFiles(this.files)">
                  </label>
                  <div class="h-4 w-px bg-outline-variant mx-1"></div>
                  <span class="label-caps text-outline" id="chat-context-label">准备就绪</span>
                </div>
                <div class="flex items-end p-2 pr-4">
                  <textarea id="userInput" rows="1"
                    class="flex-1 border-none focus:ring-0 text-body-md py-3 px-3 bg-transparent resize-none overflow-hidden"
                    placeholder="输入您的问题..."
                    oninput="autoResize(this); checkMention(this)"
                    onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMessage()}"></textarea>
                  <button id="sendBtn" class="mb-1 ml-2 bg-secondary text-on-secondary w-10 h-10 rounded-lg flex items-center justify-center hover:bg-on-secondary-fixed-variant transition-all shadow-md active:scale-95"
                          onclick="sendMessage()">
                    <span class="material-symbols-outlined">send</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Right: Context Panel (≥2xl) -->
        <aside class="w-80 bg-surface-container-lowest border-l border-surface-container-highest hidden 2xl:flex flex-col" id="chat-context-panel">
          <div class="p-4 border-b border-surface-container-highest">
            <h3 class="label-caps text-outline mb-3">意图识别</h3>
            <div class="space-y-2" id="ctx-intents">
              <p class="text-body-sm text-on-surface-variant">等待输入...</p>
            </div>
          </div>
          <div class="flex-1 p-4 overflow-y-auto custom-scrollbar">
            <h3 class="label-caps text-outline mb-3">上下文信息</h3>
            <div id="ctx-info" class="space-y-3">
              <div>
                <div class="label-caps text-outline mb-1">数据状态</div>
                <div class="text-body-sm" id="ctx-data-status">无数据</div>
              </div>
              <div>
                <div class="label-caps text-outline mb-1">LLM 提供商</div>
                <div class="text-body-sm" id="ctx-llm-provider">--</div>
              </div>
            </div>
          </div>
        </aside>
      </div>`;

    _chatEl = document.getElementById('chat');
    _setupScrollDetection();
    _loadSessionList();
    _loadContextInfo();

    if (!_initialized) {
      _initialized = true;
      _showWelcome();
    }
  }

  function _setupScrollDetection() {
    const outer = document.getElementById('chat-outer');
    const btn = document.getElementById('scrollBtn');
    if (outer && btn) {
      outer.addEventListener('scroll', () => {
        const atBottom = outer.scrollHeight - outer.scrollTop - outer.clientHeight < 80;
        btn.style.display = atBottom ? 'none' : 'flex';
      });
    }
  }

  async function _loadSessionList() {
    try {
      const data = await api('GET', '/api/sessions');
      const list = document.getElementById('chat-session-list');
      if (!list) return;
      const sessions = Array.isArray(data) ? data : (data.sessions || []);
      if (!sessions.length) {
        list.innerHTML = '<p class="text-body-sm text-on-surface-variant p-2">暂无历史会话</p>';
        return;
      }
      list.innerHTML = sessions.slice(0, 20).map((s, i) => `
        <div class="p-3 rounded-lg cursor-pointer transition-all hover:bg-surface-container-low ${i === 0 ? 'bg-surface-container-low border border-transparent' : 'border border-transparent'}"
             onclick="loadSes('${esc(s.id)}')">
          <div class="text-body-sm font-medium truncate">${esc(s.title || '新会话')}</div>
          <div class="label-caps text-outline mt-1">${s.updated_at || s.created_at || ''}</div>
        </div>`).join('');
    } catch (e) {
      const list = document.getElementById('chat-session-list');
      if (list) list.innerHTML = '<p class="text-body-sm text-on-surface-variant p-2">加载失败</p>';
    }
  }

  async function _loadContextInfo() {
    try {
      const health = await api('GET', '/api/health').catch(() => null);
      if (health) {
        const el = document.getElementById('ctx-llm-provider');
        if (el) el.textContent = health.provider || health.llm_provider || '--';
        const ds = document.getElementById('ctx-data-status');
        if (ds) ds.textContent = health.tables_loaded ? health.tables_loaded + ' 张表已加载' : '无数据';
      }
    } catch (e) { /* ignore */ }
  }

  function _showWelcome() {
    if (!_chatEl) return;
    _chatEl.innerHTML = `
      <div class="flex flex-col items-center justify-center py-16 text-center">
        <div class="w-16 h-16 bg-primary-container rounded-2xl flex items-center justify-center mb-4">
          <span class="material-symbols-outlined text-on-secondary-container text-[32px]" style="font-variation-settings: 'FILL' 1">neurology</span>
        </div>
        <h2 class="text-headline-md font-semibold mb-2">DataAgent AI</h2>
        <p class="text-body-md text-on-surface-variant mb-8 max-w-md">
          您好！我是 DataAgent 智能分析助手。上传数据文件后，我可以帮您进行数据分析、合规检查和报告生成。
        </p>
        <div class="flex flex-wrap gap-3 justify-center max-w-lg">
          <button class="suggestion-pill" onclick="document.getElementById('fileInput').click()">
            <span class="material-symbols-outlined text-[16px]">upload_file</span> 上传数据文件
          </button>
          <button class="suggestion-pill" onclick="ChatPage.setInput('帮我分析持仓数据')">
            <span class="material-symbols-outlined text-[16px]">query_stats</span> 分析持仓
          </button>
          <button class="suggestion-pill" onclick="ChatPage.setInput('生成运作报告')">
            <span class="material-symbols-outlined text-[16px]">description</span> 生成报告
          </button>
        </div>
      </div>`;
  }

  function newChat() {
    if (typeof resetChat === 'function') {
      resetChat();
    } else {
      api('POST', '/api/reset').then(() => {
        _initialized = false;
        render(document.getElementById('pageRoot'));
      });
    }
  }

  function setInput(text) {
    const input = document.getElementById('userInput');
    if (input) { input.value = text; input.focus(); }
  }

  return { render, newChat, setInput };
})();
