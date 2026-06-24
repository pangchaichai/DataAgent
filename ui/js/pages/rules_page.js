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
        container.innerHTML = '<div class="rp-empty">暂无可用技能</div>';
        return;
      }
      container.innerHTML = skills.map(s => {
        const readyCls = s.ready ? 'skill-ready' : 'skill-missing';
        const readyLabel = s.ready ? '就绪' : '缺数据';
        const desc = (s.description || '').slice(0, 100) + (s.description && s.description.length > 100 ? '…' : '');
        return '<div class="rp-skill-card">'
          + '<div class="rp-sc-header">'
          + '<span class="rp-sc-name">' + esc(s.name) + '</span>'
          + '<span class="skill-badge ' + readyCls + '">' + readyLabel + '</span>'
          + '</div>'
          + (desc ? '<div class="rp-sc-desc">' + esc(desc) + '</div>' : '')
          + (s.ready
            ? '<div class="rp-sc-actions"><button class="dp-btn" onclick="executeSkill(\'' + esc(s.name) + '\')">执行</button></div>'
            : '<div class="rp-sc-actions"><span class="skill-hint">缺：' + esc((s.missing_files || []).slice(0, 2).join('、')) + '</span></div>')
          + '</div>';
      }).join('');
    } catch (e) {
      container.innerHTML = '<div class="rp-empty">加载失败</div>';
    }
  }
};
