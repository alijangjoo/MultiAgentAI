window.Dashboard = window.Dashboard || {};

Dashboard.API = window.location.origin;

Dashboard.escapeHtml = function(text) {
  const d = document.createElement('div');
  d.textContent = text || '';
  return d.innerHTML;
};

Dashboard.NAV_ITEMS = [
  { href: '/', label: 'Home', page: 'home' },
  { href: '/dashboard/develop', label: 'Develop', page: 'develop' },
  { href: '/dashboard/review', label: 'Review', page: 'review' },
  { href: '/dashboard/qa', label: 'QA Agent', page: 'qa' },
  { href: '/dashboard/pipelines', label: 'Pipelines', page: 'pipelines' },
  { href: '/dashboard/deploy-requests', label: 'Deploy Request', page: 'deploy-requests' },
  { href: '/dashboard/channel-alerts', label: 'Disaster & Bugs', page: 'channel-alerts' },
  { href: '/dashboard/jira-reporter', label: 'Jira Reporter Agent', page: 'jira-reporter' },
  { href: '/dashboard/knowledge', label: 'Knowledge Agent', page: 'knowledge' },
  { href: '/dashboard/rtk', label: 'RTK Savings', page: 'rtk' },
];

Dashboard.SETTINGS_NAV = [
  { href: '/dashboard/settings/agents', label: 'Agent Executors', page: 'settings-agents' },
  { href: '/dashboard/settings/deploy', label: 'Deploy Branches', page: 'settings-deploy' },
];

Dashboard.renderHeader = function(title, subtitle, activePage) {
  const mainLinks = Dashboard.NAV_ITEMS.map(item =>
    `<a href="${item.href}" class="${item.page === activePage ? 'active' : ''}">${item.label}</a>`
  ).join('');
  const settingsActive = Dashboard.SETTINGS_NAV.some(item => item.page === activePage);
  const settingsLinks = Dashboard.SETTINGS_NAV.map(item =>
    `<a href="${item.href}" class="${item.page === activePage ? 'active' : ''}">${item.label}</a>`
  ).join('');

  return `
    <header class="app-header">
      <div class="header-top">
        <div>
          <h1><span>Agent</span>Framework</h1>
          <div class="header-sub">${Dashboard.escapeHtml(subtitle || title)}</div>
        </div>
        <div style="display:flex;align-items:center;gap:0.75rem">
          <span class="status-dot disconnected" id="ws-status"></span>
          <span id="ws-label" style="font-size:0.82rem;color:var(--muted)">Connecting...</span>
        </div>
      </div>
      <nav class="app-nav">
        ${mainLinks}
        <div class="nav-dropdown${settingsActive ? ' open' : ''}" id="nav-settings">
          <button type="button" class="nav-dropdown-toggle${settingsActive ? ' active' : ''}"
                  aria-expanded="${settingsActive ? 'true' : 'false'}" aria-haspopup="true">
            Settings <span class="nav-caret">▾</span>
          </button>
          <div class="nav-dropdown-menu" role="menu">${settingsLinks}</div>
        </div>
      </nav>
    </header>`;
};

Dashboard.toggleSettingsMenu = function(event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  const dd = document.getElementById('nav-settings');
  if (!dd) return;
  const open = dd.classList.toggle('open');
  const btn = dd.querySelector('.nav-dropdown-toggle');
  if (btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
};

Dashboard.initNav = function() {
  if (Dashboard._navInitialized) return;
  Dashboard._navInitialized = true;

  document.addEventListener('click', (event) => {
    const dd = document.getElementById('nav-settings');
    if (!dd) return;
    const toggle = dd.querySelector('.nav-dropdown-toggle');
    if (toggle && toggle.contains(event.target)) {
      Dashboard.toggleSettingsMenu(event);
      return;
    }
    if (!dd.contains(event.target)) {
      dd.classList.remove('open');
      if (toggle) toggle.setAttribute('aria-expanded', 'false');
    }
  });
};

Dashboard.mountHeader = function(containerId, title, subtitle, activePage) {
  const el = document.getElementById(containerId);
  if (el) el.innerHTML = Dashboard.renderHeader(title, subtitle, activePage);
  Dashboard.initNav();
};

Dashboard.connectWebSocket = function(onMessage) {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${window.location.host}/ws/dashboard`);
  ws.onopen = () => {
    const dot = document.getElementById('ws-status');
    const label = document.getElementById('ws-label');
    if (dot) dot.className = 'status-dot connected';
    if (label) label.textContent = 'Live';
  };
  ws.onclose = () => {
    const dot = document.getElementById('ws-status');
    const label = document.getElementById('ws-label');
    if (dot) dot.className = 'status-dot disconnected';
    if (label) label.textContent = 'Reconnecting...';
    setTimeout(() => Dashboard.connectWebSocket(onMessage), 3000);
  };
  ws.onmessage = (event) => {
    if (onMessage) {
      try { onMessage(JSON.parse(event.data)); } catch (_) {}
    }
  };
  return ws;
};

Dashboard.statusBadgeClass = function(status) {
  const s = (status || '').toLowerCase();
  if (s.includes('progress') || s === 'running') return 'progress';
  if (s === 'done' || s === 'success' || s === 'completed') return 'done';
  if (s === 'failed') return 'failed';
  if (s === 'manual' || s === 'pending') return 'pending';
  return 'todo';
};