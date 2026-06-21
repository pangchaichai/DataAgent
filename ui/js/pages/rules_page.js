// rules_page.js — Analysis rules page lifecycle (Skills + Groups)

const RulesPage = {
  onEnter() {
    this._renderSkills();
    this._renderGroups();
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
  },

  async _renderGroups() {
    const container = $('rulesPageGroupList');
    if (!container) return;
    try {
      const r = await fetch('/api/groups');
      if (!r.ok) return;
      const d = await r.json();
      const groups = d.groups || {};
      const entries = Object.entries(groups);
      if (!entries.length) {
        container.innerHTML = '<div class="rp-empty">暂无集团系。点击「新建集团系」创建。</div>';
        return;
      }
      container.innerHTML = entries.map(([name, members]) => {
        const ms = (members || []).map(m => '<span class="rp-member-tag">' + esc(m) + '</span>').join('');
        return '<div class="rp-group-card">'
          + '<div class="rp-gc-header">'
          + '<span class="rp-gc-name">' + esc(name) + '</span>'
          + '<span class="rp-gc-cnt">' + (members || []).length + '家</span>'
          + '</div>'
          + (ms ? '<div class="rp-gc-members">' + ms + '</div>' : '')
          + '</div>';
      }).join('');
    } catch (e) {
      container.innerHTML = '<div class="rp-empty">加载失败</div>';
    }
  }
};
