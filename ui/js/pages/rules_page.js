// rules_page.js — Analysis rules page lifecycle (Skills + Groups)

const RulesPage = {
  onEnter() {
    this._renderSkills();
  },

  async _renderSkills() {
    const container = $('rulesPageSkillList');
    if (!container) return;
    try {
      const d = await api('GET', '/api/skills/status');
      const skills = d.skills || [];
      if (!skills.length) {
        container.innerHTML = '<div class="rp-empty">暂无可用技能 — 可在「创建技能」中新建</div>';
        return;
      }
      container.innerHTML = '<div class="rp-skill-grid">'
        + skills.map(s => {
          const ready = s.ready;
          const readyColor = ready ? 'var(--green)' : 'var(--orange,#e67e22)';
          const readyLabel = ready ? '就绪' : '缺数据';
          const desc = (s.description || '').slice(0, 60) + (s.description && s.description.length > 60 ? '…' : '');
          const missingHint = !ready && s.missing_files && s.missing_files.length
            ? '<div class="rp-sg-missing">缺：' + esc(s.missing_files.slice(0, 1).join('')) + '</div>'
            : '';
          return '<div class="rp-sg-card' + (ready ? '' : ' rp-sg-dim') + '">'
            + '<div class="rp-sg-top">'
            + '<div class="rp-sg-name" title="' + esc(s.name) + '">' + esc(s.name) + '</div>'
            + '<span class="rp-sg-badge" style="color:' + readyColor + ';background:' + readyColor + '1a">' + readyLabel + '</span>'
            + '</div>'
            + (desc ? '<div class="rp-sg-desc">' + esc(desc) + '</div>' : '')
            + missingHint
            + '<div class="rp-sg-foot">'
            + (ready
              ? '<button class="rp-sg-btn" onclick="executeSkill(\'' + esc(s.name) + '\')">▶ 执行</button>'
              : '<button class="rp-sg-btn rp-sg-btn-dim" disabled>未就绪</button>')
            + '</div>'
            + '</div>';
        }).join('')
        + '</div>';
    } catch (e) {
      container.innerHTML = '<div class="rp-empty">加载失败</div>';
    }
  }
};
