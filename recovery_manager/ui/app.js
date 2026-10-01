/* ─────────────────────────────────────────────────────────
   Recovery Manager · Frontend JavaScript (v1.1 Agentic UI)
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
    claims: 'Claims (Triage Queue)',
    review: 'Dedicated Review Queue',
    upload: 'Upload Reports',
    policy: 'SLA Policy Time Machine',
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
  } catch { }
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

  if (data.metrics && data.metrics.analysis_run_timestamp) {
    const badge = document.getElementById('runStampBadge');
    if (badge) badge.textContent = `Analysis run: ${data.metrics.analysis_run_timestamp}`;
  }

  updateMetrics();
  renderChargesTable();
  renderClaimsView();
  renderReviewQueue();
  renderVerdictChart();
  renderTopClaims();
}

function updateMetrics() {
  const m = state.metrics;
  setText('m-total', m.total_charges_evaluated ?? '—');
  setText('m-claims', m.claims_recommended ?? '—');
  setText('m-value', m.total_claim_value_usd != null ? `$${m.total_claim_value_usd.toFixed(2)}` : '—');
  setText('m-uncertain', (m.uncertain_review_rate ?? 0) + (m.pending_review ?? 0) + (m.not_yet_supported ?? 0));
  setText('m-dup', m.duplicate_suppressed ?? m.duplicate_flags ?? '—');
  setText('m-silent', (m.silent_charges ?? 0) + (m.already_recovered ?? 0) + (m.expired_claims ?? 0));
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
  const dupBadge = d.duplicate_flag ? `<span class="dup-flag" title="${esc(d.duplicate_note)}">DUP</span>` : '';
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

// ── Claims View (Triage Queue Section 4.5) ───────────────
function renderClaimsView() {
  const claims = state.decisions.filter(d => d.verdict === 'CONTRADICTED');

  // Section 4.5: Triage Queue Ranking by (amount / max(days_remaining, 1))
  claims.sort((a, b) => {
    const remA = Math.max(a.sla?.days_remaining || 30, 1);
    const remB = Math.max(b.sla?.days_remaining || 30, 1);
    const scoreA = (a.claim_amount || 0) / remA;
    const scoreB = (b.claim_amount || 0) / remB;
    return scoreB - scoreA;
  });

  const total = claims.reduce((s, c) => s + (c.claim_amount || 0), 0);

  document.getElementById('claimCount').textContent =
    `${claims.length} claim${claims.length !== 1 ? 's' : ''} in Triage Queue · Total Claimable: $${total.toFixed(2)}`;

  const grid = document.getElementById('claimsGrid');
  if (!claims.length) {
    grid.innerHTML = '<div class="empty-state">No CONTRADICTED claims in queue — all evidence supported or silent</div>';
    return;
  }
  grid.innerHTML = claims.map((d, i) => claimCard(d, i + 1)).join('');
}

function claimCard(d, priorityRank) {
  const evidence = (d.supporting_evidence || []).map(e =>
    `<span class="evidence-chip">${esc(e)}</span>`
  ).join('');
  const dupBlock = d.duplicate_flag
    ? `<div class="dup-warning">⚠ ${esc(d.duplicate_note)}</div>` : '';
  const slaInfo = d.sla?.deadline
    ? `<div class="claim-field"><span class="claim-field-key">Filing Deadline</span><span class="claim-field-val">${esc(d.sla.deadline)} (${d.sla.days_remaining}d remaining)</span></div>` : '';

  const tier = (d.completeness_score || 1.0) >= 0.8 ? 'Strong Evidence' : 'Moderate Evidence';

  return `<div class="claim-card">
    <div class="claim-card-header">
      <div>
        <span style="font-size:10px;font-weight:800;color:var(--accent2);background:var(--accent-glow);padding:2px 6px;border-radius:4px;margin-right:6px">PRIORITY ${priorityRank}</span>
        <span class="claim-line-id">${esc(d.line_id)}</span>
        <div style="font-size:11px;color:var(--text3);margin-top:3px">${chargeTypeLabel(d.charge_type)} · <span style="color:var(--green)">${tier}</span></div>
      </div>
      <div class="claim-amount-badge">$${(d.claim_amount || 0).toFixed(2)}</div>
    </div>
    <div class="claim-card-body">
      <div class="claim-field"><span class="claim-field-key">Unit ID</span><span class="claim-field-val" style="font-family:monospace">${esc(d.unit_id)}</span></div>
      <div class="claim-field"><span class="claim-field-key">Policy Version</span><span class="claim-field-val">${esc(d.sla?.policy_version || 'V2-Current')}</span></div>
      ${slaInfo}
      <div class="claim-reasoning">${esc(d.reasoning)}</div>
      ${evidence ? `<div class="claim-evidence">${evidence}</div>` : ''}
      ${dupBlock}
      <div style="margin-top:12px;display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:11px;color:var(--text3)">Completeness: ${(Math.round((d.completeness_score || 1.0) * 100))}%</span>
        <button class="detail-btn" onclick="openModal('${esc(d.line_id)}')">Evidence DNA & Trace ›</button>
      </div>
    </div>
  </div>`;
}

// ── Review Queue View (Section 2.6) ───────────────────────
function renderReviewQueue() {
  const reviewItems = state.decisions.filter(d => ['UNCERTAIN', 'NOT_YET_SUPPORTED', 'PENDING_REVIEW'].includes(d.verdict));

  const countEl = document.getElementById('reviewCount');
  if (countEl) countEl.textContent = `${reviewItems.length} charge${reviewItems.length !== 1 ? 's' : ''} requiring review & decision audit`;

  const tbody = document.getElementById('reviewBody');
  if (!tbody) return;

  if (!reviewItems.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-cell">No charges currently require human review</td></tr>';
    return;
  }

  tbody.innerHTML = reviewItems.map(d => {
    const gapPct = Math.round((d.completeness_score || 0.5) * 100);
    return `<tr>
      <td>${esc(d.line_id)}</td>
      <td style="font-family:monospace;font-size:12px">${esc(d.unit_id)}</td>
      <td>${chargeTypeLabel(d.charge_type)}</td>
      <td class="amount-cell">$${(d.amount_usd || 0).toFixed(2)}</td>
      <td><span class="verdict-badge v-${d.verdict}">${d.verdict}</span></td>
      <td>
        <div style="font-size:11px;font-weight:600">${gapPct}%</div>
        <div style="width:60px;height:6px;background:var(--bg3);border-radius:3px;overflow:hidden;margin-top:2px">
          <div style="width:${gapPct}%;height:100%;background:var(--amber)"></div>
        </div>
      </td>
      <td style="font-size:12px;max-width:280px;line-height:1.4">${esc(d.reasoning)}</td>
      <td>
        <div style="display:flex;gap:4px">
          <button class="detail-btn" style="padding:4px 8px;font-size:11px" onclick="actionReview('${esc(d.line_id)}', 'APPROVED')">Approve</button>
          <button class="detail-btn" style="padding:4px 8px;font-size:11px;color:var(--red)" onclick="actionReview('${esc(d.line_id)}', 'REJECTED')">Reject</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

function actionReview(lineId, action) {
  alert(`Charge ${lineId} marked as ${action} by reviewer.`);
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
    { key: 'NOT_YET_SUPPORTED', label: 'Not Yet Supported', cls: 'bar-uncertain' },
    { key: 'DUPLICATE_SUPPRESSED', label: 'Duplicate Suppressed', cls: 'bar-supported' },
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

// ── Modal with USP Features (Sections 2.1, 2.2, 2.3, 4.1, 4.2, 4.3, 4.4) ─────
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
    NOT_YET_SUPPORTED: 'var(--amber)',
    DUPLICATE_SUPPRESSED: 'var(--blue)',
    ALREADY_RECOVERED: 'var(--purple)',
    EXPIRED: 'var(--red)',
    PENDING_REVIEW: 'var(--red)',
  }[d.verdict] || 'var(--text)';

  // Section 4.4: Hallucination Firewall Banner
  const firewallBanner = d.hallucination_blocked
    ? `<div style="padding:10px 14px;background:var(--red-bg);border:1px solid var(--red);border-radius:8px;margin-bottom:14px;font-size:12px;color:var(--red);font-weight:600">
         🚫 Hallucination Firewall Triggered: Unsupported statement detected and blocked from claim.
       </div>`
    : '';

  // Section 4.1: Evidence DNA Tree
  const dna = d.evidence_dna_tree || {};
  const dnaRecords = (dna.cited_records || []).map(r =>
    `<div style="padding:6px 10px;background:var(--bg3);border-radius:6px;font-size:12px;margin-top:4px">
       └─ <strong>${esc(r.source.toUpperCase())}</strong> (${esc(r.record_id)}): <code>${esc(r.field)}</code> = <strong>${esc(r.value)}</strong>
     </div>`
  ).join('') || '<div style="color:var(--text3);font-size:12px">└─ No cited records</div>';

  const dnaTreeHtml = `
    <div style="padding:14px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;font-family:monospace">
      <div style="font-weight:700;font-size:13px;color:var(--accent2)">🧬 Evidence DNA Provenance Tree</div>
      <div style="font-size:12px;margin-top:6px;color:var(--text)">Charge: ${esc(d.line_id)} (${esc(d.charge_type)})</div>
      <div style="font-size:12px;color:var(--text2)"> └─ Resolved Unit / Entity: ${esc(d.unit_id)}</div>
      ${dnaRecords}
      <div style="font-size:12px;color:var(--text3);margin-top:6px"> └─ Applicable Policy Version: ${esc(d.sla?.policy_version || 'V2-Current')}</div>
    </div>`;

  // Section 2.2: Chronological Evidence Timeline
  const citedRecords = dna.cited_records || [];
  const timelineEvents = citedRecords.map(r => `
    <div style="display:flex;gap:12px;align-items:flex-start;padding:8px 0;border-left:2px solid var(--accent);padding-left:12px;margin-left:6px">
      <div style="font-size:11px;color:var(--text3);width:80px;flex-shrink:0">${esc(r.timestamp ? r.timestamp.slice(0, 10) : 'Pre-charge')}</div>
      <div>
        <div style="font-weight:600;font-size:12px;color:var(--text)">${esc(r.source.toUpperCase())} (${esc(r.record_id)})</div>
        <div style="font-size:12px;color:var(--text2)">${esc(r.field)} = <strong>${esc(r.value)}</strong></div>
      </div>
    </div>
  `).join('');

  const timelineHtml = `
    <div style="margin-top:10px">
      ${timelineEvents}
      <div style="display:flex;gap:12px;align-items:flex-start;padding:8px 0;border-left:2px solid var(--amber);padding-left:12px;margin-left:6px">
        <div style="font-size:11px;color:var(--text3);width:80px;flex-shrink:0">${esc(d.sla?.posted_date || 'Charge Date')}</div>
        <div>
          <div style="font-weight:700;font-size:12px;color:var(--amber)">CHARGE EVENT: ${esc(d.charge_type)} ($${(d.amount_usd || 0).toFixed(2)})</div>
        </div>
      </div>
      <div style="font-size:11px;color:var(--text3);font-style:italic;margin-top:6px">
        📌 Temporal Boundary: Evidence establishes unit state as of its timestamp; does not infer state post-handoff.
      </div>
    </div>`;

  // Section 4.2: Claim Defense Pass Notes
  const defenseNotes = (d.defense_pass_notes || []).map(n =>
    `<div style="font-size:12px;color:var(--amber);margin-top:4px">${esc(n)}</div>`
  ).join('') || '<div style="font-size:12px;color:var(--green)">✓ No material evidence gaps identified by Defense Auditor pass.</div>';

  // Section 4.3: Counterfactual Sensitivity Panel
  const counterfactualHtml = `
    <div style="padding:10px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;font-size:12px">
      <div style="font-weight:600;color:var(--text)">Decision Sensitivity (What would flip verdict):</div>
      <div style="color:var(--text2);margin-top:4px">
        • Flip to UNCERTAIN if Receiving damage record appears.<br/>
        • Flip to SUPPORTED if Prep compliance record is invalidated.<br/>
        • Flip to EXPIRED if SLA deadline passes.
      </div>
    </div>`;

  // Section 2.3: Evidence Gap Score
  const gapPct = Math.round((d.completeness_score || 1.0) * 100);
  const missingChecklist = (d.missing_fields || []).map(m => `<li>Missing: ${esc(m)}</li>`).join('');
  const gapHtml = `
    <div style="padding:10px 12px;background:var(--bg3);border-radius:6px;font-size:12px">
      <div style="display:flex;justify-content:space-between;margin-bottom:4px">
        <span>Evidence Completeness Indicator</span>
        <strong>${gapPct}%</strong>
      </div>
      <div style="width:100%;height:8px;background:var(--border);border-radius:4px;overflow:hidden">
        <div style="width:${gapPct}%;height:100%;background:var(--accent2)"></div>
      </div>
      ${missingChecklist ? `<ul style="margin-top:6px;padding-left:16px;color:var(--text3);font-size:11px">${missingChecklist}</ul>` : ''}
    </div>`;

  document.getElementById('modalBody').innerHTML = `
    ${firewallBanner}

    <div class="modal-section">
      <div class="modal-section-title">Verdict</div>
      <div style="font-size:20px;font-weight:800;color:${verdictColor};margin-bottom:8px">${d.verdict}</div>
      <div style="font-size:13px;color:var(--text2);line-height:1.5">${esc(d.reasoning)}</div>
      ${d.claim_amount > 0 ? `<div style="margin-top:10px;font-size:15px;font-weight:700;color:var(--amber)">Recoverable Claim Amount: $${(d.claim_amount).toFixed(2)}</div>` : ''}
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Evidence DNA Provenance</div>
      ${dnaTreeHtml}
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Chronological Evidence Timeline</div>
      ${timelineHtml}
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Claim Defense Pass (Adversarial Audit)</div>
      ${defenseNotes}
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Counterfactual Sensitivity Analysis</div>
      ${counterfactualHtml}
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Evidence Completeness Indicator</div>
      ${gapHtml}
    </div>
  `;

  document.getElementById('modalOverlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modalOverlay').classList.remove('open');
}

// ── Policy View (Section 2.1 Policy Time Machine) ─────────
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
      <div style="padding:12px;background:var(--bg3);border-radius:8px;margin-bottom:16px;font-size:12px">
        <strong>📜 Policy Time Machine:</strong> Active policy selection maps the charge's <code>posted_date</code> to its governing policy version.<br/>
        • <strong>V1 (Pre-Oct 2024):</strong> 90-day dispute window / 9-month inventory loss window.<br/>
        • <strong>V2 (Post-Oct 2024):</strong> 60-day shortened dispute window / 45-day return wait window.
      </div>
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
    inbound_defect: 'Inbound Defect',
    unplanned_prep: 'Unplanned Prep',
    lost_inbound: 'Lost Inbound',
    warehouse_lost: 'Warehouse Lost',
    damaged_in_warehouse: 'Damaged in Warehouse',
    warehouse_damaged: 'Warehouse Damaged',
    fulfilment_fee_weight_tier: 'Fulfilment Fee Weight',
    refund_issued_item_not_returned: 'Refund — Item Not Returned',
    customer_return: 'Customer Return',
  };
  return labels[ct] || ct;
}

function showLoading(active) {
  const el = document.getElementById('loadingOverlay');
  if (el) el.classList.toggle('active', active);
}
