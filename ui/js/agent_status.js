// agent_status.js — DA 小猫头鹰任务进度动画

const AgentStatus = (function () {
  let _bar = null;
  let _owlEl = null;
  let _mode = 'idle'; // idle|thinking|planned|executing|simple|waiting|done
  let _steps = [];
  let _hasError = false;
  let _hasWarn = false;
  let _retryCount = 0;
  let _taskStart = null;
  let _dismissTimer = null;
  let _tickTimer = null;

  // ── SVG 猫头鹰（内联，无外部依赖）──────────────────────────
  function _owlSVG() {
    return `<svg class="da-owl" viewBox="0 0 40 48" width="36" height="44"
        xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <!-- 耳羽 -->
      <ellipse cx="12" cy="8" rx="5" ry="7.5" fill="var(--owl-body)" transform="rotate(-18 12 8)"/>
      <ellipse cx="28" cy="8" rx="5" ry="7.5" fill="var(--owl-body)" transform="rotate(18 28 8)"/>
      <!-- 头部 -->
      <ellipse cx="20" cy="17" rx="14" ry="13" fill="var(--owl-body)"/>
      <!-- 身体 -->
      <ellipse cx="20" cy="36" rx="12" ry="11" fill="var(--owl-body)"/>
      <!-- 腹部浅色 -->
      <ellipse cx="20" cy="37" rx="8" ry="8.5" fill="var(--owl-belly)"/>
      <!-- 眼白 -->
      <circle cx="13.5" cy="17" r="6.2" fill="white"/>
      <circle cx="26.5" cy="17" r="6.2" fill="white"/>
      <!-- 瞳孔 -->
      <circle class="owl-pl" cx="13.5" cy="17" r="3.3" fill="#1C2024"/>
      <circle class="owl-pr" cx="26.5" cy="17" r="3.3" fill="#1C2024"/>
      <!-- 瞳孔高光 -->
      <circle cx="14.5" cy="15.2" r="1.1" fill="white" opacity="0.75"/>
      <circle cx="27.5" cy="15.2" r="1.1" fill="white" opacity="0.75"/>
      <!-- 金属框眼镜 -->
      <rect x="7.5" y="11" width="11.5" height="12" rx="5.5" fill="none"
            stroke="var(--owl-glasses)" stroke-width="1.6"/>
      <rect x="21" y="11" width="11.5" height="12" rx="5.5" fill="none"
            stroke="var(--owl-glasses)" stroke-width="1.6"/>
      <line x1="19" y1="16.5" x2="21" y2="16.5"
            stroke="var(--owl-glasses)" stroke-width="1.6"/>
      <!-- 喙 -->
      <polygon points="17.5,22.5 22.5,22.5 20,27" fill="#f59e0b"/>
      <!-- 领结 -->
      <polygon class="owl-tie" points="16.5,30.5 20,27.5 23.5,30.5 20,33.5" fill="var(--blue)"/>
      <!-- 翅膀 -->
      <ellipse cx="8" cy="38" rx="4.5" ry="8.5" fill="var(--owl-wing)"
               transform="rotate(-22 8 38)"/>
      <ellipse cx="32" cy="38" rx="4.5" ry="8.5" fill="var(--owl-wing)"
               transform="rotate(22 32 38)"/>
    </svg>`;
  }

  // ── 工具函数 ─────────────────────────────────────────────────
  function _elapsed() {
    if (!_taskStart) return '';
    return ((Date.now() - _taskStart) / 1000).toFixed(1) + 's';
  }

  function _showBar(height) {
    if (!_bar) return;
    _bar.style.setProperty('--asb-h', (height || 62) + 'px');
    _bar.classList.remove('asb-hidden');
    _bar.classList.add('asb-visible');
  }

  function _hideBar() {
    if (!_bar) return;
    _bar.classList.add('asb-hiding');
    setTimeout(() => {
      _bar.classList.remove('asb-visible', 'asb-hiding');
      _bar.classList.add('asb-hidden');
      _bar.innerHTML = '';
    }, 300);
  }

  function _setOwlState(state) {
    if (_owlEl) _owlEl.className = 'da-owl owl-' + state;
  }

  function _stopTick() {
    clearInterval(_tickTimer);
    _tickTimer = null;
  }

  function _startTick() {
    _stopTick();
    _tickTimer = setInterval(() => {
      const el = _bar && _bar.querySelector('.asb-elapsed');
      if (el) el.textContent = _elapsed();
    }, 500);
  }

  // ── 渲染函数 ─────────────────────────────────────────────────
  function _renderThinking() {
    _bar.innerHTML =
      '<div class="asb-row asb-thinking">'
      + '<div class="asb-owl-wrap">' + _owlSVG() + '</div>'
      + '<div class="asb-info">'
      + '<div class="asb-label">DA 正在理解需求并规划任务…</div>'
      + '<div class="asb-sublabel" id="asb-think-sub"></div>'
      + '</div>'
      + '<div class="asb-dots"><span></span><span></span><span></span></div>'
      + '</div>';
    _owlEl = _bar.querySelector('.da-owl');
    _setOwlState('thinking');
  }

  function _renderPlanTimeline(steps) {
    let timeline = '';
    steps.forEach((s, i) => {
      timeline += '<div class="asb-step pending" id="asb-s-' + s.id + '" data-idx="' + i + '">'
        + '<div class="asb-step-dot"><span class="asb-dot-num">' + (i + 1) + '</span></div>'
        + '<div class="asb-step-name">' + esc((s.name || '').slice(0, 10)) + '</div>'
        + '</div>';
      if (i < steps.length - 1)
        timeline += '<div class="asb-step-line" id="asb-ln-' + i + '"></div>';
    });
    _bar.innerHTML =
      '<div class="asb-top-row">'
      + '<span class="asb-mode-tag">规划 ' + steps.length + ' 步</span>'
      + '<span class="asb-cur-step" id="asb-cur-step">准备开始…</span>'
      + '<span class="asb-elapsed" id="asb-elapsed">' + _elapsed() + '</span>'
      + '</div>'
      + '<div class="asb-timeline-wrap">'
      + '<div class="asb-owl-slide" id="asb-owl-slide">' + _owlSVG() + '</div>'
      + '<div class="asb-timeline">' + timeline + '</div>'
      + '</div>';
    _owlEl = _bar.querySelector('.da-owl');
    _setOwlState('thinking');
    _startTick();
  }

  function _renderSimple(label) {
    _bar.innerHTML =
      '<div class="asb-row">'
      + '<div class="asb-owl-wrap">' + _owlSVG() + '</div>'
      + '<div class="asb-info">'
      + '<div class="asb-label" id="asb-simple-lbl">' + esc(label || '正在执行…') + '</div>'
      + '<div class="asb-sublabel">DA 正在处理您的请求</div>'
      + '</div>'
      + '<div class="asb-dots"><span></span><span></span><span></span></div>'
      + '</div>';
    _owlEl = _bar.querySelector('.da-owl');
    _setOwlState('working');
  }

  function _renderWaiting(msg) {
    _bar.innerHTML =
      '<div class="asb-row asb-waiting">'
      + '<div class="asb-owl-wrap">' + _owlSVG() + '</div>'
      + '<div class="asb-info">'
      + '<div class="asb-label">' + esc(msg || 'DA 需要您的指令') + '</div>'
      + '<div class="asb-sublabel">请在上方查看并操作</div>'
      + '</div>'
      + '<div class="asb-pulse-ring"></div>'
      + '</div>';
    _owlEl = _bar.querySelector('.da-owl');
    _setOwlState('waiting');
  }

  const _DONE = {
    success: { cls: 'green',  icon: '✓', title: '顺利完成！',       owl: 'success', sub: () => '全部步骤执行成功，用时 ' + _elapsed() },
    hard:    { cls: 'orange', icon: '≈', title: '艰难完成',          owl: 'hard',    sub: () => '自动重试 ' + _retryCount + ' 次后完成，建议核查结果' },
    partial: { cls: 'yellow', icon: '?', title: '部分完成',          owl: 'partial', sub: () => '部分步骤未按预期执行，请核查输出结果' },
    failed:  { cls: 'red',    icon: '✗', title: '执行中断',          owl: 'failed',  sub: (e) => e || '请修改问题或检查数据后重试' },
    stopped: { cls: 'grey',   icon: '⏸', title: '已停止',            owl: 'stopped', sub: () => '任务已由您中断' },
  };

  function _renderDone(quality, extra) {
    _stopTick();
    const c = _DONE[quality] || _DONE.success;
    _bar.innerHTML =
      '<div class="asb-row asb-done asb-done-' + c.cls + '">'
      + '<div class="asb-owl-wrap">' + _owlSVG() + '</div>'
      + '<div class="asb-info">'
      + '<div class="asb-label"><span class="asb-done-icon">' + c.icon + '</span> ' + c.title + '</div>'
      + '<div class="asb-sublabel">' + esc(c.sub(extra || '')) + '</div>'
      + '</div>'
      + '<button class="asb-close" onclick="AgentStatus.dismiss()" title="关闭">✕</button>'
      + '</div>';
    _owlEl = _bar.querySelector('.da-owl');
    _setOwlState(c.owl);
  }

  function _moveOwlToStep(idx) {
    const slide = _bar && _bar.querySelector('#asb-owl-slide');
    const steps = _bar && _bar.querySelectorAll('.asb-step');
    if (!slide || !steps || !steps[idx]) return;
    const sRect = steps[idx].getBoundingClientRect();
    const wRect = _bar.querySelector('.asb-timeline-wrap').getBoundingClientRect();
    const target = sRect.left - wRect.left + sRect.width / 2 - 18;
    slide.style.left = Math.max(0, target) + 'px';
    slide.classList.remove('asb-jump');
    void slide.offsetWidth; // force reflow
    slide.classList.add('asb-jump');
    setTimeout(() => slide.classList.remove('asb-jump'), 560);
  }

  function _updateStep(stepId, status) {
    const el = _bar && _bar.querySelector('#asb-s-' + stepId);
    if (!el) return;
    el.className = 'asb-step ' + status;
    const num = el.querySelector('.asb-dot-num');
    if (num) {
      num.textContent = status === 'done' ? '✓' : status === 'failed' ? '✗' : status === 'running' ? '↻' : el.dataset.idx ? +el.dataset.idx + 1 : '·';
    }
    if (status === 'done') {
      const lineIdx = parseInt(el.dataset.idx || '0') - 1;
      const ln = _bar.querySelector('#asb-ln-' + lineIdx);
      if (ln) ln.classList.add('done');
    }
  }

  function _reset() {
    clearTimeout(_dismissTimer);
    _stopTick();
    _steps = [];
    _hasError = false;
    _hasWarn = false;
    _retryCount = 0;
    _taskStart = null;
    _owlEl = null;
    _mode = 'idle';
    if (_bar) _bar.innerHTML = '';
  }

  // ── 公开 API ─────────────────────────────────────────────────
  return {
    init() {
      _bar = document.getElementById('agentStatusBar');
    },

    // 用户发消息时调用（sendMessage 中）
    onNewMessage() {
      if (!_bar) return;
      _reset();
      _mode = 'thinking';
      _taskStart = Date.now();
      _renderThinking();
      _showBar(62);
    },

    // SSE: thinking
    onThinking(text) {
      if (!_bar || _mode !== 'thinking') return;
      const el = _bar.querySelector('#asb-think-sub');
      if (el) el.textContent = (text || '').slice(0, 55);
    },

    // SSE: plan（规划出来了，展示时间轴）
    onPlan(data) {
      if (!_bar) return;
      const steps = data.steps || [];
      _steps = steps.map(s => ({ ...s, status: 'pending' }));
      _mode = 'planned';
      _renderPlanTimeline(_steps);
      _showBar(104);
      setTimeout(() => _moveOwlToStep(0), 120);
    },

    // SSE: plan_step（某步开始/完成/失败）
    onPlanStep(stepId, status, name) {
      if (!_bar) return;
      const step = _steps.find(s => String(s.id) === String(stepId));
      if (step) step.status = status;
      _updateStep(stepId, status);
      if (status === 'running') {
        _mode = 'executing';
        const idx = _steps.findIndex(s => String(s.id) === String(stepId));
        if (idx >= 0) _moveOwlToStep(idx);
        _setOwlState('working');
        const cur = _bar.querySelector('#asb-cur-step');
        if (cur) cur.textContent = name || step?.name || '执行中…';
      }
      if (status === 'failed') _hasWarn = true;
    },

    // SSE: tool_start（无规划时的简单任务）
    onToolStart(tool, label) {
      if (!_bar) return;
      if (_mode === 'planned' || _mode === 'executing') return;
      if (_mode !== 'simple') {
        _mode = 'simple';
        _renderSimple(label || tool);
        _showBar(62);
      } else {
        const lbl = _bar.querySelector('#asb-simple-lbl');
        if (lbl) lbl.textContent = label || tool;
        _setOwlState('working');
      }
    },

    // SSE: tool_end
    onToolEnd(success) {
      if (!success) { _hasWarn = true; _retryCount++; }
    },

    // SSE: error
    onError(msg) {
      if (!_bar) return;
      _hasError = true;
      _mode = 'done';
      _stopTick();
      _renderDone('failed', (msg || '').slice(0, 55));
      _showBar(62);
    },

    // SSE: confirm
    onConfirm() {
      if (!_bar) return;
      _mode = 'waiting';
      _stopTick();
      _renderWaiting('DA 需要您确认计算结果');
      _showBar(62);
    },

    // SSE: ask
    onAsk(question) {
      if (!_bar) return;
      _mode = 'waiting';
      _stopTick();
      _renderWaiting('DA 需要您选择：' + (question || '').slice(0, 38));
      _showBar(62);
    },

    // SSE: stream_end（流正常结束）
    onStreamEnd() {
      if (!_bar) return;
      if (_mode === 'waiting') return; // 保持等待状态
      const q = this._quality();
      _stopTick();
      _renderDone(q);
      _showBar(62);
      if (q === 'success') {
        _dismissTimer = setTimeout(() => this.dismiss(), 5000);
      }
    },

    // 用户点停止
    onStop() {
      if (!_bar) return;
      _mode = 'done';
      _stopTick();
      _renderDone('stopped');
      _showBar(62);
      _dismissTimer = setTimeout(() => this.dismiss(), 3000);
    },

    // 用户发送后续消息（等待状态中断后继续）
    onResume() {
      if (_mode === 'waiting') {
        _mode = 'thinking'; // 重新进入思考
        _hasError = false;
      }
    },

    // 手动关闭
    dismiss() {
      clearTimeout(_dismissTimer);
      _hideBar();
      setTimeout(() => _reset(), 350);
    },

    // 评估任务质量
    _quality() {
      if (_hasError) return 'failed';
      if (_retryCount >= 2) return 'hard';
      if (_hasWarn) return 'partial';
      return 'success';
    },
  };
})();
