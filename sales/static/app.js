"use strict";
// Sales Engine console - vanilla JS over /api/sales.

const API = "/api/sales";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmtDate = (v) => (v ? new Date(v).toLocaleString() : "—");
const ago = (v) => {
  if (!v) return "never";
  const s = (Date.now() - new Date(v)) / 1000;
  if (s < 90) return "just now";
  if (s < 5400) return Math.round(s / 60) + "m ago";
  if (s < 129600) return Math.round(s / 3600) + "h ago";
  return Math.round(s / 86400) + "d ago";
};
const csv = (s) => (s || "").split(",").map((x) => x.trim()).filter(Boolean);

let TOKEN = (() => { try { return localStorage.getItem("salesToken") || ""; } catch (_) { return ""; } })();

async function api(method, path, body, raw) {
  const opt = { method, headers: {} };
  if (TOKEN) opt.headers.Authorization = "Bearer " + TOKEN;
  if (body !== undefined) {
    if (raw) opt.body = body;
    else {
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(body);
    }
  }
  const r = await fetch(API + path, opt);
  if (r.status === 401) {
    const t = prompt("This server needs its SALES_API_TOKEN:");
    if (t) {
      TOKEN = t.trim();
      try { localStorage.setItem("salesToken", TOKEN); } catch (_) {}
      return api(method, path, body, raw);
    }
  }
  if (r.status === 204) return null;
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new Error((data && (data.detail || data.error)) || r.statusText);
  return data;
}

function toast(msg, ms = 3500) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

async function guard(fn) {
  try {
    return await fn();
  } catch (e) {
    toast("Error: " + e.message, 6000);
  }
}

async function waitJob(job, label) {
  toast(label + " started…");
  for (let i = 0; i < 600; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const j = await api("GET", "/jobs/" + job.job).catch(() => null);
    if (j && j.status !== "running") {
      if (j.status === "failed") toast(label + " failed: " + j.error, 8000);
      else toast(label + " done");
      return j;
    }
  }
}

function drawer(html) {
  closeDrawer();
  const d = document.createElement("div");
  d.className = "drawer";
  d.id = "drawer";
  d.innerHTML = '<button class="btn close" onclick="closeDrawer()">Close</button>' + html;
  document.body.appendChild(d);
  return d;
}
function closeDrawer() {
  const d = $("#drawer");
  if (d) d.remove();
}
window.closeDrawer = closeDrawer;

const stateChip = (s) => {
  const cls = { sent: "good", accepted: "good", answered: "good", delivered: "good", manual: "warn", pending: "warn", failed: "bad", skipped: "" }[s] ?? "";
  return `<span class="chip ${cls}">${esc(s)}</span>`;
};

let META = null;
let SEATS = { linkedin: [], email: [] };
let LISTS = [];

// ------------------------------------------------------------------ pages --
const pages = {};

pages.overview = async (m) => {
  const o = await api("GET", "/overview");
  const k = (v, l) => `<div class="card kpi"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`;
  const recent = await api("GET", "/contacts?limit=8");
  m.innerHTML = `
    <h1>Overview</h1><div class="sub">Source agents find leads into lists; campaigns reach out; replies land in the unibox.</div>
    <div class="grid kpis">
      ${k(o.contacts, "Leads")}${k(o.leads_7d, "Leads · 7 days")}${k(o.agents_active + "/" + o.agents, "Agents running")}
      ${k(o.campaigns_active + "/" + o.campaigns, "Campaigns active")}${k(o.contacted, "Contacted")}${k(o.replied, "Replied")}
      ${k(o.manual_tasks, "Manual tasks")}${k(o.unread_threads, "Unread threads")}
    </div>
    <div class="grid" style="grid-template-columns: 1fr 2fr">
      <div class="card"><h2>Leads by signal</h2>
        ${o.intent_counts.length ? `<table>${o.intent_counts.map((r) => `<tr><td>${esc(r.intent_type)}</td><td class="score">${r.count}</td></tr>`).join("")}</table>` : '<div class="muted">No leads yet.</div>'}
      </div>
      <div class="card"><h2>Newest leads</h2>${leadTable(recent.items)}</div>
    </div>`;
  bindLeadRows(m);
};

function leadTable(items) {
  if (!items.length) return '<div class="muted">Nothing here yet.</div>';
  return `<table><tr><th>Name</th><th>Title · Company</th><th>Signal</th><th>Score</th><th>Found</th></tr>
    ${items.map((c) => `<tr class="click" data-contact="${c.id}">
      <td>${esc(c.full_name)}${c.rejected ? ' <span class="chip bad">rejected</span>' : ""}</td>
      <td>${esc(c.job_title || c.headline || "")}<div class="muted small">${esc(c.company || "")}</div></td>
      <td><span class="chip">${esc(c.intent_type || "")}</span></td>
      <td class="score">${c.total_score != null ? Number(c.total_score).toFixed(2) : "—"}</td>
      <td class="muted small">${ago(c.created_at)}</td></tr>`).join("")}</table>`;
}

function bindLeadRows(root) {
  $$("[data-contact]", root).forEach((tr) => tr.addEventListener("click", () => openContact(tr.dataset.contact)));
}

async function openContact(id) {
  const c = await api("GET", "/contacts/" + id);
  const s = c.scoring || {};
  const d = drawer(`
    <h1>${esc(c.full_name)}</h1>
    <div class="sub">${esc(c.headline || c.job_title || "")}</div>
    <div class="row">${c.profile_url ? `<a class="btn" target="_blank" href="${esc(c.profile_url)}">LinkedIn ↗</a>` : ""}
      <button class="btn" id="en-email">Find email</button><button class="btn" id="en-phone">Find phone</button>
      ${c.rejected ? '<button class="btn" id="unrej">Un-reject</button>' : '<button class="btn danger" id="rej">Reject</button>'}</div>
    <div class="card" style="margin-top:14px"><table>
      <tr><td class="muted">Company</td><td>${esc(c.company || "—")} ${c.website ? `<span class="muted">(${esc(c.website)})</span>` : ""}</td></tr>
      <tr><td class="muted">Location</td><td>${esc(c.location || "—")}</td></tr>
      <tr><td class="muted">Email</td><td>${esc(c.email || "—")} ${c.email ? `<span class="chip">${esc(c.email_status)}</span>` : ""}</td></tr>
      <tr><td class="muted">Phone</td><td>${esc(c.phone || "—")}</td></tr>
      <tr><td class="muted">Signal</td><td><span class="chip">${esc(c.intent_type)}</span> ${esc(c.signal_value || "")}
        ${c.intent_url ? `<a target="_blank" href="${esc(c.intent_url)}">source ↗</a>` : ""}<div class="small">${esc(c.intent || "")}</div></td></tr>
      <tr><td class="muted">Score</td><td class="score">${c.total_score != null ? Number(c.total_score).toFixed(2) + " / 3" : "—"}
        <div class="small muted">persona ${s.persona ?? "—"} · company ${s.company ?? "—"} · intent ${s.intent ?? "—"}</div>
        <div class="small">${esc(s.reason || "")}</div></td></tr>
    </table></div>
    <h2 style="margin-top:18px">Campaign status</h2>
    ${c.campaign_status.length ? `<table>${c.campaign_status.map((r) => `<tr><td>#${r.step_number} ${esc(r.type)}</td><td>${stateChip(r.state)}</td><td class="small muted">${r.done_at ? fmtDate(r.done_at) : r.due_at ? "due " + fmtDate(r.due_at) : ""}</td></tr>`).join("")}</table>` : '<div class="muted">Not in any campaign yet.</div>'}
    <h2 style="margin-top:18px">Conversations</h2>
    ${c.threads.length ? c.threads.map((t) => `<div class="small">${esc(t.channel)} · ${esc(t.last_message_preview || "")}</div>`).join("") : '<div class="muted">No messages.</div>'}
  `);
  const reload = () => openContact(id);
  $("#en-email", d).onclick = () => guard(async () => { await waitJob(await api("POST", `/contacts/${id}/enrich-email`), "Email search"); reload(); });
  $("#en-phone", d).onclick = () => guard(async () => { await waitJob(await api("POST", `/contacts/${id}/enrich-phone`), "Phone search"); reload(); });
  if ($("#rej", d)) $("#rej", d).onclick = () => guard(async () => { await api("POST", `/contacts/${id}/reject`, { reason: "manual" }); reload(); });
  if ($("#unrej", d)) $("#unrej", d).onclick = () => guard(async () => { await api("POST", `/contacts/${id}/unreject`); reload(); });
}

// ---------------------------------------------------------------- agents --
pages.agents = async (m) => {
  const agents = await api("GET", "/agents");
  m.innerHTML = `
    <div class="row spread"><div><h1>Agents</h1><div class="sub">Each agent sources leads into a list; its campaign reaches out to that list.</div></div>
      <button class="btn primary" id="new-agent">New agent</button></div>
    <div class="card">${agents.length ? `<table>
      <tr><th>Agent</th><th>Type</th><th>Signals</th><th>Leads</th><th>Outreach</th><th>Last run</th><th></th></tr>
      ${agents.map((a) => `<tr class="click" data-agent="${a.id}">
        <td><b>${esc(a.name)}</b><div class="muted small">min score ${a.min_lead_score} · every ${a.run_interval_minutes}m</div></td>
        <td>${esc(a.agent_type)}</td>
        <td>${(a.variables || []).filter((v) => v.enabled !== false).length}/${(a.variables || []).length}</td>
        <td class="score">${a.leads_found}</td>
        <td>${a.list_campaign_id ? `<span class="chip good">campaign #${a.list_campaign_id}</span>` : '<span class="chip warn">no campaign</span>'}</td>
        <td class="muted small">${ago(a.last_run)}</td>
        <td>${a.paused ? '<span class="chip">paused</span>' : '<span class="chip good">running</span>'}</td></tr>`).join("")}</table>`
      : '<div class="muted">No agents yet - create one to start finding leads.</div>'}</div>`;
  $("#new-agent").onclick = newAgentWizard;
  $$("[data-agent]", m).forEach((tr) => tr.addEventListener("click", () => openAgent(tr.dataset.agent)));
};

async function openAgent(id) {
  const [a, logs] = await Promise.all([api("GET", "/agents/" + id), api("GET", `/agents/${id}/logs`)]);
  const vars = a.variables || [];
  const d = drawer(`
    <h1>${esc(a.name)}</h1><div class="sub">${esc(a.agent_type)} agent · list #${a.list_id ?? "—"} ${a.list_campaign_id ? "· campaign #" + a.list_campaign_id : "· no campaign (leads won't be contacted)"}</div>
    <div class="row"><button class="btn primary" id="run">Run now</button>
      <button class="btn" id="pause">${a.paused ? "Resume" : "Pause"}</button>
      <button class="btn" onclick="location.hash='leads?agent=${a.id}';closeDrawer()">See leads</button>
      <button class="btn danger" id="del">Delete</button></div>
    ${a.tracking_script ? `<h2 style="margin-top:16px">Tracking script</h2><div class="small muted">Paste on every page of your site ${a.script_installed ? '<span class="chip good">installed</span>' : '<span class="chip warn">not seen yet</span>'}</div><pre class="code">${esc(a.tracking_script)}</pre>` : ""}
    <h2 style="margin-top:16px">ICP</h2>
    <div class="small"><b>Titles:</b> ${esc((a.target_job_titles || []).join(", "))}<br><b>Industries:</b> ${esc((a.target_industries || []).join(", "))}<br>
      <b>Sizes:</b> ${esc((a.target_company_sizes || []).join(", "))} · <b>Locations:</b> ${esc((a.target_locations || []).join(", "))}<br>
      <b>Ignored:</b> ${esc((a.ignored_companies || []).join(", ") || "—")} · <b>Must mention:</b> ${esc((a.mandatory_keywords || []).join(", ") || "—")}</div>
    <h2 style="margin-top:16px">Signals</h2>
    <table>${vars.map((v, i) => `<tr><td><input type="checkbox" data-var="${i}" ${v.enabled !== false ? "checked" : ""}></td>
      <td><b>${esc(v.type)}</b><div class="small muted">${esc(v.value)}</div></td>
      <td class="small">${v.strength ? `<span class="chip">${esc(v.strength)}</span>` : ""}</td>
      <td class="small muted">${v.last_usage ? ago(v.last_usage) + " · " + (v.nb_results_last_launch ?? 0) + " leads" : "not run"}</td></tr>`).join("")}</table>
    <h2 style="margin-top:16px">Run log</h2>
    ${logs.length ? `<table><tr><th>When</th><th>Signal</th><th>Found</th><th>Dup</th><th>Filtered</th><th>Low</th><th>Imported</th></tr>
      ${logs.map((l) => `<tr><td class="small">${ago(l.started_at)}</td><td class="small">${esc(l.variable_type)}<div class="muted">${esc(l.variable_value || "")}</div>
        ${l.status !== "success" ? `<div>${stateChip(l.status)} <span class="small">${esc(l.error || "")}</span></div>` : ""}</td>
        <td>${l.found}</td><td>${l.duplicates}</td><td>${l.filtered}</td><td>${l.below_score}</td><td class="score">${l.imported}</td></tr>`).join("")}</table>`
      : '<div class="muted">No runs yet.</div>'}`);
  $("#run", d).onclick = () => guard(async () => { await waitJob(await api("POST", `/agents/${id}/run`), "Agent run"); openAgent(id); });
  $("#pause", d).onclick = () => guard(async () => { await api("PATCH", "/agents/" + id, { paused: !a.paused }); openAgent(id); route(); });
  $("#del", d).onclick = () => guard(async () => { if (confirm("Delete this agent? Its leads stay.")) { await api("DELETE", "/agents/" + id); closeDrawer(); route(); } });
  $$("[data-var]", d).forEach((cb) => cb.addEventListener("change", () => guard(async () => {
    vars[cb.dataset.var].enabled = cb.checked;
    await api("PATCH", "/agents/" + id, { variables: vars });
    toast("Signals saved");
  })));
}

const DEFAULT_STEPS = [
  { type: "invitation", like_posts_before_invitation: true, delay_after_last_step: 1 },
  { type: "message", message_mode: "ai", delay_after_last_step: 3 },
  { type: "email", message_mode: "ai", delay_after_last_step: 2 },
  { type: "visitProfile", delay_after_last_step: 2 },
  { type: "message", message_mode: "ai", delay_after_last_step: 1 },
  { type: "email", message_mode: "ai", delay_after_last_step: 3 },
  { type: "message", message_mode: "ai", delay_after_last_step: 2 },
];

function signalRow(v = {}) {
  const opts = META.signals.map((s) => `<option ${s.type === v.type ? "selected" : ""} value="${s.type}">${s.type}</option>`).join("");
  return `<div class="row sig"><select class="sig-type">${opts}</select><input class="sig-val" placeholder="value (keyword / URL / true)" value="${esc(v.value || "")}" style="flex:1"><button class="btn sig-del" type="button">×</button></div>`;
}

async function newAgentWizard() {
  const sizes = META.company_sizes.map((s) => `<label class="row"><input type="checkbox" name="size" value="${s}" ${["2-10", "11-50", "51-200"].includes(s) ? "checked" : ""}> ${s}</label>`).join("");
  const types = META.company_types.filter((t) => t !== "All company types").map((t) => `<label class="row"><input type="checkbox" name="ctype" value="${t}" ${["Startup", "Private Company"].includes(t) ? "checked" : ""}> ${t}</label>`).join("");
  const d = drawer(`
    <h1>New agent</h1><div class="sub">Creates a list, a source agent and an (inactive) campaign - the full cycle.</div>
    <form id="wiz" class="grid">
      <div class="card grid">
        <h2>1 · Who you sell to</h2>
        <div class="row"><input name="site" placeholder="your website, e.g. acme.com" style="flex:1"><button class="btn" type="button" id="gen">Build ICP from site</button></div>
        <label>Agent name<input name="name" required placeholder="Founders · Australia · SaaS"></label>
        <label>Job titles<input name="titles" placeholder="Founder, CEO, CTO"></label>
        <label>Industries<input name="industries" placeholder="Software Development & SaaS, Fintech"></label>
        <label>Locations<input name="locations" placeholder="Australia, United Kingdom"></label>
        <div><div class="small muted">Company size</div><div class="row">${sizes}</div></div>
        <div><div class="small muted">Company type</div><div class="row">${types}</div></div>
        <label>Ignore companies<input name="ignored" placeholder="competitors, existing clients"></label>
        <label>Must mention (optional)<input name="mandatory" placeholder="AI, automation"></label>
      </div>
      <div class="card grid">
        <h2>2 · Signals</h2>
        <div class="row"><label>Type<select name="agent_type"><option>autopilot</option><option>lookalike</option><option value="website-visitor">website-visitor</option></select></label>
          <label>Min score (0-1)<input name="min" type="number" step="0.05" min="0" max="1" value="0.6"></label>
          <label>Leads / run<input name="per_run" type="number" value="25"></label>
          <label>Every (min)<input name="interval" type="number" value="240"></label></div>
        <div id="sigs" class="grid">${[
          { type: "SEARCH_KEYWORD", value: "" }, { type: "SEARCH_KEYWORD_COMMENT", value: "" },
          { type: "RECENT_ACTIVITY", value: "true" }, { type: "RECENTLY_CHANGED_JOB", value: "true" },
        ].map(signalRow).join("")}</div>
        <button class="btn" type="button" id="add-sig">+ signal</button>
        <div class="small muted">Autopilot agents need 4-15 signals. Keyword signals: what your buyers post about.</div>
        <label class="row"><input type="checkbox" name="exclude_sp" checked> Exclude service providers</label>
        <label class="row"><input type="checkbox" name="otw"> Include open-to-work profiles</label>
      </div>
      <div class="card grid">
        <h2>3 · Outreach</h2>
        <label>What you offer<textarea name="offer" placeholder="One paragraph - the AI writes every message from this."></textarea></label>
        <div class="row"><label>Tone<select name="tone"><option>conversational</option><option>professional</option><option>friendly</option></select></label>
          <label>Goal<select name="goal"><option value="demos">book demos</option><option value="warm">warm conversations</option></select></label>
          <label>Sender name<input name="sender"></label><label>Launch hour<input name="hour" type="number" min="0" max="23" value="9"></label></div>
        <label>LinkedIn seat<select name="li_seat"><option value="">— none —</option>${SEATS.linkedin.map((s) => `<option value="${s.id}">${esc(s.name)}${s.automation_enabled ? "" : " (manual)"}</option>`).join("")}</select></label>
        <label>Email seat<select name="email_seat"><option value="">— none —</option>${SEATS.email.map((s) => `<option value="${s.id}">${esc(s.email)}</option>`).join("")}</select></label>
        <label class="row"><input type="checkbox" name="manual"> Manual campaign (every step becomes a task for you)</label>
        <label>Sequence (JSON)<textarea name="steps" style="min-height:160px;font-family:monospace;font-size:12px">${esc(JSON.stringify(DEFAULT_STEPS, null, 1))}</textarea></label>
      </div>
      <button class="btn primary">Create agent</button>
    </form>`);
  const f = $("#wiz", d);
  $("#add-sig", d).onclick = () => $("#sigs", d).insertAdjacentHTML("beforeend", signalRow());
  $("#sigs", d).addEventListener("click", (e) => { if (e.target.classList.contains("sig-del")) e.target.closest(".sig").remove(); });
  $("#gen", d).onclick = () => guard(async () => {
    toast("Reading the site…");
    const icp = await api("POST", "/icp/from-site", { url: f.site.value });
    f.titles.value = (icp.job_roles || []).join(", ");
    f.industries.value = (icp.industries || []).join(", ");
    f.locations.value = (icp.locations || []).join(", ");
    f.ignored.value = (icp.excluded_keywords || []).join(", ");
    $$("[name=size]", f).forEach((c) => (c.checked = (icp.company_sizes || []).some((s) => s.startsWith(c.value.split("-")[0] + "-") || s.startsWith(c.value))));
    $$("[name=ctype]", f).forEach((c) => (c.checked = (icp.company_types || []).includes(c.value)));
    if (!f.name.value) f.name.value = [(icp.job_roles || [])[0], (icp.locations || [])[0], (icp.industries || [])[0]].filter(Boolean).join(" · ");
    toast("ICP drafted - review it");
  });
  f.onsubmit = (e) => {
    e.preventDefault();
    guard(async () => {
      const agentType = f.agent_type.value;
      const variables = agentType === "autopilot" ? $$(".sig", f).map((r) => ({ type: $(".sig-type", r).value, value: $(".sig-val", r).value.trim() })).filter((v) => v.value) : [];
      const email = f.email_seat.value ? [Number(f.email_seat.value)] : [];
      const res = await api("POST", "/full-cycle", {
        name: f.name.value,
        agent: {
          agent_type: agentType, variables,
          target_job_titles: csv(f.titles.value), target_industries: csv(f.industries.value),
          target_locations: csv(f.locations.value),
          target_company_sizes: $$("[name=size]:checked", f).map((c) => c.value),
          target_company_types: $$("[name=ctype]:checked", f).map((c) => c.value),
          ignored_companies: csv(f.ignored.value), mandatory_keywords: csv(f.mandatory.value),
          min_lead_score: Number(f.min.value), leads_per_run: Number(f.per_run.value),
          run_interval_minutes: Number(f.interval.value),
          exclude_service_providers: f.exclude_sp.checked, include_open_to_work_profiles: f.otw.checked,
        },
        campaign: {
          steps: JSON.parse(f.steps.value), offer: f.offer.value || null, tone: f.tone.value, goal: f.goal.value,
          sender_name: f.sender.value || null, launch_hour: Number(f.hour.value),
          linkedin_seat_id: f.li_seat.value ? Number(f.li_seat.value) : null, email_seat_ids: email,
          is_manual: f.manual.checked,
        },
      });
      toast(`Agent #${res.agent.id} + campaign #${res.campaign.id} created (campaign is paused until you activate it)`, 6000);
      closeDrawer();
      route();
    });
  };
}

// ------------------------------------------------------------- campaigns --
pages.campaigns = async (m) => {
  const cs = await api("GET", "/campaigns");
  m.innerHTML = `<h1>Campaigns</h1><div class="sub">Outreach sequences. Created paused - activate when you're happy with them.</div>
    <div class="card">${cs.length ? `<table><tr><th>Campaign</th><th>Steps</th><th>Contacts</th><th>Contacted</th><th>Replies</th><th>Accept rate</th><th>Status</th></tr>
      ${cs.map((c) => `<tr class="click" data-camp="${c.id}"><td><b>${esc(c.name)}</b><div class="small muted">${esc(c.goal)} · ${esc(c.tone)}${c.is_manual ? " · manual" : ""}</div></td>
        <td>${(c.steps || []).length}</td><td>${c.stats.contacts}</td><td>${c.stats.contacted}</td>
        <td class="score">${c.stats.answered} <span class="muted small">(${(c.stats.reply_rate * 100).toFixed(1)}%)</span></td>
        <td>${(c.stats.acceptance_rate * 100).toFixed(0)}%</td>
        <td>${c.active ? '<span class="chip good">active</span>' : '<span class="chip">paused</span>'}</td></tr>`).join("")}</table>`
      : '<div class="muted">No campaigns yet. Creating an agent creates its campaign.</div>'}</div>`;
  $$("[data-camp]", m).forEach((tr) => tr.addEventListener("click", () => openCampaign(tr.dataset.camp)));
};

async function openCampaign(id) {
  const c = await api("GET", "/campaigns/" + id);
  const st = c.stats;
  const byStep = {};
  st.by_step.forEach((r) => ((byStep[r.step_number] ||= {})[r.state] = r.n));
  const d = drawer(`
    <h1>${esc(c.name)}</h1><div class="sub">lists ${esc(c.list_ids.join(", "))} · launch ${c.launch_hour}:00 · skip DMs after ${c.skip_invitation_after_days}d without acceptance</div>
    <div class="row"><button class="btn primary" id="toggle">${c.active ? "Pause" : "Activate"}</button>
      <button class="btn" id="tick">Run now</button><button class="btn danger" id="del">Delete</button></div>
    ${!c.active ? "" : '<div class="small muted" style="margin-top:6px">Active: the scheduler runs due steps on active days from the launch hour.</div>'}
    <div class="grid kpis" style="margin-top:14px">
      <div class="card kpi"><div class="v">${st.contacts}</div><div class="l">Contacts</div></div>
      <div class="card kpi"><div class="v">${st.contacted}</div><div class="l">Contacted</div></div>
      <div class="card kpi"><div class="v">${st.answered}</div><div class="l">Replied</div></div>
      <div class="card kpi"><div class="v">${st.manual_tasks_open}</div><div class="l">Manual tasks</div></div></div>
    <h2>Sequence</h2>
    <div class="steps">${c.steps.map((s) => `<div class="step"><div class="n">${s.step_number + 1}</div>
      <div><b>${esc(s.type)}</b> ${s.message_mode ? `<span class="chip">${esc(s.message_mode)}</span>` : ""}
        <div class="small muted">${s.step_number ? `${s.delay_after_last_step} day(s) after previous` : "first touch"}${s.like_posts_before_invitation ? " · likes a post first" : ""}</div>
        ${s.message ? `<div class="small">${esc(s.message)}</div>` : ""}${s.note ? `<div class="small">${esc(s.note)}</div>` : ""}</div>
      <div class="small">${Object.entries(byStep[s.step_number] || {}).map(([k, v]) => stateChip(k) + " " + v).join("<br>")}</div></div>`).join("")}</div>
    <h2 style="margin-top:16px">Edit sequence</h2>
    <textarea id="steps-json" style="min-height:180px;font-family:monospace;font-size:12px">${esc(JSON.stringify(c.steps, null, 1))}</textarea>
    <div class="row" style="margin-top:8px"><button class="btn" id="save-steps">Save sequence</button></div>`);
  $("#toggle", d).onclick = () => guard(async () => {
    if (!c.active && !confirm("Activate? Outreach starts on the next active day at the launch hour.")) return;
    await api("POST", `/campaigns/${id}/${c.active ? "pause" : "activate"}`);
    openCampaign(id); route();
  });
  $("#tick", d).onclick = () => guard(async () => { await waitJob(await api("POST", `/campaigns/${id}/tick?force=true`), "Campaign run"); openCampaign(id); });
  $("#del", d).onclick = () => guard(async () => { if (confirm("Delete campaign?")) { await api("DELETE", "/campaigns/" + id); closeDrawer(); route(); } });
  $("#save-steps", d).onclick = () => guard(async () => { await api("PATCH", "/campaigns/" + id, { steps: JSON.parse($("#steps-json", d).value) }); toast("Saved"); openCampaign(id); });
}

// ----------------------------------------------------------------- leads --
pages.leads = async (m, params) => {
  const q = new URLSearchParams(params);
  q.set("limit", q.get("limit") || "50");
  const res = await api("GET", "/contacts?" + q.toString());
  const intents = (await api("GET", "/intent-counts")).map((r) => r.intent_type);
  m.innerHTML = `<h1>Leads</h1><div class="sub">${res.total} leads</div>
    <form class="row card" id="lf" style="margin-bottom:14px">
      <input name="search" placeholder="search name, company, title…" value="${esc(q.get("search") || "")}" style="flex:1">
      <select name="list_id"><option value="">all lists</option>${LISTS.map((l) => `<option value="${l.id}" ${q.get("list_id") == l.id ? "selected" : ""}>${esc(l.name)} (${l.contact_count})</option>`).join("")}</select>
      <select name="intent_type"><option value="">all signals</option>${intents.map((t) => `<option ${q.get("intent_type") === t ? "selected" : ""}>${t}</option>`).join("")}</select>
      <input name="score_from" type="number" step="0.1" placeholder="min score" value="${esc(q.get("score_from") || "")}" style="width:110px">
      <button class="btn">Filter</button>
      <label class="btn" style="display:inline-flex">Import CSV<input type="file" id="csvf" accept=".csv" hidden></label>
    </form>
    <div class="card">${leadTable(res.items)}</div>`;
  bindLeadRows(m);
  $("#lf").onsubmit = (e) => {
    e.preventDefault();
    const p = new URLSearchParams(new FormData(e.target));
    for (const [k, v] of [...p]) if (!v) p.delete(k);
    if (q.get("agent")) p.set("agent", q.get("agent"));
    location.hash = "leads?" + p.toString();
  };
  $("#csvf").onchange = (e) => guard(async () => {
    const listId = $("#lf").list_id.value || prompt("Import into which list id?", LISTS[0] ? LISTS[0].id : "");
    if (!listId) return;
    const r = await api("POST", `/lists/${listId}/import`, await e.target.files[0].text(), true);
    toast(`Imported: ${r.created} new, ${r.existing} existing, ${r.skipped} skipped`);
    route();
  });
};

// ----------------------------------------------------------------- tasks --
pages.tasks = async (m) => {
  const tasks = await api("GET", "/tasks");
  m.innerHTML = `<h1>Tasks</h1><div class="sub">Steps waiting for you to do by hand: manual campaigns, or LinkedIn steps on a seat without automation.</div>
    ${tasks.length ? tasks.map((t) => `<div class="card" style="margin-bottom:10px" data-task="${t.id}">
      <div class="row spread"><div><b>${esc(t.full_name)}</b> <span class="muted">${esc(t.job_title || "")} · ${esc(t.company || "")}</span>
        <div class="small muted">${esc(t.campaign_name)} · step ${t.step_number + 1}: <b>${esc(t.type)}</b></div></div>
        <div class="row">${t.profile_url && t.type !== "email" ? `<a class="btn" target="_blank" href="${esc(t.profile_url)}">Open profile ↗</a>` : ""}
          ${t.body ? '<button class="btn copy">Copy text</button>' : ""}
          ${t.type.startsWith("invitation") ? '<button class="btn done" data-o="accepted">Already connected</button>' : ""}
          <button class="btn primary done" data-o="sent">Done</button><button class="btn done" data-o="skipped">Skip</button></div></div>
      ${t.subject ? `<div class="small" style="margin-top:8px"><b>Subject:</b> ${esc(t.subject)}</div>` : ""}
      ${t.body ? `<pre class="code" style="margin-top:8px">${esc(t.body)}</pre>` : ""}</div>`).join("")
      : '<div class="card muted">Nothing to do right now.</div>'}`;
  $$("[data-task]", m).forEach((el) => {
    const t = tasks.find((x) => String(x.id) === el.dataset.task);
    const copy = $(".copy", el);
    if (copy) copy.onclick = () => navigator.clipboard.writeText(t.body).then(() => toast("Copied"));
    $$(".done", el).forEach((b) => (b.onclick = () => guard(async () => {
      await api("POST", `/tasks/${t.id}/complete`, { outcome: b.dataset.o });
      el.remove();
      badges();
    })));
  });
};

// ---------------------------------------------------------------- unibox --
pages.unibox = async (m, params) => {
  const q = new URLSearchParams(params);
  const res = await api("GET", "/unibox/threads?limit=100" + (q.get("interested") ? "&interested=" + q.get("interested") : ""));
  m.innerHTML = `<div class="row spread"><div><h1>Unibox</h1><div class="sub">Every LinkedIn and email conversation.</div></div>
    <div class="row"><button class="btn" onclick="location.hash='unibox'">All</button><button class="btn" onclick="location.hash='unibox?interested=true'">Interested</button>
    <button class="btn" id="sync">Sync now</button></div></div>
    <div class="split"><div class="card" style="padding:0;overflow:auto;max-height:75vh">
      ${res.items.map((t) => `<div class="thread ${t.seen ? "" : "unread"}" data-thread="${t.id}">
        <div class="row spread"><span>${esc(t.attendee_full_name || t.attendee_email || "Unknown")}</span><span class="small muted">${ago(t.last_message_at)}</span></div>
        <div class="small muted">${esc(t.channel)} ${t.interested === true ? '<span class="chip good">interested</span>' : t.interested === false ? '<span class="chip">not interested</span>' : ""}</div>
        <div class="small">${esc((t.last_message_preview || "").slice(0, 90))}</div></div>`).join("") || '<div class="thread muted">No conversations yet.</div>'}
    </div><div class="card" id="conv"><div class="muted">Pick a conversation.</div></div></div>`;
  $("#sync").onclick = () => guard(async () => { await waitJob(await api("POST", "/unibox/sync"), "Inbox sync"); route(); });
  $$("[data-thread]", m).forEach((el) => el.addEventListener("click", () => {
    $$(".thread", m).forEach((x) => x.classList.remove("active"));
    el.classList.add("active");
    el.classList.remove("unread");
    openThread(res.items.find((t) => String(t.id) === el.dataset.thread));
  }));
};

async function openThread(t) {
  const { messages } = await api("GET", "/unibox/threads/" + t.id);
  const c = $("#conv");
  c.innerHTML = `<div class="row spread"><div><h2 style="margin:0">${esc(t.attendee_full_name || t.attendee_email)}</h2>
      <div class="small muted">${esc(t.channel)}${t.subject ? " · " + esc(t.subject) : ""}</div></div>
    <div class="row"><button class="btn" data-i="true">Interested</button><button class="btn" data-i="false">Not interested</button>
      ${t.contact_id ? `<button class="btn" id="tc">Lead</button>` : ""}</div></div>
    <div style="margin:12px 0;max-height:52vh;overflow:auto">${messages.map((x) => `<div class="msg ${x.direction}">${esc(x.body)}<div class="small muted">${fmtDate(x.sent_at)}</div></div>`).join("")}</div>
    <textarea id="reply" placeholder="Write a reply…"></textarea>
    <div class="row" style="margin-top:8px"><button class="btn primary" id="send">Send</button></div>`;
  $$("[data-i]", c).forEach((b) => (b.onclick = () => guard(async () => { await api("PATCH", "/unibox/threads/" + t.id, { interested: b.dataset.i === "true" }); toast("Saved"); })));
  if ($("#tc", c)) $("#tc", c).onclick = () => openContact(t.contact_id);
  $("#send", c).onclick = () => guard(async () => {
    const msg = $("#reply", c).value.trim();
    if (!msg) return;
    await api("POST", `/unibox/threads/${t.id}/messages`, { message: msg });
    toast("Sent");
    openThread(t);
  });
}

// ------------------------------------------------------------- directory --
pages.directory = async (m) => {
  m.innerHTML = `<h1>Directory</h1><div class="sub">Search everyone your agents have found, or run a live LinkedIn people search through your seat. Revealing is free.</div>
    <form class="card form" id="df">
      <label>Source<select name="source"><option value="workspace">workspace</option><option value="linkedin">live LinkedIn search</option></select></label>
      <label>Job titles<input name="job_title" placeholder="Head of Marketing, CMO"></label>
      <label>Locations<input name="location" placeholder="Germany"></label>
      <label>Industries (boost)<input name="industry"></label>
      <label>Company<input name="company"></label>
      <label>Name<input name="name"></label>
      <label class="row"><input type="checkbox" name="has_recent_activity"> Active in last 90 days</label>
      <label class="row"><input type="checkbox" name="has_recently_changed_job"> Changed job recently</label>
      <label class="row"><input type="checkbox" name="has_recent_funding_round"> Company raised (12 months)</label>
      <label class="row"><input type="checkbox" name="is_company_hiring"> Company hiring</label>
      <div class="wide"><button class="btn primary">Search</button></div>
    </form>
    <div id="dres" style="margin-top:14px"></div>`;
  $("#df").onsubmit = (e) => {
    e.preventDefault();
    guard(async () => {
      const f = e.target;
      const body = { source: f.source.value, limit: 50 };
      ["job_title", "location", "industry"].forEach((k) => { const v = csv(f[k].value); if (v.length) body[k] = v; });
      ["company", "name"].forEach((k) => { if (f[k].value) body[k] = f[k].value; });
      ["has_recent_activity", "has_recently_changed_job", "has_recent_funding_round", "is_company_hiring"].forEach((k) => { if (f[k].checked) body[k] = true; });
      const r = await api("POST", "/directory/leads/search", body);
      $("#dres").innerHTML = `<div class="card"><div class="row spread"><div>${r.total} results ${r.note ? `<span class="muted">(${esc(r.note)})</span>` : ""}</div>
        <div class="row"><select id="dlist">${LISTS.map((l) => `<option value="${l.id}">${esc(l.name)}</option>`).join("")}</select><button class="btn primary" id="reveal">Reveal + add to list</button></div></div>
        <table><tr><th><input type="checkbox" id="all"></th><th>First name</th><th>Title</th><th>Location</th><th>Industry</th></tr>
        ${r.items.map((x) => `<tr><td><input type="checkbox" class="pick" value="${x.id}"></td><td>${esc(x.first_name)}</td><td>${esc(x.job_title)}</td><td>${esc(x.location)}</td><td>${esc(x.industry)}</td></tr>`).join("")}</table></div>`;
      $("#all").onchange = (ev) => $$(".pick").forEach((c) => (c.checked = ev.target.checked));
      $("#reveal").onclick = () => guard(async () => {
        const ids = $$(".pick:checked").map((c) => (/^\d+$/.test(c.value) ? Number(c.value) : c.value));
        if (!ids.length) return toast("Pick some leads first");
        const out = await api("POST", "/directory/leads/reveal", { ids, list_id: Number($("#dlist").value) || null });
        toast(`Revealed ${out.leads.length}, added ${out.imported} to the list`);
      });
    });
  };
};

// -------------------------------------------------------------- settings --
pages.settings = async (m) => {
  await loadSeats();
  m.innerHTML = `<h1>Settings</h1><div class="sub">Seats are the accounts that send. Daily caps are hard limits.</div>
    <div class="card"><h2>LinkedIn seats</h2>
      <div class="warnbox small">Automating LinkedIn (invites, messages, likes) is against LinkedIn's terms and accounts do get restricted.
        Leave <b>automation</b> off and every LinkedIn step becomes a task you do yourself in one click. Turn it on only for an account you accept that risk for, and keep the caps low.</div>
      <table style="margin-top:10px"><tr><th>Seat</th><th>Session</th><th>Automation</th><th>Daily caps (invite / msg / visit / like)</th><th></th></tr>
      ${SEATS.linkedin.map((s) => `<tr data-li="${s.id}"><td><b>${esc(s.name)}</b><div class="small muted">${esc(s.profile_url || "")}</div></td>
        <td>${s.has_session ? '<span class="chip good">logged in</span>' : '<span class="chip warn">no session</span>'}</td>
        <td><label class="row"><input type="checkbox" class="auto" ${s.automation_enabled ? "checked" : ""}> on</label></td>
        <td><input class="cap" data-k="daily_invitations" value="${s.daily_invitations}" style="width:50px"> <input class="cap" data-k="daily_messages" value="${s.daily_messages}" style="width:50px">
            <input class="cap" data-k="daily_visits" value="${s.daily_visits}" style="width:50px"> <input class="cap" data-k="daily_likes" value="${s.daily_likes}" style="width:50px"></td>
        <td class="row"><button class="btn login">Log in</button><button class="btn save">Save</button></td></tr>`).join("")}</table>
      <form class="row" id="lif" style="margin-top:10px"><input name="name" placeholder="seat name" required><input name="profile_url" placeholder="your linkedin.com/in/ URL" style="flex:1">
        <select name="timezone">${["UTC", "Asia/Karachi", "Australia/Sydney", "Europe/London", "America/New_York"].map((z) => `<option>${z}</option>`).join("")}</select>
        <label class="row"><input type="checkbox" name="sales_navigator"> Sales Navigator</label><button class="btn">Add seat</button></form>
      <div class="small muted" style="margin-top:6px">"Log in" opens a real Chrome window on the machine running the server - sign in by hand; only the session cookies are kept.</div>
    </div>
    <div class="card" style="margin-top:14px"><h2>Email seats</h2>
      <table><tr><th>Mailbox</th><th>Today</th><th>Warm-up</th><th>Tracking</th><th></th></tr>
      ${SEATS.email.map((s) => `<tr data-em="${s.id}"><td><b>${esc(s.email)}</b><div class="small muted">${esc(s.type)} · ${esc(s.smtp_host || "")}</div></td>
        <td>${s.daily_email_count} / ${s.daily_cap_today}</td>
        <td>${s.warmup_enabled ? (s.warmup_completed ? '<span class="chip good">done</span>' : '<span class="chip warn">ramping</span>') : "off"}</td>
        <td class="small">${s.track_opening ? "opens" : "—"} ${s.remove_unsubscribe_link ? "" : "· unsubscribe link"}</td>
        <td class="row"><button class="btn test">Send test</button><button class="btn danger del">Remove</button></td></tr>`).join("")}</table>
      <form class="form" id="emf" style="margin-top:10px">
        <label>Provider<select name="type"><option value="google">Google (app password)</option><option value="outlook">Outlook</option><option value="smtp">Other SMTP</option></select></label>
        <label>Email<input name="email" required></label><label>Sender name<input name="name"></label>
        <label>Password / app password<input name="smtp_pass" type="password" required></label>
        <label>SMTP host (other)<input name="smtp_host"></label><label>IMAP host (other)<input name="imap_host"></label>
        <label>Daily max<input name="daily_email_max" type="number" value="30"></label>
        <label>Signature<input name="signature"></label>
        <div class="wide"><button class="btn primary">Add mailbox</button></div></form>
    </div>`;
  $$("[data-li]", m).forEach((row) => {
    const id = row.dataset.li;
    $(".auto", row).onchange = (e) => guard(async () => {
      if (e.target.checked && !confirm("Turn on LinkedIn automation for this seat? LinkedIn may restrict the account.")) { e.target.checked = false; return; }
      await api("PATCH", "/seats/linkedin/" + id, { automation_enabled: e.target.checked });
      toast("Saved");
    });
    $(".save", row).onclick = () => guard(async () => {
      const body = {};
      $$(".cap", row).forEach((i) => (body[i.dataset.k] = Number(i.value)));
      await api("PATCH", "/seats/linkedin/" + id, body);
      toast("Caps saved");
    });
    $(".login", row).onclick = () => guard(async () => { await waitJob(await api("POST", `/seats/linkedin/${id}/login`), "LinkedIn login"); route(); });
  });
  $("#lif").onsubmit = (e) => { e.preventDefault(); guard(async () => {
    const f = e.target;
    await api("POST", "/seats/linkedin", { name: f.name.value, profile_url: f.profile_url.value || null, timezone: f.timezone.value, sales_navigator: f.sales_navigator.checked });
    route();
  }); };
  $$("[data-em]", m).forEach((row) => {
    const id = row.dataset.em;
    $(".test", row).onclick = () => guard(async () => { const to = prompt("Send a test to:"); if (to) { await api("POST", `/seats/email/${id}/test`, { to }); toast("Test sent"); } });
    $(".del", row).onclick = () => guard(async () => { if (confirm("Remove mailbox?")) { await api("DELETE", "/seats/email/" + id); route(); } });
  });
  $("#emf").onsubmit = (e) => { e.preventDefault(); guard(async () => {
    const body = Object.fromEntries([...new FormData(e.target)].filter(([, v]) => v !== ""));
    body.daily_email_max = Number(body.daily_email_max || 30);
    await api("POST", "/seats/email", body);
    route();
  }); };
};

// ---------------------------------------------------------------- router --
async function loadSeats() {
  [SEATS.linkedin, SEATS.email, LISTS] = await Promise.all([api("GET", "/seats/linkedin"), api("GET", "/seats/email"), api("GET", "/lists")]);
}

async function badges() {
  const o = await api("GET", "/overview").catch(() => null);
  if (!o) return;
  const set = (id, n) => { const b = $(id); b.hidden = !n; b.textContent = n; };
  set("#b-tasks", o.manual_tasks);
  set("#b-unibox", o.unread_threads);
}

async function route() {
  const [page, params] = (location.hash.slice(1) || "overview").split("?");
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  const m = $("#main");
  m.innerHTML = '<div class="muted">Loading…</div>';
  try {
    await (pages[page] || pages.overview)(m, params || "");
  } catch (e) {
    m.innerHTML = `<div class="card"><b>Couldn't load:</b> ${esc(e.message)}</div>`;
  }
  badges();
}

$$("#nav button").forEach((b) => b.addEventListener("click", () => { location.hash = b.dataset.page; }));
window.addEventListener("hashchange", () => { closeDrawer(); route(); });

(async () => {
  META = await api("GET", "/meta");
  await loadSeats().catch(() => {});
  route();
  setInterval(badges, 30000);
})();
