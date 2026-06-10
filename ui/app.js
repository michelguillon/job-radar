/* Job Radar UI — vanilla JS, no build step, no framework.
 *
 * Reads data/index.json (the join produced by `python -m cli.stats --export-index`:
 * one row per scored job = ApplicationRecord ⨝ JDRecord ⨝ sidecar ⨝ activity-log
 * projection, plus a `stats` block). The UI is strictly read-only — it never POSTs,
 * never writes, never calls a CLI. All state lives in memory.
 */
'use strict';

const DATA_URL = 'data/index.json';

// Canonical orderings (mirror models/record.py enums) so empty buckets still
// render in a sensible order and the pipeline lanes read like a funnel.
const FIT_LABELS = ['strong_fit', 'good_fit', 'stretch', 'interview_practice', 'income_bridge', 'blocked_fit'];
const STATUS_ORDER = ['new', 'review', 'shortlisted', 'applied', 'interviewing', 'offer', 'rejected', 'archived'];
const LABEL_TEXT = {
  strong_fit: 'strong', good_fit: 'good', stretch: 'stretch',
  interview_practice: 'practice', income_bridge: 'bridge', blocked_fit: 'blocked',
};

const state = {
  records: [],
  stats: null,
  view: 'browse',
  sort: { key: 'priority_score', dir: 'desc' },
  filters: {
    search: '',
    fitMin: 1, fitMax: 10,
    priMin: 1, priMax: 10,
    locWorkable: false,
    fitLabels: new Set(),   // empty = all
    statuses: new Set(),
    domains: new Set(),
    roles: new Set(),
  },
};

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const k of kids) node.append(k);
  return node;
};

// ───────────────────────── load ─────────────────────────

async function boot() {
  let data;
  try {
    const res = await fetch(DATA_URL, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    document.body.innerHTML =
      `<p style="padding:40px;color:#9a3636">Could not load <code>${DATA_URL}</code>: ${err.message}.<br>` +
      `Run <code>python -m cli.stats --input "corpus/validated/validated_*.jsonl" --export-index</code> first.</p>`;
    return;
  }
  state.records = data.records || [];
  state.stats = data.stats || null;
  if (data.generated_at) $('#generated').textContent = `· built ${fmtDate(data.generated_at)}`;

  renderStatbar();
  buildFilterControls();
  wireEvents();
  render();
}

// ───────────────────────── stats bar ─────────────────────────

function renderStatbar() {
  const s = state.stats;
  const bar = $('#statbar');
  bar.innerHTML = '';
  if (!s) return;

  bar.append(stat(s.total, 'roles'));

  const strong = (s.by_fit_label && s.by_fit_label.strong_fit) || 0;
  bar.append(stat(strong, 'strong fit'));

  const active = STATUS_ORDER
    .filter(k => !['new', 'rejected', 'archived'].includes(k))
    .reduce((n, k) => n + ((s.by_application_status && s.by_application_status[k]) || 0), 0);
  bar.append(stat(active, 'in pipeline'));

  if (typeof s.cost_to_date_usd === 'number') {
    bar.append(stat('$' + s.cost_to_date_usd.toFixed(2), 'cost to date'));
  }

  // score distribution sparkline (1..10)
  const dist = s.fit_score_distribution || {};
  const max = Math.max(1, ...Object.values(dist));
  const spark = el('div', { className: 'spark', title: 'fit_score distribution (1–10)' });
  for (let i = 1; i <= 10; i++) {
    const c = dist[String(i)] || 0;
    const bar2 = el('div', { className: 'bar' + (i < 6 ? ' lo' : '') });
    bar2.style.height = `${Math.round((c / max) * 26)}px`;
    bar2.title = `score ${i}: ${c}`;
    spark.append(bar2);
  }
  const wrap = el('div', { className: 'stat' });
  wrap.append(spark, el('span', { className: 'k', textContent: 'score 1–10' }));
  bar.append(wrap);
}

function stat(value, key) {
  const node = el('div', { className: 'stat' });
  node.append(el('span', { className: 'v', textContent: String(value) }));
  node.append(el('span', { className: 'k', textContent: key }));
  return node;
}

// ───────────────────────── filter controls ─────────────────────────

function buildFilterControls() {
  // fit label + status: canonical order, only those present
  const present = key => new Set(state.records.map(r => r[key]).filter(Boolean));

  renderChecks($('#fitLabelChecks'), FIT_LABELS.filter(l => present('fit_label').has(l)),
    state.filters.fitLabels, countBy('fit_label'), v => labelBadge(v));

  renderChecks($('#statusChecks'), STATUS_ORDER.filter(s => present('application_status').has(s)),
    state.filters.statuses, countBy('application_status'), v => v);

  // domain + role_type: list-valued, frequency order
  renderChecks($('#domainChecks'), sortedByFreq('domain'),
    state.filters.domains, countByList('domain'), v => v);

  renderChecks($('#roleChecks'), sortedByFreq('role_type'),
    state.filters.roles, countByList('role_type'), v => v);
}

function countBy(key) {
  const m = {};
  for (const r of state.records) if (r[key]) m[r[key]] = (m[r[key]] || 0) + 1;
  return m;
}
function countByList(key) {
  const m = {};
  for (const r of state.records) for (const v of (r[key] || [])) m[v] = (m[v] || 0) + 1;
  return m;
}
function sortedByFreq(key) {
  const m = countByList(key);
  return Object.keys(m).sort((a, b) => m[b] - m[a] || a.localeCompare(b));
}

function renderChecks(container, values, selectedSet, counts, labelFn) {
  container.innerHTML = '';
  if (!values.length) { container.append(el('span', { className: 'muted', textContent: '—' })); return; }
  for (const v of values) {
    const cb = el('input', { type: 'checkbox', checked: selectedSet.has(v) });
    cb.addEventListener('change', () => {
      cb.checked ? selectedSet.add(v) : selectedSet.delete(v);
      render();
    });
    const labelNode = labelFn(v);
    const label = el('label');
    label.append(cb, typeof labelNode === 'string' ? document.createTextNode(labelNode) : labelNode);
    label.append(el('span', { className: 'ct', textContent: String(counts[v] || 0) }));
    container.append(label);
  }
}

function labelBadge(label) {
  return el('span', { className: `badge ${label}`, textContent: LABEL_TEXT[label] || label });
}

// ───────────────────────── events ─────────────────────────

function wireEvents() {
  document.querySelectorAll('.tab').forEach(t =>
    t.addEventListener('click', () => setView(t.dataset.view)));

  // honour #browse / #pipeline on load and on hash change (bookmarkable)
  if (location.hash === '#pipeline') setView('pipeline');
  window.addEventListener('hashchange', () => setView(location.hash === '#pipeline' ? 'pipeline' : 'browse'));

  $('#search').addEventListener('input', e => { state.filters.search = e.target.value.trim().toLowerCase(); render(); });

  const num = (id, key) => $('#' + id).addEventListener('input', e => {
    const v = parseInt(e.target.value, 10);
    state.filters[key] = Number.isFinite(v) ? v : (key.endsWith('Min') ? 1 : 10);
    render();
  });
  num('fitMin', 'fitMin'); num('fitMax', 'fitMax');
  num('priMin', 'priMin'); num('priMax', 'priMax');

  $('#locWorkable').addEventListener('change', e => { state.filters.locWorkable = e.target.checked; render(); });

  document.querySelectorAll('.grid th[data-sort]').forEach(th =>
    th.addEventListener('click', () => toggleSort(th.dataset.sort)));

  $('#resetFilters').addEventListener('click', resetFilters);

  $('#scrim').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
}

function setView(view) {
  state.view = view;
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x.dataset.view === view));
  if (location.hash !== '#' + view) history.replaceState(null, '', '#' + view);
  render();
}

function toggleSort(key) {
  const s = state.sort;
  if (s.key === key) s.dir = s.dir === 'asc' ? 'desc' : 'asc';
  else { s.key = key; s.dir = (key === 'company' || key === 'title' || key === 'location') ? 'asc' : 'desc'; }
  render();
}

function resetFilters() {
  Object.assign(state.filters, { search: '', fitMin: 1, fitMax: 10, priMin: 1, priMax: 10, locWorkable: false });
  ['fitLabels', 'statuses', 'domains', 'roles'].forEach(k => state.filters[k].clear());
  $('#search').value = '';
  $('#fitMin').value = 1; $('#fitMax').value = 10; $('#priMin').value = 1; $('#priMax').value = 10;
  $('#locWorkable').checked = false;
  document.querySelectorAll('.checks input').forEach(c => { c.checked = false; });
  render();
}

// ───────────────────────── filter + sort ─────────────────────────

function applyFilters() {
  const f = state.filters;
  return state.records.filter(r => {
    if (r.fit_score < f.fitMin || r.fit_score > f.fitMax) return false;
    if (r.priority_score < f.priMin || r.priority_score > f.priMax) return false;
    if (f.locWorkable && r.location_workable !== 'yes') return false;
    if (f.fitLabels.size && !f.fitLabels.has(r.fit_label)) return false;
    if (f.statuses.size && !f.statuses.has(r.application_status)) return false;
    if (f.domains.size && !(r.domain || []).some(d => f.domains.has(d))) return false;
    if (f.roles.size && !(r.role_type || []).some(d => f.roles.has(d))) return false;
    if (f.search) {
      const hay = `${r.company} ${r.title}`.toLowerCase();
      if (!hay.includes(f.search)) return false;
    }
    return true;
  });
}

function sortRows(rows) {
  const { key, dir } = state.sort;
  const mul = dir === 'asc' ? 1 : -1;
  return rows.slice().sort((a, b) => {
    let av = a[key], bv = b[key];
    if (typeof av === 'number' && typeof bv === 'number') {
      if (av !== bv) return (av - bv) * mul;
    } else {
      const c = String(av ?? '').localeCompare(String(bv ?? ''));
      if (c) return c * mul;
    }
    // stable tiebreak: priority desc then company
    return (b.priority_score - a.priority_score) || a.company.localeCompare(b.company);
  });
}

// ───────────────────────── render ─────────────────────────

function render() {
  const rows = applyFilters();
  $('#resultCount').textContent = `${rows.length} of ${state.records.length} roles`;
  $('#browseView').hidden = state.view !== 'browse';
  $('#pipelineView').hidden = state.view !== 'pipeline';
  if (state.view === 'browse') renderGrid(sortRows(rows));
  else renderPipeline(rows);
}

function renderGrid(rows) {
  const body = $('#gridBody');
  body.innerHTML = '';
  $('#browseEmpty').hidden = rows.length > 0;

  document.querySelectorAll('.grid th[data-sort]').forEach(th => {
    const on = th.dataset.sort === state.sort.key;
    th.classList.toggle('sorted', on);
    th.classList.toggle('asc', on && state.sort.dir === 'asc');
  });

  for (const r of rows) {
    const tr = el('tr');
    if (r.fit_label === 'blocked_fit') tr.classList.add('is-blocked');
    tr.addEventListener('click', e => { if (e.target.tagName !== 'A') openDrawer(r); });

    tr.append(el('td', { className: 'company', textContent: r.company }));

    const role = el('td', { className: 'role' });
    role.append(el('span', { className: 'role-text', textContent: r.title }));
    tr.append(role);

    const fit = el('td'); fit.append(labelBadge(r.fit_label)); tr.append(fit);
    tr.append(el('td', { className: 'num score-cell', textContent: r.fit_score }));
    tr.append(el('td', { className: 'num pri-cell', textContent: r.priority_score }));
    tr.append(el('td', { className: 'loc', textContent: r.location || '—' }));

    const st = el('td');
    st.append(el('span', { className: `pill ${r.application_status}`, textContent: r.application_status }));
    tr.append(st);

    tr.append(el('td', { className: 'seen', textContent: fmtDate(r.date_first_seen) }));

    const link = el('td');
    if (r.source_url) link.append(el('a', { className: 'link-out', href: r.source_url, target: '_blank', rel: 'noopener', textContent: 'open ↗' }));
    tr.append(link);

    body.append(tr);
  }
}

function renderPipeline(rows) {
  const view = $('#pipelineView');
  view.innerHTML = '';
  const byStatus = {};
  for (const r of rows) (byStatus[r.application_status] ||= []).push(r);

  const order = STATUS_ORDER.filter(s => byStatus[s]);
  if (!order.length) { view.append(el('p', { className: 'empty', textContent: 'No roles match the current filters.' })); return; }

  for (const status of order) {
    const group = byStatus[status].sort((a, b) => b.priority_score - a.priority_score || b.fit_score - a.fit_score);
    const head = el('div', { className: 'pipe-head' });
    head.append(el('span', { textContent: status }));
    head.append(el('span', { className: 'count', textContent: group.length }));
    head.append(el('span', { className: 'rule' }));

    const block = el('div', { className: 'pipe-group' });
    block.append(head);
    for (const r of group) {
      const card = el('div', { className: 'pipe-card' + (r.fit_label === 'blocked_fit' ? ' is-blocked' : '') });
      card.addEventListener('click', () => openDrawer(r));
      card.append(el('div', { className: 'pc-score', textContent: r.priority_score }));
      const main = el('div', { className: 'pc-main' });
      main.append(el('div', { className: 'pc-co', textContent: r.company }));
      main.append(el('div', { className: 'pc-role', textContent: r.title }));
      card.append(main);
      card.append(labelBadge(r.fit_label));
      block.append(card);
    }
    view.append(block);
  }
}

// ───────────────────────── detail drawer ─────────────────────────

function openDrawer(r) {
  const d = $('#drawer');
  d.innerHTML = '';

  const head = el('div', { className: 'dh' });
  const close = el('button', { className: 'close', textContent: '×', title: 'Close (Esc)' });
  close.addEventListener('click', closeDrawer);
  head.append(close);
  head.append(el('div', { className: 'co', textContent: r.company }));
  head.append(el('h2', { textContent: r.title }));

  const meta = el('div', { className: 'dh-meta' });
  meta.append(labelBadge(r.fit_label));
  meta.append(el('span', { className: `pill ${r.application_status}`, textContent: r.application_status }));
  if (r.location) meta.append(el('span', { className: 'muted', textContent: r.location }));
  head.append(meta);

  const scores = el('div', { className: 'scores' });
  scores.append(scoreBox(r.fit_score, 'fit score'));
  scores.append(scoreBox(r.priority_score, 'priority'));
  if (r.location_workable) scores.append(scoreBox(r.location_workable, 'location'));
  head.append(scores);
  d.append(head);

  const body = el('div', { className: 'dbody' });

  if (r.fit_label_reason) body.append(section('Assessment', el('p', { className: 'reason', textContent: r.fit_label_reason })));
  if ((r.blocking_constraints || []).length) body.append(section('Blocking constraints', chips(r.blocking_constraints, 'block')));
  if ((r.requirement_gaps || []).length) body.append(section('Requirement gaps', chips(r.requirement_gaps, 'warn')));
  if (r.notes) body.append(section('Notes', el('p', {}, r.notes)));

  // extraction facts
  const kv = el('dl', { className: 'kv' });
  addKV(kv, 'Role type', listText(r.role_type));
  addKV(kv, 'Domain', listText(r.domain));
  addKV(kv, 'Seniority', r.seniority);
  addKV(kv, 'Technical depth', r.technical_depth);
  addKV(kv, 'Remote policy', r.remote_policy);
  addKV(kv, 'Company stage', r.company_stage);
  addKV(kv, 'Company size', r.company_size_signal);
  addKV(kv, 'Experience', r.years_experience_required);
  addKV(kv, 'Delivery motion', listText(r.delivery_motion));
  addKV(kv, 'Source', r.source_ats);
  addKV(kv, 'First seen', fmtDate(r.date_first_seen));
  if (r.application_date) addKV(kv, 'Applied', r.application_date);
  body.append(section('Extraction', kv));

  if ((r.required_technologies || []).length) body.append(section('Required technologies', chips(r.required_technologies)));
  if ((r.required_competencies || []).length) body.append(section('Required competencies', chips(r.required_competencies)));
  if ((r.nice_to_have_technologies || []).length || (r.nice_to_have_competencies || []).length)
    body.append(section('Nice to have', chips([...(r.nice_to_have_technologies || []), ...(r.nice_to_have_competencies || [])])));
  if ((r.culture_signals || []).length) body.append(section('Culture signals', chips(r.culture_signals)));
  if (r.raw_observations) body.append(section('Raw observations', el('p', { className: 'muted' }, r.raw_observations)));

  if (r.raw_text) body.append(section('Full JD text', el('div', { className: 'jd-text', textContent: r.raw_text })));

  if (r.source_url) {
    const s = section('Source', el('a', { className: 'link-out', href: r.source_url, target: '_blank', rel: 'noopener', textContent: r.source_url }));
    body.append(s);
  }

  d.append(body);
  d.hidden = false;
  $('#scrim').hidden = false;
  d.scrollTop = 0;
}

function closeDrawer() {
  $('#drawer').hidden = true;
  $('#scrim').hidden = true;
}

function scoreBox(n, label) {
  const box = el('div', { className: 's' });
  box.append(el('div', { className: 'n', textContent: n }));
  box.append(el('div', { className: 'l', textContent: label }));
  return box;
}
function section(title, ...nodes) {
  const s = el('div', { className: 'dsection' });
  s.append(el('h3', { textContent: title }));
  for (const n of nodes) s.append(n);
  return s;
}
function chips(items, cls = '') {
  const wrap = el('div', { className: 'chips' });
  for (const it of items) wrap.append(el('span', { className: 'chip ' + cls, textContent: it }));
  return wrap;
}
function addKV(dl, key, value) {
  if (!value) return;
  dl.append(el('dt', { textContent: key }));
  dl.append(el('dd', { textContent: value }));
}

// ───────────────────────── utils ─────────────────────────

function listText(v) { return Array.isArray(v) ? v.join(', ') : (v || ''); }
function fmtDate(s) {
  if (!s) return '—';
  const d = new Date(s);
  return isNaN(d) ? String(s).slice(0, 10) : d.toISOString().slice(0, 10);
}

boot();
