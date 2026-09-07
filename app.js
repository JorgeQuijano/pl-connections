/* Club Connections — pure vanilla, no deps. Reads data/pl-connections.json. */
const DATA_URL = 'data/pl-connections.json';
const state = {
  leagues: [], players: [], league: null, selected: null,
  pos: new Set(), query: '', metric: 'academy',
};
const ROLE_LABEL = { senior: 'First team', academy: 'Academy only', both: 'First team + academy' };
const METRIC_ROLES = { academy: ['academy', 'both'], senior: ['senior', 'both'], any: ['academy', 'senior', 'both'] };
const METRIC_VERB = { academy: 'came through the academy at', senior: 'played first-team football for', any: 'have a connection to' };
const $ = (id) => document.getElementById(id);

function currentLeague() { return state.leagues.find(l => l.key === state.league) || null; }
function currentClubs() { const lg = currentLeague(); return lg ? lg.clubs : []; }
function currentPlayers() {
  return state.league ? state.players.filter(p => p.league === state.league) : state.players;
}

async function init() {
  let data;
  try {
    const r = await fetch(DATA_URL);
    data = await r.json();
  } catch (e) {
    $('league-tabs').innerHTML = '<p class="error">Could not load data/pl-connections.json — serve this folder over HTTP (e.g. <code>python3 -m http.server</code>) or check the file exists.</p>';
    return;
  }
  state.leagues = (data.meta && data.meta.leagues) || [];
  state.players = data.players || [];
  const season = (data.meta && data.meta.season) || '26/27';
  const nClubs = state.leagues.reduce((n, l) => n + l.clubs.length, 0);
  const nPl = state.players.length;
  $('meta').textContent =
    `${nPl} players · ${nClubs} clubs · ${state.leagues.map(l => l.name).join(' / ')} · snapshot ${(data.meta && data.meta.crawledAt || '').slice(0, 10)} · source: Transfermarkt`;
  document.querySelectorAll('#metric .chip').forEach(b => {
    b.onclick = () => {
      state.metric = b.dataset.m;
      document.querySelectorAll('#metric .chip').forEach(x => x.classList.toggle('on', x === b));
      renderOverview();
    };
  });
  if (state.leagues.length) selectLeague(state.leagues[0].key);
}

function renderTabs() {
  const wrap = $('league-tabs');
  wrap.innerHTML = '';
  for (const l of state.leagues) {
    const b = document.createElement('button');
    b.className = 'tab' + (state.league === l.key ? ' on' : '');
    b.textContent = l.name;
    b.setAttribute('role', 'tab');
    b.onclick = () => selectLeague(l.key);
    wrap.appendChild(b);
  }
}

function selectLeague(key) {
  state.league = key;
  state.selected = null;
  state.query = '';
  state.pos.clear();
  $('search').value = '';
  renderTabs();
  $('league-name').textContent = currentLeague().name;
  $('overview-sub').textContent =
    `How many current ${currentLeague().name} players have a connection to each ${currentLeague().name} club, counted across all ${currentLeague().clubs.length} squads.`;
  renderClubs();
  renderPos();
  renderResults();
  renderOverview();
}

function renderClubs() {
  const sel = $('club-select');
  sel.innerHTML = '<option value="">Pick a club…</option>';
  for (const c of currentClubs()) {
    const o = document.createElement('option');
    o.value = c.id;
    o.textContent = `${c.name} (${c.squadSize})`;
    sel.appendChild(o);
  }
  sel.value = state.selected === null ? '' : String(state.selected);
}

function overviewRows() {
  const roles = METRIC_ROLES[state.metric];
  const players = currentPlayers();
  return currentClubs().map(c => {
    let total = 0, home = 0;
    for (const p of players) {
      const inv = (p.involvements || []).find(i => i.club === c.name);
      if (inv && roles.includes(inv.role)) {
        total++;
        if (p.club.name === c.name) home++;
      }
    }
    return { c, total, home, away: total - home };
  }).sort((a, b) => b.total - a.total || a.c.name.localeCompare(b.c.name));
}

function renderOverview() {
  const rows = overviewRows();
  const max = Math.max(1, rows[0].total);
  const chart = $('chart');
  chart.innerHTML = rows.map(r => {
    const homePct = (r.home / max) * 100;
    const awayPct = (r.away / max) * 100;
    return `
    <div class="bar-row" data-id="${r.c.id}" role="button" tabindex="0" title="${r.c.name}: ${r.total} player${r.total === 1 ? '' : 's'} (${r.home} still there, ${r.away} elsewhere)">
      <span class="bar-club">${r.c.name}</span>
      <span class="bar-track">
        ${r.total ? `<i class="bar home" style="width:${homePct}%"></i><i class="bar away" style="left:${homePct}%;width:${awayPct}%"></i>` : '<i class="bar none"></i>'}
      </span>
      <span class="bar-n">${r.total}</span>
    </div>`;
  }).join('');
  chart.querySelectorAll('.bar-row').forEach(row => {
    row.onclick = () => selectClub(Number(row.dataset.id));
    row.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectClub(Number(row.dataset.id)); } };
  });
  const top = rows[0];
  $('chart-note').textContent =
    top.total
      ? `${top.c.name} tops the ranking: ${top.total} of today's ${currentLeague().name} players ${METRIC_VERB[state.metric]} ${top.c.name} — ${top.home} still there, ${top.away} playing elsewhere in the league. Click a bar to drill into that club.`
      : 'No connections recorded for this league yet.';
}

function selectClub(id) {
  state.selected = id;
  state.query = '';
  state.pos.clear();
  $('search').value = '';
  renderClubs();
  renderPos();
  renderResults();
}

function renderPos() {
  const wrap = $('pos-chips');
  wrap.innerHTML = '';
  if (!state.selected) return;
  for (const g of ['GK', 'DF', 'MF', 'FW']) {
    const b = document.createElement('button');
    b.className = 'chip small' + (state.pos.has(g) ? ' on' : '');
    b.textContent = g;
    b.onclick = () => { state.pos.has(g) ? state.pos.delete(g) : state.pos.add(g); renderPos(); renderResults(); };
    wrap.appendChild(b);
  }
}

function matches(p) {
  if (state.query) {
    const q = state.query.toLowerCase();
    if (!(p.name.toLowerCase().includes(q) || p.club.name.toLowerCase().includes(q))) return false;
  }
  if (state.pos.size && !state.pos.has(p.group)) return false;
  return true;
}

function invYears(inv) {
  if (inv.years) return inv.years.replace(/-$/, '');
  if (inv.firstDate) {
    const f = inv.firstDate.slice(0, 4);
    const l = inv.lastDate && inv.lastDate.slice(0, 4);
    return l && l !== f ? `${f}–${l}` : f;
  }
  return '—';
}

function renderResults() {
  const club = currentClubs().find(c => c.id === state.selected);
  const section = $('results');
  if (!club) { section.hidden = true; return; }
  section.hidden = false;

  const rows = [];
  const stats = { senior: 0, academy: 0, both: 0, here: 0 };
  for (const p of currentPlayers()) {
    const inv = (p.involvements || []).find(i => i.club === club.name);
    if (!inv) continue;
    stats[inv.role] = (stats[inv.role] || 0) + 1;
    if (p.club.name === club.name) stats.here++;
    if (matches(p)) rows.push({ p, inv });
  }
  rows.sort((a, b) => a.p.name.localeCompare(b.p.name));

  const total = stats.senior + stats.academy + stats.both;
  $('summary').innerHTML =
    `<h2>Connected to ${club.name}</h2>
     <p><b>${total}</b> player${total === 1 ? '' : 's'} in today's ${currentLeague().name} have been part of ${club.name}:
     <span class="tag ft">${stats.senior} first team</span>
     <span class="tag ac">${stats.academy} academy only</span>
     <span class="tag bo">${stats.both} both</span>
     ${stats.here ? ` · <b>${stats.here}</b> still ${stats.here === 1 ? 'is' : 'are'} there now` : ''}</p>`;

  const tbody = $('tbody');
  tbody.innerHTML = '';
  for (const { p, inv } of rows) {
    const tr = document.createElement('tr');
    tr.className = 'exp';
    const here = p.club.name === club.name;
    tr.innerHTML = `
      <td data-label="Player"><button class="expand">${p.name}</button></td>
      <td data-label="Pos"><span class="pos">${p.group || '?'}</span></td>
      <td data-label="Now at">${p.club.name}${here ? ' <span class="dot" title="current squad">●</span>' : ''}</td>
      <td data-label="Connection"><span class="tag ${inv.role === 'senior' ? 'ft' : inv.role === 'academy' ? 'ac' : 'bo'}">${ROLE_LABEL[inv.role]}</span></td>
      <td data-label="Years" class="mono">${invYears(inv)}</td>`;
    tr.querySelector('.expand').onclick = () => toggleDetail(tr, p);
    tbody.appendChild(tr);
  }
  $('empty').hidden = rows.length > 0;
  $('search').oninput = (e) => { state.query = e.target.value; renderResults(); };
  $('search').disabled = false;
}

function toggleDetail(tr, p) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains('detail')) {
    next.remove();
    tr.classList.remove('open');
    return;
  }
  const d = document.createElement('tr');
  d.className = 'detail';
  const invs = (p.involvements || []).slice().sort((a, b) => (a.lastDate || '').localeCompare(b.lastDate || ''));
  d.innerHTML = `<td colspan="5"><div class="career">
    <p class="career-head">${p.name} — career clubs <span class="muted">(per Transfermarkt history)</span></p>
    <div class="career-grid">${
      invs.map(i =>
        `<span class="career-item"><span class="tag ${i.role === 'senior' ? 'ft' : i.role === 'academy' ? 'ac' : 'bo'}">${ROLE_LABEL[i.role]}</span>
         <b>${i.club}</b> <span class="muted">${invYears(i)}</span></span>`).join('') || '<span class="muted">no club history recorded</span>'
    }</div></div></td>`;
  tr.after(d);
  tr.classList.add('open');
}

init();
