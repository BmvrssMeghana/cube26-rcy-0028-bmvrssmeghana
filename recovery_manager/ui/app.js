/* ─────────────────────────────────────────────────────────
   Recovery Manager · Frontend JavaScript
   ───────────────────────────────────────────────────────── */

const API = 'http://localhost:5000/api';

// ── State ────────────────────────────────────────────────
let state = {
  decisions: [],
  metrics: {},
  currentView: 'dashboard',
};

// ── Init ─────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  initTheme();
  loadOrgs();
  loadPolicy();
});

// ── Theme Switcher ───────────────────────────────────────
function initTheme() {
  const savedTheme = localStorage.getItem('theme') || 'light';
  applyTheme(savedTheme);
}

function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  const newTheme = currentTheme === 'light' ? 'dark' : 'light';
  applyTheme(newTheme);
  localStorage.setItem('theme', newTheme);
}

function applyTheme(theme) {
  if (theme === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark');
    document.getElementById('themeIcon').textContent = '🌙';
    document.getElementById('themeText').textContent = 'Dark';
  } else {
    document.documentElement.removeAttribute('data-theme');
    document.getElementById('themeIcon').textContent = '☀️';
    document.getElementById('themeText').textContent = 'Light';
  }
}

// ── Navigation ───────────────────────────────────────────
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById(`view-${name}`).classList.add('active');
  document.querySelector(`[data-view="${name}"]`).classList.add('active');

  const titles = {
    dashboard: 'Dashboard',
    charges: 'Charges',
    claims: 'Claims',
    upload: 'Upload',
    policy: 'SLA Policy',
  };
  document.getElementById('pageTitle').textContent = titles[name] || name;
  state.currentView = name;
}

// ── Org loader ───────────────────────────────────────────
async function loadOrgs() {
  try {
    const res = await fetch(`${API}/orgs`);
    const orgs = await res.json();
    const sel = document.getElementById('orgSelector');
    orgs.forEach(o => {
      const opt = document.createElement('option');
      opt.value = o;
      opt.textContent = o;
      sel.appendChild(opt);
    });
  } catch {}
}

function loadOrg() {
  if (state.decisions.length > 0) runAnalysis();
}

// ── Run Analysis ─────────────────────────────────────────
async function runAnalysis() {
  showLoading(true);
  const org = document.getElementById('orgSelector').value;
  const url = `${API}/run${org ? `?org=${encodeURIComponent(org)}` : ''}`;

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    applyResults(data);
  } catch (err) {
    alert(`Analysis failed: ${err.message}`);
  } finally {
    showLoading(false);
  }
}

// ── Apply Results ────────────────────────────────────────
function applyResults(data) {
  state.decisions = data.decisions || [];
  state.metrics = data.metrics || {};
  updateMetrics();
  renderChargesTable();
  renderClaimsView();
  renderVerdictChart();
  renderTopClaims();
}

function updateMetrics() {
  const m = state.metrics;
  setText('m-total', m.total_charges_evaluated ?? '—');
  setText('m-claims', m.claims_recommended ?? '—');
  setText('m-value', m.total_claim_value_usd != null ? `$${m.total_claim_value_usd.toFixed(2)}` : '—');
  setText('m-uncertain', (m.uncertain_review_rate ?? 0) + (m.pending_review ?? 0));
  setText('m-dup', m.duplicate_flags ?? '—');
  setText('m-silent', m.silent_charges ?? '—');
}

// ── Charges Table ────────────────────────────────────────
function renderChargesTable() {
  const tbody = document.getElementById('chargesBody');
  if (!state.decisions.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty-cell">No charges loaded</td></tr>';
    return;
  }
  tbody.innerHTML = state.decisions.map(d => chargeRow(d)).join('');
}

function chargeRow(d) {
  const slaClass = `sla-${d.sla?.status || 'unknown'}`;
  const slaLabel = {
    open: '✓ Open',
    expired: '✗ Expired',
    min_wait: '⏳ Min Wait',
    unknown: '? Unknown',
  }[d.sla?.status || 'unknown'] || '?';
  const dupBadge = d.duplicate_flag ? `<span class="dup-flag">DUP</span>` : '';
  const claimAmt = d.claim_amount > 0
    ? `<span class="amount-cell amount-claimable">$${d.claim_amount.toFixed(2)}</span>`
    : `<span class="amount-cell" style="color:var(--text3)">—</span>`;

  return `<tr>
    <td>${esc(d.line_id)}${dupBadge}</td>
    <td style="font-family:monospace;font-size:12px;">${esc(d.unit_id)}</td>
    <td>${chargeTypeLabel(d.charge_type)}</td>
    <td class="amount-cell">$${(d.amount_usd || 0).toFixed(2)}</td>
    <td style="font-size:12px;color:var(--text3)">${esc(d.sla?.deadline || '—')}</td>
    <td><span class="sla-badge ${slaClass}">${slaLabel}</span></td>
    <td><span class="verdict-badge v-${d.verdict}">${d.verdict}</span></td>
    <td>${claimAmt}</td>
    <td><button class="detail-btn" onclick="openModal('${esc(d.line_id)}')">Detail ›</button></td>
  </tr>`;
}

// ── Filter table ─────────────────────────────────────────
function filterTable() {
  const q = document.getElementById('chargeSearch').value.toLowerCase();
  const vf = document.getElementById('verdictFilter').value;
  const tf = document.getElementById('chargeTypeFilter').value;

  const filtered = state.decisions.filter(d => {
    const matchQ = !q || JSON.stringify(d).toLowerCase().includes(q);
    const matchV = !vf || d.verdict === vf;
    const matchT = !tf || d.charge_type === tf;
    return matchQ && matchV && matchT;
  });

  const tbody = document.getElementById('chargesBody');
  if (!filtered.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty-cell">No matching charges</td></tr>';
    return;
  }
  tbody.innerHTML = filtered.map(d => chargeRow(d)).join('');
}

// ── Claims View ───────────────────────────────────────────
function renderClaimsView() {
  const claims = state.decisions.filter(d => d.verdict === 'CONTRADICTED');
  const total = claims.reduce((s, c) => s + (c.claim_amount || 0), 0);

  document.getElementById('claimCount').textContent =
    `${claims.length} claim${claims.length !== 1 ? 's' : ''} recommended · Total: $${total.toFixed(2)}`;

  const grid = document.getElementById('claimsGrid');
  if (!claims.length) {
    grid.innerHTML = '<div class="empty-state">No CONTRADICTED charges — all evidence insufficient or supporting fees</div>';
    return;
  }
  grid.innerHTML = claims.map(claimCard).join('');
}

function claimCard(d) {
  const evidence = (d.supporting_evidence || []).map(e =>
    `<span class="evidence-chip">${esc(e)}</span>`
  ).join('');
  const dupBlock = d.duplicate_flag
    ? `<div class="dup-warning">⚠ ${esc(d.duplicate_note)}</div>` : '';
  const slaInfo = d.sla?.deadline
    ? `<div class="claim-field"><span class="claim-field-key">Filing Deadline</span><span class="claim-field-val">${esc(d.sla.deadline)} (${d.sla.days_remaining}d remaining)</span></div>` : '';

  return `<div class="claim-card">
    <div class="claim-card-header">
      <div>
        <div class="claim-line-id">${esc(d.line_id)}</div>
        <div style="font-size:11px;color:var(--text3);margin-top:3px">${chargeTypeLabel(d.charge_type)}</div>
      </div>
      <div class="claim-amount-badge">$${(d.claim_amount || 0).toFixed(2)}</div>
    </div>
    <div class="claim-card-body">
      <div class="claim-field"><span class="claim-field-key">Unit ID</span><span class="claim-field-val" style="font-family:monospace">${esc(d.unit_id)}</span></div>
      <div class="claim-field"><span class="claim-field-key">Charge Amount</span><span class="claim-field-val">$${(d.amount_usd || 0).toFixed(2)}</span></div>
      ${slaInfo}
      <div class="claim-reasoning">${esc(d.reasoning)}</div>
      ${evidence ? `<div class="claim-evidence">${evidence}</div>` : ''}
      ${dupBlock}
      <div style="margin-top:12px;text-align:right">
        <button class="detail-btn" onclick="openModal('${esc(d.line_id)}')">View Evidence ›</button>
      </div>
    </div>
  </div>`;
}

// ── Verdict Chart ─────────────────────────────────────────
function renderVerdictChart() {
  const counts = {};
  state.decisions.forEach(d => {
    counts[d.verdict] = (counts[d.verdict] || 0) + 1;
  });
  const total = state.decisions.length || 1;

  const verdicts = [
    { key: 'CONTRADICTED', label: 'Contradicted (Claim)', cls: 'bar-contradicted' },
    { key: 'SUPPORTED', label: 'Supported (Legit)', cls: 'bar-supported' },
    { key: 'SILENT', label: 'Silent (No Evidence)', cls: 'bar-silent' },
    { key: 'UNCERTAIN', label: 'Uncertain (Review)', cls: 'bar-uncertain' },
    { key: 'PENDING_REVIEW', label: 'Pending Review', cls: 'bar-pending' },
  ];

  const html = `<div class="chart-bars">` +
    verdicts.map(v => {
      const n = counts[v.key] || 0;
      const pct = ((n / total) * 100).toFixed(1);
      return `<div class="chart-bar-row">
        <div class="chart-bar-label">${v.label}</div>
        <div class="chart-bar-track">
          <div class="chart-bar-fill ${v.cls}" style="width:${pct}%">${n > 0 ? n : ''}</div>
        </div>
        <div class="chart-bar-count">${n}</div>
      </div>`;
    }).join('') + `</div>`;

  document.getElementById('verdictChart').innerHTML = html;
}

// ── Top Claims ───────────────────────────────────────────
function renderTopClaims() {
  const claims = state.decisions
    .filter(d => d.verdict === 'CONTRADICTED' && d.claim_amount > 0)
    .sort((a, b) => b.claim_amount - a.claim_amount)
    .slice(0, 5);

  const el = document.getElementById('topClaimsList');
  if (!claims.length) {
    el.innerHTML = '<div class="empty-state" style="padding:20px">No claimable charges</div>';
    return;
  }

  el.innerHTML = claims.map((d, i) => `
    <div class="top-claim-item" onclick="openModal('${esc(d.line_id)}')">
      <div class="top-claim-rank">${i + 1}</div>
      <div class="top-claim-info">
        <div class="top-claim-id">${esc(d.line_id)}</div>
        <div class="top-claim-type">${chargeTypeLabel(d.charge_type)} · ${esc(d.unit_id)}</div>
      </div>
      <div class="top-claim-amount">$${(d.claim_amount || 0).toFixed(2)}</div>
    </div>
  `).join('');
}

// ── Modal ─────────────────────────────────────────────────
async function openModal(lineId) {
  const d = state.decisions.find(x => x.line_id === lineId);
  if (!d) return;

  document.getElementById('modalTitle').textContent = lineId;
  document.getElementById('modalSub').textContent = `${chargeTypeLabel(d.charge_type)} · ${d.unit_id} · ${d.org_id}`;

  const verdictColor = {
    CONTRADICTED: 'var(--green)',
    SUPPORTED: 'var(--text3)',
    SILENT: 'var(--text3)',
    UNCERTAIN: 'var(--amber)',
    PENDING_REVIEW: 'var(--red)',
  }[d.verdict] || 'var(--text)';

  const citedEvi = (d.cited_fields || []).map(f => {
    const valClass = f.value && ['yes', 'legible', 'flat', 'all_present'].includes(f.value)
      ? 'evi-val-good'
      : f.value && ['on_seam', 'on_curve', 'missing', 'not_sealed', 'obscured_by_fold'].includes(f.value)
        ? 'evi-val-bad'
        : f.value === 'uncertain' ? 'evi-val-uncertain' : '';
    return `<div class="modal-evidence-item">
      <div class="evi-source">${esc(f.source)} · ${esc(f.record_id)}</div>
      <div class="evi-field">${esc(f.field)} = <span class="${valClass}">${esc(f.value)}</span></div>
    </div>`;
  }).join('') || '<div style="color:var(--text3);font-size:13px">No field-level citations</div>';

  const slaHtml = d.sla ? `
    <div class="modal-kv">
      <div class="modal-key">Status</div><div class="modal-val"><span class="sla-badge sla-${d.sla.status}">${d.sla.status}</span></div>
      <div class="modal-key">Deadline</div><div class="modal-val">${d.sla.deadline || '—'}</div>
      <div class="modal-key">Earliest Filing</div><div class="modal-val">${d.sla.earliest_filing || '—'}</div>
      <div class="modal-key">Days Remaining</div><div class="modal-val">${d.sla.days_remaining != null ? d.sla.days_remaining + ' days' : '—'}</div>
      <div class="modal-key">Policy Note</div><div class="modal-val" style="color:var(--text3);font-size:12px">${esc(d.sla.policy_note || '')}</div>
    </div>` : '<div style="color:var(--text3)">No SLA data</div>';

  const dupHtml = d.duplicate_flag
    ? `<div style="padding:10px 12px;background:var(--blue-bg);border-radius:6px;font-size:12px;color:var(--blue)">⚠ ${esc(d.duplicate_note)}</div>`
    : '<div style="color:var(--text3);font-size:13px">None detected</div>';

  const errHtml = d.error
    ? `<div style="padding:10px 12px;background:var(--red-bg);border-radius:6px;font-size:12px;color:var(--red)">${esc(d.error)}</div>`
    : '';

  document.getElementById('modalBody').innerHTML = `
    <div class="modal-section">
      <div class="modal-section-title">Verdict</div>
      <div style="font-size:20px;font-weight:800;color:${verdictColor};margin-bottom:8px">${d.verdict}</div>
      <div style="font-size:13px;color:var(--text2);line-height:1.5">${esc(d.reasoning)}</div>
      ${d.claim_amount > 0 ? `<div style="margin-top:10px;font-size:15px;font-weight:700;color:var(--amber)">Potential Claim: $${(d.claim_amount).toFixed(2)}</div>` : ''}
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Charge Details</div>
      <div class="modal-kv">
        <div class="modal-key">Line ID</div><div class="modal-val" style="font-family:monospace">${esc(d.line_id)}</div>
        <div class="modal-key">Unit ID</div><div class="modal-val" style="font-family:monospace">${esc(d.unit_id)}</div>
        <div class="modal-key">Org</div><div class="modal-val">${esc(d.org_id)}</div>
        <div class="modal-key">Charge Type</div><div class="modal-val">${chargeTypeLabel(d.charge_type)}</div>
        <div class="modal-key">Amount</div><div class="modal-val" style="font-family:monospace">$${(d.amount_usd || 0).toFixed(2)}</div>
        <div class="modal-key">Report Type</div><div class="modal-val">${esc(d.report_type || '—')}</div>
      </div>
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Cited Evidence Fields</div>
      <div class="modal-evidence-list">${citedEvi}</div>
    </div>

    ${(d.supporting_evidence || []).length ? `<div class="modal-section">
      <div class="modal-section-title">Supporting Evidence Summary</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px">${(d.supporting_evidence || []).map(e => `<span class="evidence-chip">${esc(e)}</span>`).join('')}</div>
    </div>` : ''}

    <div class="modal-section">
      <div class="modal-section-title">SLA / Filing Window</div>
      ${slaHtml}
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Duplicate Detection</div>
      ${dupHtml}
    </div>

    ${errHtml ? `<div class="modal-section"><div class="modal-section-title">Engine Notes</div>${errHtml}</div>` : ''}
  `;

  document.getElementById('modalOverlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modalOverlay').classList.remove('open');
}

// ── Policy View ───────────────────────────────────────────
async function loadPolicy() {
  try {
    const res = await fetch(`${API}/policy`);
    const policy = await res.json();
    const rows = Object.entries(policy).map(([ct, p]) => `
      <tr>
        <td style="font-family:monospace;font-size:12px">${esc(ct)}</td>
        <td>${p.min_wait_days} days</td>
        <td>${p.max_window_days} days</td>
        <td>${p.basis}</td>
        <td style="font-size:12px;color:var(--text3)">${esc(p.note)}</td>
      </tr>
    `).join('');

    document.getElementById('policyTable').innerHTML = `
      <table class="policy-table">
        <thead><tr>
          <th>Charge Type</th>
          <th>Min Wait</th>
          <th>Max Window</th>
          <th>Basis</th>
          <th>Policy Note</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  } catch {
    document.getElementById('policyTable').innerHTML = '<div class="empty-state">Could not load policy (API offline)</div>';
  }
}

// ── Upload Form ───────────────────────────────────────────
async function submitUpload(e) {
  e.preventDefault();
  showLoading(true);
  const form = document.getElementById('uploadForm');
  const fd = new FormData(form);

  const org = document.getElementById('orgSelector').value;
  if (org) fd.append('org', org);

  try {
    const res = await fetch(`${API}/upload`, { method: 'POST', body: fd });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    applyResults(data);
    showView('dashboard');
  } catch (err) {
    alert(`Upload failed: ${err.message}`);
  } finally {
    showLoading(false);
  }
}

function markZone(zoneId, input) {
  const zone = document.getElementById(zoneId);
  if (input.files && input.files.length > 0) {
    zone.classList.add('has-file');
    const hint = zone.querySelector('.upload-hint');
    hint.textContent = input.files[0].name;
  }
}

// ── Helpers ───────────────────────────────────────────────
function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function chargeTypeLabel(ct) {
  const labels = {
    inbound_defect_fee: 'Inbound Defect Fee',
    lost_inbound: 'Lost Inbound',
    damaged_in_warehouse: 'Damaged in Warehouse',
    fulfilment_fee_weight_tier: 'Fulfilment Fee Weight',
    refund_issued_item_not_returned: 'Refund — Item Not Returned',
  };
  return labels[ct] || ct;
}

function showLoading(active) {
  const el = document.getElementById('loadingOverlay');
  el.classList.toggle('active', active);
}
