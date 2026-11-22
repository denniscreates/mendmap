// MendMap city dashboard — plain JS, served by the FastAPI backend at /admin.
const API = location.origin; // same server as the API
const CAT_ICON = { pothole: "🕳️", streetlight: "💡", dumping: "🗑️", other: "📍", accessibility: "♿" };
// Why a report scores high on priority (codes come from the API, see backend/app/insights.py).
const REASON = {
  severe: "Severe (AI severity 4–5)",
  many_confirmations: "Many neighbours confirmed it",
  waiting_long: "Waiting more than a week",
  near_school: "Near a school",
  near_hospital: "Near a hospital",
  near_bus_stop: "Near a bus stop",
  accessibility: "Blocks wheelchairs or strollers",
};
const prio = (r) => r.status === "fixed" ? '<span class="muted">—</span>'
  : `<span class="prio ${r.priority >= 70 ? "high" : r.priority >= 45 ? "mid" : "low"}">${r.priority}</span>`;
const STATUS_LABEL = { reported: "Reported", in_progress: "In progress", fixed: "Fixed" };
const STATUS_COLOR = { reported: "#f26a2e", in_progress: "#f5b638", fixed: "#6d95ff" };

const state = {
  token: localStorage.getItem("mm_token"),
  user: JSON.parse(localStorage.getItem("mm_user") || "null"),
  reports: [],
  categories: [],
  sort: { key: "priority", dir: "desc" }, // fix the most urgent first
  view: "list",
};
let map, markersLayer, miniMap;

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmtDate = (d) => new Date(d + (d.endsWith("Z") ? "" : "Z")).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const ago = (d) => {
  const s = (Date.now() - new Date(d + (d.endsWith("Z") ? "" : "Z"))) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
};
const pill = (st) => `<span class="pill ${st}">${STATUS_LABEL[st]}</span>`;
const icon = (cat) => CAT_ICON[cat.icon] || "📍";

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}), ...opts.headers },
  });
  // A 401 on a signed-in request means the token expired; on /auth/login it just means a wrong password.
  if (res.status === 401 && state.token && !path.startsWith("/auth/")) {
    logout();
    throw new Error("Session expired, please sign in again");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  }
  return res.status === 204 ? null : res.json();
}

// ---------- auth ----------
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  $("#login-error").textContent = "";
  try {
    const { token, user } = await api("/auth/login", { method: "POST", body: JSON.stringify({ email: f.get("email"), password: f.get("password") }) });
    if (user.role !== "admin") throw new Error("This account is not a city admin account");
    state.token = token; state.user = user;
    localStorage.setItem("mm_token", token);
    localStorage.setItem("mm_user", JSON.stringify(user));
    start();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

// Demo mode (SEED_DEMO=1): one tap signs judges in as the demo city admin.
api("/auth/demo-accounts").then((list) => {
  const a = list.find((x) => x.role === "admin");
  if (!a) return;
  $("#demo-admin").classList.remove("hidden");
  $("#demo-admin-hint").classList.remove("hidden");
  $("#demo-admin-hint").textContent = `Demo account: ${a.email} / ${a.password}`;
  $("#demo-admin").addEventListener("click", () => {
    const f = $("#login-form");
    f.elements.email.value = a.email;
    f.elements.password.value = a.password;
    f.requestSubmit();
  });
}).catch(() => {});

function logout() {
  state.token = null; state.user = null;
  localStorage.removeItem("mm_token"); localStorage.removeItem("mm_user");
  $("#app").classList.add("hidden");
  $("#login").classList.remove("hidden");
}
$("#logout").addEventListener("click", logout);

// Light / dark theme, remembered in this browser.
document.querySelectorAll("[data-theme-toggle]").forEach((b) =>
  b.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("mm_theme", next);
  }),
);

// ---------- data ----------
async function load() {
  const params = new URLSearchParams();
  if ($("#f-category").value) params.set("category", $("#f-category").value);
  if ($("#f-status").value) params.set("status", $("#f-status").value);
  params.set("limit", "2000");
  state.reports = await api(`/reports?${params}`);
  render();
}

function filtered() {
  const q = $("#f-search").value.trim().toLowerCase();
  let list = state.reports;
  if (q) list = list.filter((r) => `#${r.id}` === q || String(r.id) === q || (r.description || "").toLowerCase().includes(q)
    || r.category.name.toLowerCase().includes(q) || (r.address || "").toLowerCase().includes(q));
  if ($("#f-flagged").checked) list = list.filter((r) => r.flagged || r.fix_ai === "fake" || r.fix_ai === "suspicious");
  const { key, dir } = state.sort;
  const val = (r) => (key === "category" ? r.category.name : r[key]);
  return [...list].sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * (dir === "asc" ? 1 : -1));
}

// ---------- rendering ----------
function render() {
  const list = filtered();
  $("#count").textContent = `${list.length} report${list.length === 1 ? "" : "s"}`;
  if (state.view === "list") renderTable(list);
  if (state.view === "map") renderMap(list);
  if (state.view === "stats") renderStats();
  if (state.view === "fixers") renderFixers();
  if (state.view === "mjeshtrit") renderMjeshtrit();
  else refreshMjBadge();
  if (state.view === "chat") renderChat();
  else refreshChatBadge();
  if (state.view === "bookings") renderBookings();
  else refreshBookingBadge();
  const waiting = state.reports.filter((r) => r.fix_status === "pending").length;
  $("#fix-badge").textContent = waiting;
  $("#fix-badge").classList.toggle("hidden", !waiting);
}

// ---------- neighbour fixes ----------
async function renderFixers() {
  const pending = state.reports.filter((r) => r.fix_status === "pending");
  $("#fix-pending").innerHTML = pending.length ? pending.map((r) => `
    <div class="fix-card">
      <div class="before-after">
        <figure><img class="photo" src="${esc(API + r.photo_url)}" alt="Before"><figcaption class="muted">Before</figcaption></figure>
        <figure><img class="photo" src="${esc(API + r.after_photo_url)}" alt="After"><figcaption class="muted">After</figcaption></figure>
      </div>
      <div>${icon(r.category)} ${esc(r.category.name)} · ${esc(r.neighbourhood || "")} · fixed by ${esc(r.claimed_by_name || "a neighbour")}
        <a href="#" data-open="${r.id}">#${r.id}</a></div>
      <div class="fix-actions">
        <button class="btn primary" data-verify="${r.id}" data-ok="1">Accept fix</button>
        <button class="btn ghost" data-verify="${r.id}" data-ok="0">Reject, reopen</button>
      </div>
    </div>`).join("") : '<p class="muted">Nothing to check.</p>';

  await renderPartners();
}

// ---------- mjeshtrit (skilled volunteers) ----------
const SKILL = { plumbing: "🔧 Plumbing", electrics: "⚡ Electrics", building: "🧱 Building", painting: "🎨 Painting",
  carpentry: "🪚 Carpentry", gardening: "🌳 Gardening", welding: "🔥 Welding" };
const DAY = { weekday_evenings: "Weekday evenings", saturday: "Saturday", sunday: "Sunday", holidays: "Holidays" };
const VERDICT = { legit: ["✓ Looks genuine", "ok"], suspicious: ["? Unclear", "warn"], fake: ["✗ Looks fake", "bad"],
  not_a_document: ["✗ Not a document", "bad"], unavailable: ["AI was busy", "warn"] };
let mjRows = [];

async function refreshMjBadge() {
  try {
    mjRows = await api("/admin/mjeshtrit");
    const waiting = mjRows.filter((m) => m.status === "pending").length;
    $("#mj-badge").textContent = waiting;
    $("#mj-badge").classList.toggle("hidden", !waiting);
  } catch { /* ignore */ }
}

async function renderMjeshtrit() {
  await refreshMjBadge();
  $("#mj-empty").classList.toggle("hidden", mjRows.length > 0);
  $("#mj-list").innerHTML = mjRows.map((m) => {
    const [vText, vCls] = VERDICT[m.ai_verdict] || ["Not checked", "warn"];
    const status = { pending: "Waiting for you", approved: `Approved${m.verified_by === "ai" ? " by AI" : ""}`, rejected: "Rejected" }[m.status];
    return `
    <div class="mj-card ${m.status}">
      <div class="mj-head">
        <div><b>${esc(m.user_name)}</b> <small class="muted">${esc(m.user_email)}</small><br>
          <small class="muted">${esc(m.neighbourhood || "—")} · applied ${fmtDate(m.created_at)}</small></div>
        <span class="mj-status ${m.status}">${status}</span>
      </div>
      <div>${m.skills.map((s) => `<span class="tag ${m.verified_skills.includes(s) ? "on" : ""}">${SKILL[s] || esc(s)}${m.verified_skills.includes(s) ? " ✓" : ""}</span>`).join("")}</div>
      <div class="muted">${m.days.map((d) => DAY[d] || esc(d)).join(" · ") || "No days given"}</div>
      ${m.bio ? `<p class="mj-bio">“${esc(m.bio)}”</p>` : ""}
      <div class="mj-ai">
        <div><span class="verdict ${vCls}">🤖 ${vText}</span>${m.ai_confidence != null ? ` <small class="muted">${m.ai_confidence}% sure</small>` : ""}</div>
        ${m.ai_verdict && m.ai_verdict !== "unavailable" ? `
        <dl>
          <dt>Document</dt><dd>${esc((m.ai_doc_type || "—").replaceAll("_", " "))}${m.ai_issuer ? ` · ${esc(m.ai_issuer)}` : ""}</dd>
          <dt>Name on it</dt><dd>${esc(m.ai_name_on_doc || "—")} ${m.ai_name_matches === false ? '<b class="owed">doesn’t match</b>' : m.ai_name_matches ? "✓" : ""}</dd>
          <dt>Shows skills</dt><dd>${m.ai_skills.length ? m.ai_skills.map((s) => SKILL[s] || esc(s)).join(", ") : "none of the claimed ones"}</dd>
          <dt>Genuine?</dt><dd>${m.ai_looks_genuine ? "No signs of forgery" : '<b class="owed">Signs of forgery or a template</b>'}</dd>
        </dl>
        ${m.ai_reason ? `<q class="transcript">${esc(m.ai_reason)}</q>` : ""}` : ""}
      </div>
      ${m.admin_note ? `<p class="muted">Your note: ${esc(m.admin_note)}</p>` : ""}
      <div class="fix-actions">
        <button class="btn ghost" data-mjdoc="${m.id}" data-mime="${esc(m.proof_mime || "")}">View document</button>
        ${m.status !== "approved" ? `<button class="btn primary" data-mjok="${m.id}">Approve</button>` : ""}
        ${m.status !== "rejected" ? `<button class="btn danger" data-mjno="${m.id}" data-name="${esc(m.user_name)}">${m.status === "approved" ? "Remove" : "Reject"}</button>` : ""}
      </div>
    </div>`;
  }).join("");
}

document.addEventListener("click", async (e) => {
  const doc = e.target.closest("[data-mjdoc]");
  if (doc) {
    // The document needs the admin token, so fetch it and open it as a blob (never a public URL).
    const res = await fetch(`${API}/admin/mjeshtrit/${doc.dataset.mjdoc}/proof`, { headers: { Authorization: `Bearer ${state.token}` } });
    if (!res.ok) return alert("Couldn't open the document");
    window.open(URL.createObjectURL(await res.blob()), "_blank", "noopener");
    return;
  }
  const ok = e.target.closest("[data-mjok]");
  if (ok) {
    await api(`/admin/mjeshtrit/${ok.dataset.mjok}/approve`, { method: "POST", body: "{}" });
    renderMjeshtrit();
    return;
  }
  const no = e.target.closest("[data-mjno]");
  if (no) {
    const note = prompt(`Why can't ${no.dataset.name} be a mjeshtër? (sent to them)`, "We couldn't verify your document. Please send a clearer photo of your certificate.");
    if (note === null) return;
    await api(`/admin/mjeshtrit/${no.dataset.mjno}/reject`, { method: "POST", body: JSON.stringify({ note }) });
    renderMjeshtrit();
  }
});

// ---------- partner rewards ----------
let partners = [];
async function renderPartners() {
  const [list, claims] = await Promise.all([api("/admin/partners"), api("/admin/reward-claims")]);
  partners = list;
  $("#partner-empty").classList.toggle("hidden", list.length > 0);
  $("#partner-rows").innerHTML = list.map((r) => `
    <tr class="${r.active ? "" : "off"}">
      <td><span class="emoji">${esc(r.emoji)}</span> <b>${esc(r.partner)}</b> · ${esc(r.title)}
        ${r.details ? `<br><small class="muted">${esc(r.details)}</small>` : ""}</td>
      <td>${r.cost}</td>
      <td>${r.stock == null ? '<span class="muted">No limit</span>' : r.stock === 0 ? '<b class="owed">Sold out</b>' : r.stock}</td>
      <td>${r.claimed}</td>
      <td>${r.active ? "On offer" : '<span class="muted">Hidden</span>'}</td>
      <td class="nowrap">
        <button class="btn ghost" data-pedit="${r.id}">Edit</button>
        <button class="btn danger" data-pdel="${r.id}">${r.claimed ? "Hide" : "Delete"}</button>
      </td>
    </tr>`).join("");
  $("#claim-empty").classList.toggle("hidden", claims.length > 0);
  $("#claim-rows").innerHTML = claims.map((c) => `
    <tr class="${c.used ? "off" : ""}">
      <td><code>${esc(c.code)}</code></td>
      <td>${esc(c.emoji)} ${esc(c.partner)} · ${esc(c.title)} <small class="muted">(${c.cost} badges)</small></td>
      <td>${esc(c.user_name || "")}<br><small class="muted">${esc(c.user_email || "")}</small></td>
      <td>${new Date(c.created_at + "Z").toLocaleDateString()}</td>
      <td>${c.used ? `<span class="muted">Used ${new Date(c.used_at + "Z").toLocaleDateString()}</span>`
        : `<button class="btn ghost" data-cused="${c.id}" data-code="${esc(c.code)}">Mark used</button>`}</td>
    </tr>`).join("");
}

function partnerFormReset() {
  const f = $("#partner-form");
  f.reset();
  f.id.value = "";
  $("#partner-save").textContent = "Add reward";
  $("#partner-cancel").classList.add("hidden");
}

$("#partner-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = {
    partner: f.partner.value.trim(), title: f.title.value.trim(), details: f.details.value.trim() || null,
    emoji: f.emoji.value.trim() || "🎁", cost: Number(f.cost.value),
    stock: f.stock.value === "" ? null : Number(f.stock.value), active: f.active.checked,
  };
  try {
    if (f.id.value) await api(`/admin/partners/${f.id.value}`, { method: "PUT", body: JSON.stringify(body) });
    else await api("/admin/partners", { method: "POST", body: JSON.stringify(body) });
    partnerFormReset();
    renderPartners();
  } catch (err) {
    alert(err.message);
  }
});
$("#partner-cancel").addEventListener("click", partnerFormReset);

document.addEventListener("click", async (e) => {
  const ed = e.target.closest("[data-pedit]");
  if (ed) {
    const r = partners.find((x) => x.id === Number(ed.dataset.pedit));
    const f = $("#partner-form");
    f.id.value = r.id; f.emoji.value = r.emoji; f.partner.value = r.partner; f.title.value = r.title;
    f.details.value = r.details || ""; f.cost.value = r.cost; f.stock.value = r.stock ?? ""; f.active.checked = r.active;
    $("#partner-save").textContent = "Save changes";
    $("#partner-cancel").classList.remove("hidden");
    f.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  const del = e.target.closest("[data-pdel]");
  if (del) {
    const r = partners.find((x) => x.id === Number(del.dataset.pdel));
    const msg = r.claimed
      ? `Hide “${r.title}”? The ${r.claimed} voucher(s) already given stay valid.`
      : `Delete “${r.title}” from ${r.partner}? This can't be undone.`;
    if (!confirm(msg)) return;
    await api(`/admin/partners/${r.id}`, { method: "DELETE" });
    renderPartners();
    return;
  }
  const used = e.target.closest("[data-cused]");
  if (used) {
    if (!confirm(`Mark voucher ${used.dataset.code} as used? Do this when the partner has taken it.`)) return;
    await api(`/admin/reward-claims/${used.dataset.cused}/used`, { method: "POST" });
    renderPartners();
  }
});

document.addEventListener("click", async (e) => {
  const v = e.target.closest("[data-verify]");
  if (v) {
    const ok = v.dataset.ok === "1";
    const comment = ok ? null : prompt("Why can't the city confirm the fix? (sent to the neighbour)") || null;
    await api(`/admin/reports/${v.dataset.verify}/verify-fix`, { method: "POST", body: JSON.stringify({ ok, comment }) });
    await load();
    return;
  }
});

function renderTable(list) {
  $("#empty").classList.toggle("hidden", list.length > 0);
  $("#rows").innerHTML = list.map((r) => `
    <tr data-id="${r.id}">
      <td class="muted">#${r.id}</td>
      <td>${prio(r)}</td>
      <td>${icon(r.category)} ${esc(r.category.name)}${flagMark(r)}<br><small class="muted">${esc(r.address || r.neighbourhood || "")}</small></td>
      <td class="desc">${esc(r.description) || (r.voice_text ? `🎙️ ${esc(r.voice_text)}` : '<span class="muted">—</span>')}</td>
      <td>${pill(r.status)}</td>
      <td>${r.confirmations || ""}</td>
      <td title="${fmtDate(r.created_at)}">${ago(r.created_at)}</td>
      <td title="${fmtDate(r.updated_at)}">${ago(r.updated_at)}</td>
    </tr>`).join("");
}
$("#rows").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (tr) openReport(+tr.dataset.id);
});
document.querySelectorAll(".reports th[data-sort]").forEach((th) => th.addEventListener("click", () => {
  const key = th.dataset.sort;
  state.sort = { key, dir: state.sort.key === key && state.sort.dir === "desc" ? "asc" : "desc" };
  document.querySelectorAll(".reports th").forEach((h) => h.classList.remove("sorted", "asc", "desc"));
  th.classList.add("sorted", state.sort.dir);
  render();
}));

function pinIcon(r) {
  return L.divIcon({
    className: "mm-pin",
    html: `<div style="background:${STATUS_COLOR[r.status]}"><span>${icon(r.category)}</span></div>`,
    iconSize: [30, 30], iconAnchor: [15, 30], popupAnchor: [0, -28],
  });
}

function tiles() {
  // OpenStreetMap tiles, darkened with CSS (.mm-dark) to match the MendMap look.
  return L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
    className: "mm-dark",
  });
}

function renderMap(list) {
  if (!map) {
    map = L.map("map");
    tiles().addTo(map);
    markersLayer = L.layerGroup().addTo(map);
    // Leaflet stops click propagation inside popups, so bind the link when a popup opens.
    map.on("popupopen", (e) => {
      const a = e.popup.getElement().querySelector("[data-open]");
      if (a) a.addEventListener("click", (ev) => { ev.preventDefault(); openReport(+a.dataset.open); });
    });
  }
  setTimeout(() => map.invalidateSize(), 0);
  markersLayer.clearLayers();
  const pts = [];
  list.forEach((r) => {
    pts.push([r.latitude, r.longitude]);
    L.marker([r.latitude, r.longitude], { icon: pinIcon(r) })
      .bindPopup(`<b>#${r.id} ${esc(r.category.name)}</b><br>${pill(r.status)}<br>${esc(r.description)}<br><a href="#" role="button" data-open="${r.id}">Open report →</a>`)
      .addTo(markersLayer);
  });
  if (pts.length) map.fitBounds(pts, { padding: [40, 40], maxZoom: 16 });
  else map.setView([42.6629, 21.1655], 13); // Prishtina
}
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-open]");
  if (a) { e.preventDefault(); openReport(+a.dataset.open); }
});

async function renderStats() {
  renderSummary();
  renderBoard();
  const s = await api("/admin/stats");
  const days = (d) => (d == null ? "—" : `${d} days`);
  $("#stat-cards").innerHTML = `
    <div class="card"><span class="muted">All reports</span><b>${s.total}</b></div>
    <div class="card reported"><span class="muted">Reported</span><b>${s.reported}</b></div>
    <div class="card in_progress"><span class="muted">In progress</span><b>${s.in_progress}</b></div>
    <div class="card fixed"><span class="muted">Fixed</span><b>${s.fixed}</b></div>
    <div class="card"><span class="muted">Avg. time to fix</span><b>${days(s.avg_days_to_fix)}</b></div>`;
  const max = Math.max(1, ...s.per_category.map((c) => c.total));
  $("#stat-bars").innerHTML = s.per_category.map((c) => `
    <div class="bar-row">
      <span>${esc(c.category)} <span class="muted">(${c.total})</span></span>
      <div class="bar" style="width:${(c.total / max) * 100}%">
        ${["reported", "in_progress", "fixed"].map((k) => c[k] ? `<i class="${k}" style="flex:${c[k]}" title="${STATUS_LABEL[k]}: ${c[k]}"></i>` : "").join("")}
      </div>
      <span class="muted">fix: ${days(c.avg_days_to_fix)}</span>
    </div>`).join("");
}

// ---------- report drawer ----------
async function openReport(id) {
  const r = await api(`/reports/${id}`);
  const next = { reported: "in_progress", in_progress: "fixed", fixed: "fixed" }[r.status];
  $("#drawer-body").innerHTML = `
    <p class="muted">Report #${r.id}</p>
    <h2>${icon(r.category)} ${esc(r.category.name)}</h2>
    ${pill(r.status)}
    ${r.photo_url ? `<a href="${esc(API + r.photo_url)}" target="_blank" rel="noopener"><img class="photo" src="${esc(API + r.photo_url)}" alt="Report photo"></a>` : '<div class="nophoto muted">No photo</div>'}
    ${(r.photos || []).length > 1 ? `<div class="more-photos">${r.photos.slice(1).map((u) => `<a href="${esc(API + u)}" target="_blank" rel="noopener"><img src="${esc(API + u)}" alt="More photos"></a>`).join("")}</div>` : ""}
    ${r.edited_at ? `<p class="muted">✎ Edited by the reporter ${ago(r.edited_at)}</p>` : ""}
    ${r.after_photo_url ? `<p><a href="${esc(API + r.after_photo_url)}" target="_blank" rel="noopener">Photo of the finished work ↗</a></p>` : ""}
    <p>${esc(r.description) || '<span class="muted">No description</span>'}
      ${r.ai_description && r.ai_description === r.description ? '<br><small class="muted">✨ Written by AI from the photo</small>' : ""}</p>
    ${r.blurred ? `<p class="muted">🔒 ${r.blurred} face(s) or number plate(s) blurred for privacy</p>` : ""}
    ${r.rating === 1 ? '<p class="muted">👍 The reporter confirmed the fix</p>' : ""}
    ${r.reopened ? `<p class="owed">↺ Reopened ${r.reopened}× by the reporter: they said it wasn't fixed</p>` : ""}
    ${r.voice_url ? `<p><span class="muted">Voice note</span><br><audio controls preload="none" src="${esc(API + r.voice_url)}"></audio>
      ${r.voice_text ? `<br><q class="transcript">${esc(r.voice_text)}</q>` : ""}</p>` : ""}
    <dl>
      <dt>Priority</dt><dd>${prio(r)} ${r.priority_reasons.map((x) => `<span class="tag">${esc(REASON[x] || x)}</span>`).join(" ")}</dd>
      <dt>Severity</dt><dd>${r.severity ? `${r.severity} / 5` : '<span class="muted">—</span>'}</dd>
      <dt>Area</dt><dd>${esc(r.neighbourhood || "—")}${r.address ? `<br>🛣️ ${esc(r.address)}` : ""}
        ${r.adopted_by?.length ? `<br><span class="tag">💚 Looked after by ${esc(r.adopted_by.join(", "))}</span>` : ""}</dd>
      ${r.repeat_of ? `<dt>Came back</dt><dd class="owed">↺ Reported again after a fix: <a href="#" data-open="${r.repeat_of}">#${r.repeat_of}</a> was fixed here recently. The repair may not have held.</dd>` : ""}
      ${fraudBlock(r)}
      <dt>Reported by</dt><dd>${esc(r.reporter_name || "—")}</dd>
      ${r.claimed_by ? `<dt>Neighbour fix</dt><dd>${esc(r.claimed_by_name || "A neighbour")} · ${
        { pending: "waiting for your check", verified: "accepted ✓" }[r.fix_status] || "working on it"}</dd>` : ""}
      <dt>AI check</dt><dd>${r.ai_is_problem == null
        ? '<span class="muted">Not checked</span>'
        : `${r.ai_is_problem ? `${esc(r.ai_category || "other")} · severity ${r.ai_severity ?? "—"}/5` : "⚠ May not be a street problem"}
           ${r.ai_is_problem ? `<span class="tag">${r.ai_neighbour_safe ? "✓ safe for neighbours" : "needs the crew"}</span>` : ""}
           ${r.ai_reason ? `<br><q class="transcript">${esc(r.ai_reason)}</q>` : ""}
           ${r.ai_description && r.ai_description !== r.description ? `<br><span class="muted">AI sees:</span> ${esc(r.ai_description)}` : ""}
           ${r.ai_safety_reason ? `<br><q class="transcript">${esc(r.ai_safety_reason)}</q>` : ""}`}
        <br><button class="btn ghost" id="ai-check" type="button">${r.ai_is_problem == null ? "Run AI check" : "Check again"}</button>
        <span class="error" id="ai-error"></span></dd>
      <dt>Reported</dt><dd>${fmtDate(r.created_at)}</dd>
      <dt>Confirmations</dt><dd>${r.confirmations} × “I see this too”</dd>
      <dt>Location</dt><dd><a href="https://www.openstreetmap.org/?mlat=${r.latitude}&mlon=${r.longitude}#map=18/${r.latitude}/${r.longitude}" target="_blank" rel="noopener">${r.latitude.toFixed(5)}, ${r.longitude.toFixed(5)}</a></dd>
    </dl>
    ${r.fix_status === "pending" ? `
      <div class="fix-actions">
        <button class="btn primary" data-verify="${r.id}" data-ok="1">Accept neighbour fix</button>
        <button class="btn ghost" data-verify="${r.id}" data-ok="0">Reject, reopen</button>
      </div>` : ""}
    <div id="mini-map" class="mini-map"></div>
    <form id="status-form">
      <strong>Update status</strong>
      <select name="status">
        ${["reported", "in_progress", "fixed"].map((s) => `<option value="${s}" ${s === next ? "selected" : ""}>${STATUS_LABEL[s]}</option>`).join("")}
      </select>
      <textarea name="comment" placeholder="Comment for the citizen (optional), e.g. “Crew scheduled for Tuesday”"></textarea>
      <label class="muted">Photo of the finished work (optional)
        <input type="file" name="after_photo" accept="image/jpeg,image/png,image/webp">
      </label>
      <button class="btn primary" type="submit">Save &amp; notify citizen</button>
      <p class="error" id="status-error"></p>
    </form>
    <h3>Timeline</h3>
    <ul class="timeline">
      ${r.updates.slice().reverse().map((u) => `
        <li class="${u.new_status}">
          <strong>${STATUS_LABEL[u.new_status] || esc(u.new_status)}</strong>
          ${u.comment ? `<div>${esc(u.comment)}</div>` : ""}
          <small>${fmtDate(u.created_at)}</small>
        </li>`).join("")}
    </ul>
    <button class="btn danger" id="delete-report">Delete report</button>`;
  $("#drawer").classList.remove("hidden");

  if (miniMap) miniMap.remove();
  miniMap = L.map("mini-map", { zoomControl: false, attributionControl: false }).setView([r.latitude, r.longitude], 17);
  tiles().addTo(miniMap);
  L.marker([r.latitude, r.longitude], { icon: pinIcon(r) }).addTo(miniMap);

  $("#status-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const after = f.get("after_photo");
      if (after && after.size) {
        const body = new FormData();
        body.append("after_photo", after);
        const res = await fetch(`${API}/admin/reports/${r.id}/after-photo`, { method: "POST", body, headers: { Authorization: `Bearer ${state.token}` } });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Photo upload failed");
      }
      const sameStatus = f.get("status") === r.status && !f.get("comment");
      if (!sameStatus) {
        await api(`/admin/reports/${r.id}/status`, { method: "PATCH", body: JSON.stringify({ status: f.get("status"), comment: f.get("comment") || null }) });
      }
      await load();
      openReport(r.id);
    } catch (err) {
      $("#status-error").textContent = err.message;
    }
  });
  $("#clear-flag")?.addEventListener("click", async () => {
    await api(`/admin/reports/${r.id}/clear-flag`, { method: "POST" });
    await load();
    openReport(r.id);
  });
  $("#ai-check").addEventListener("click", async (e) => {
    e.target.disabled = true;
    e.target.textContent = "Checking…";
    try {
      await api(`/admin/reports/${r.id}/ai-check`, { method: "POST" });
      await load();
      openReport(r.id);
    } catch (err) {
      $("#ai-error").textContent = err.message;
      e.target.disabled = false;
      e.target.textContent = "Run AI check";
    }
  });
  $("#delete-report").addEventListener("click", async () => {
    if (!confirm(`Delete report #${r.id}? This cannot be undone.`)) return;
    await api(`/admin/reports/${r.id}`, { method: "DELETE" });
    closeDrawer();
    load();
  });
}
function closeDrawer() { $("#drawer").classList.add("hidden"); }
$("#drawer-close").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => e.key === "Escape" && closeDrawer());

// ---------- fraud checks ----------
const FLAG = {
  fake_photo: "The AI thinks the photo isn't a real photo of the street (screenshot, photo of a screen, drawing, AI-made or from the web)",
  not_problem: "The AI doesn't see a street problem in the photo",
  reused_photo: "The same photo was already used in another report",
};
const KIND = { real_photo: "Real photo", screenshot: "Screenshot", photo_of_screen: "Photo of a screen", drawing: "Drawing",
  ai_generated: "AI-generated", stock_or_web: "From the web", edited: "Edited" };
function flagMark(r) {
  const marks = [];
  if (r.flagged) marks.push(`<span class="flag" title="${esc(r.ai_flags.map((f) => FLAG[f] || f).join(" · "))}">⚑</span>`);
  if (r.fix_ai === "fake" || r.fix_ai === "suspicious") marks.push('<span class="flag" title="The AI doubts the “fixed” photo">⚑ fix</span>');
  if (r.repeat_of) marks.push(`<span class="tag" title="Reported again after #${r.repeat_of} was fixed here">↺ came back</span>`);
  return marks.length ? " " + marks.join(" ") : "";
}
function fraudBlock(r) {
  const rows = [];
  if (r.ai_flags.length) rows.push(`<ul class="flags">${r.ai_flags.map((f) => `<li>⚑ ${esc(FLAG[f] || f)}${
    f === "reused_photo" && r.reused_from ? ` (<a href="#" data-open="${r.reused_from}">#${r.reused_from}</a>)` : ""}</li>`).join("")}</ul>`);
  if (r.ai_photo_kind && r.ai_photo_kind !== "real_photo")
    rows.push(`<span class="muted">Photo looks like:</span> ${esc(KIND[r.ai_photo_kind] || r.ai_photo_kind)}${r.ai_kind_reason ? ` · <q>${esc(r.ai_kind_reason)}</q>` : ""}`);
  if (r.fix_ai) rows.push(`<span class="muted">“Fixed” photo check:</span> ${esc({ ok: "✓ looks fixed", suspicious: "? unclear", fake: "✗ looks fake" }[r.fix_ai] || r.fix_ai)}${
    r.fix_ai_reason ? ` · <q>${esc(r.fix_ai_reason)}</q>` : ""}`);
  if (!rows.length) return "";
  const btn = r.flagged ? '<br><button class="btn ghost" id="clear-flag" type="button">✓ I checked it: it\'s genuine</button>'
    : r.flag_cleared ? '<br><span class="muted">✓ Cleared by city staff</span>' : "";
  return `<dt>Fraud check</dt><dd class="${r.flagged ? "owed" : ""}">${rows.join("<br>")}${btn}</dd>`;
}
$("#review-all").addEventListener("click", async (e) => {
  const b = e.target;
  b.disabled = true;
  b.textContent = "Checking…";
  try {
    const res = await api("/admin/ai/review-all", { method: "POST" });
    b.textContent = `✓ ${res.reused_photos} reused photo(s) found · ${res.queued} sent to the AI`;
    setTimeout(load, 4000);
  } catch (err) {
    b.textContent = err.message;
  }
  setTimeout(() => { b.disabled = false; b.textContent = "✨ Check all with AI"; }, 8000);
});

// ---------- summary, scoreboard, top 10 ----------
async function renderSummary(fresh = false) {
  const box = $("#summary");
  box.innerHTML = '<p class="muted">✨ Writing the summary…</p>';
  try {
    const s = await api(`/admin/summary?days=${$("#sum-days").value}&lang=${$("#sum-lang").value}${fresh ? "&fresh=1" : ""}`);
    const list = (xs) => xs.length ? xs.map(([n, k]) => `${esc(n)} <span class="muted">(${k})</span>`).join(", ") : '<span class="muted">—</span>';
    box.innerHTML = `
      <p class="summary-text">${s.text ? esc(s.text) : '<span class="muted">The AI is busy or not set up right now, so here are just the numbers. Try “Write again” in a few minutes.</span>'}</p>
      <div class="cards">
        <div class="card"><span class="muted">New reports</span><b>${s.new}</b></div>
        <div class="card fixed"><span class="muted">Fixed</span><b>${s.fixed}</b></div>
        <div class="card reported"><span class="muted">Waiting over 10 days</span><b>${s.waiting_long}</b></div>
        <div class="card"><span class="muted">Came back after a fix</span><b>${s.came_back}</b></div>
      </div>
      <p><span class="muted">Busiest areas:</span> ${list(s.top_areas)}<br><span class="muted">Busiest streets:</span> ${list(s.top_streets)}</p>`;
  } catch (err) {
    box.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}
$("#sum-days").addEventListener("change", () => renderSummary());
$("#sum-lang").addEventListener("change", () => renderSummary());
$("#sum-fresh").addEventListener("click", () => renderSummary(true));
$("#sum-email").addEventListener("click", async (e) => {
  try {
    const r = await api(`/admin/summary/email?days=${$("#sum-days").value}&lang=${$("#sum-lang").value}`, { method: "POST" });
    e.target.textContent = `✓ Sent to ${r.to}`;
  } catch (err) {
    e.target.textContent = err.message;
  }
  setTimeout(() => { e.target.textContent = "✉ Email it to me"; }, 6000);
});

async function renderBoard() {
  const [pub, top] = await Promise.all([api("/public/stats"), api("/public/top?days=30")]);
  const pct = (x) => (x == null ? '<span class="muted">—</span>' : `${Math.round(x * 100)}%`);
  const days = (d) => (d == null ? '<span class="muted">—</span>' : `${d} days`);
  const board = [...pub.neighbourhoods].sort((a, b) => (a.avg_fix_days ?? 999) - (b.avg_fix_days ?? 999));
  $("#board-rows").innerHTML = board.map((n) => `
    <tr><td>${esc(n.name)}</td><td>${n.total}</td><td>${pct(n.fix_rate)}</td><td>${days(n.avg_fix_days)}</td>
      <td>${pct(n.fixed_in_week)}</td><td>${n.came_back ? `<span class="owed">↺ ${n.came_back}</span>` : "0"}</td></tr>`).join("");
  $("#top10").innerHTML = top.length ? top.map((r) => `
    <li><a href="#" data-open="${r.id}">#${r.id} ${esc(r.title)}</a> · ${esc(r.address || r.neighbourhood || "")}
      <span class="tag">👥 ${r.confirmations}</span> ${pill(r.status)}</li>`).join("")
    : '<p class="muted">No confirmed open problems this month.</p>';
}

// ---------- chat moderation & announcements ----------
let chatRooms = null;
async function refreshChatBadge() {
  try {
    const flagged = await api("/admin/chat");
    const n = flagged.filter((m) => !m.hidden).length;
    $("#chat-badge").textContent = n;
    $("#chat-badge").classList.toggle("hidden", !n);
  } catch { /* ignore */ }
}
async function renderChat() {
  if (!chatRooms) {
    chatRooms = ["city", ...(await api("/neighbourhoods"))];
    $("#ann-rooms").innerHTML = chatRooms.map((r) => `
      <label class="check"><input type="checkbox" name="room" value="${esc(r)}" ${r === "city" ? "checked" : ""}/> ${r === "city" ? "🏙️ All of Prishtina" : esc(r)}</label>`).join("");
  }
  const all = $("#chat-all").checked;
  const msgs = await api(`/admin/chat?flagged=${all ? "false" : "true"}`);
  $("#chat-empty").classList.toggle("hidden", msgs.length > 0);
  $("#chat-list").innerHTML = msgs.map((m) => `
    <div class="chat-card ${m.hidden ? "is-hidden" : ""}">
      <div class="chat-meta">
        <b>${esc(m.user_name)}</b> <span class="muted">${esc(m.user_email)} · ${m.room === "city" ? "All of Prishtina" : esc(m.room)} · ${ago(m.created_at)}</span>
        ${m.kind !== "message" ? `<span class="tag">${m.kind === "announcement" ? "📢 announcement" : "🧹 clean-up day"}</span>` : ""}
        ${m.flags ? `<span class="tag bad">⚑ reported ${m.flags}×</span>` : ""}
        ${m.hidden ? '<span class="tag">hidden</span>' : ""}
      </div>
      <p>${esc(m.text)}</p>
      <div>${m.hidden
        ? `<button class="btn ghost" data-chat-restore="${m.id}">Show again</button>`
        : `<button class="btn danger" data-chat-hide="${m.id}">Hide</button>${m.flags ? ` <button class="btn ghost" data-chat-restore="${m.id}">It's fine: clear reports</button>` : ""}`}</div>
    </div>`).join("");
  refreshChatBadge();
}
$("#chat-all").addEventListener("change", renderChat);
$("#chat-list").addEventListener("click", async (e) => {
  const hide = e.target.closest("[data-chat-hide]");
  const restore = e.target.closest("[data-chat-restore]");
  if (!hide && !restore) return;
  const id = (hide || restore).dataset[hide ? "chatHide" : "chatRestore"];
  await api(`/admin/chat/${id}/${hide ? "hide" : "restore"}`, { method: "POST" });
  renderChat();
});
$("#ann-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const rooms = f.getAll("room");
  if (!rooms.length) { $("#ann-msg").textContent = "Pick at least one room."; return; }
  try {
    await api("/admin/announcements", { method: "POST", body: JSON.stringify({ rooms, text: f.get("text"), push: f.get("push") === "on" }) });
    $("#ann-msg").textContent = `✓ Posted in ${rooms.length} room(s)`;
    e.target.querySelector("textarea").value = "";
    setTimeout(() => { $("#ann-msg").textContent = ""; }, 5000);
  } catch (err) {
    $("#ann-msg").textContent = err.message;
  }
});

// ---------- paid bookings: held money, problems, payouts and refunds ----------
const BK_LABEL = {
  requested: "Waiting for a price", quoted: "Price sent", declined: "Declined", cancelled: "Cancelled",
  paid: "💰 Paid, money held", disputed: "⚠️ Problem reported", done: "✓ Paid out", refunded: "↩ Refunded",
};
const eur = (cents, cur = "eur") => cents == null ? "—" : new Intl.NumberFormat("en-IE", { style: "currency", currency: cur.toUpperCase() }).format(cents / 100);
async function refreshBookingBadge() {
  try {
    const s = await api("/admin/bookings/summary");
    $("#bk-badge").textContent = s.disputed;
    $("#bk-badge").classList.toggle("hidden", !s.disputed);
    return s;
  } catch { return null; }
}
async function renderBookings() {
  const s = await refreshBookingBadge();
  if (s) {
    $("#bk-days").textContent = s.auto_release_days;
    $("#bk-mode").innerHTML = s.stripe ? "Payments: <b>Stripe</b>. Payouts and refunds here move real money (or test money with test keys)."
      : s.demo ? "Payments: <b>test mode</b>. No real money moves; buttons only change the booking." : "Payments are switched off on this server.";
    $("#bk-cards").innerHTML = `
      <div class="card"><span class="muted">MendMap earned (${Math.round(s.commission_rate * 100)}%)</span><b class="earned">${eur(s.earned_cents, s.currency)}</b><small class="muted">${s.done} finished jobs</small></div>
      <div class="card"><span class="muted">Held now</span><b>${eur(s.held_cents, s.currency)}</b><small class="muted">${s.held} jobs</small></div>
      <div class="card"><span class="muted">Problems to decide</span><b class="${s.disputed ? "owed" : ""}">${s.disputed}</b></div>
      <div class="card"><span class="muted">Paid to mjeshtrit</span><b>${eur(s.paid_out_cents, s.currency)}</b></div>
      <div class="card"><span class="muted">Refunded</span><b>${eur(s.refunded_cents, s.currency)}</b><small class="muted">${s.refunded} jobs</small></div>`;
  }
  const status = $("#bk-filter").value;
  const rows = await api(`/admin/bookings${status ? `?status=${encodeURIComponent(status)}` : ""}`);
  $("#bk-empty").classList.toggle("hidden", rows.length > 0);
  $("#bk-list").innerHTML = rows.map((b) => {
    const held = b.status === "paid" || b.status === "disputed";
    return `
    <div class="chat-card bk-card ${b.status}">
      <div class="chat-meta">
        <b>#${b.id}</b> <span class="tag ${b.status === "disputed" ? "bad" : ""}">${BK_LABEL[b.status] || esc(b.status)}</span>
        <b>${eur(b.fee_cents, b.currency)}</b>
        ${b.commission_cents != null && b.status !== "refunded" ? `<span class="muted">MendMap ${eur(b.commission_cents, b.currency)} · mjeshtër ${eur(b.worker_gets_cents, b.currency)}</span>` : ""}
        ${b.pay_mode === "demo" ? '<span class="tag">test</span>' : ""}
        <span class="muted">· ${ago(b.created_at)}</span>
      </div>
      <div class="muted">Resident: ${esc(b.customer_name)} (${esc(b.customer_email || "")}) → Mjeshtër: ${esc(b.worker_name)} (${esc(b.worker_email || "")})</div>
      <p>${esc(b.description)}${b.address ? ` <span class="muted">📍 ${esc(b.address)}</span>` : ""}</p>
      ${b.problem_note ? `<p class="bk-problem">⚠️ Resident: “${esc(b.problem_note)}”</p>` : ""}
      ${b.status === "paid" ? `<p class="muted">${b.worker_done_at ? `The mjeshtër finished ${ago(b.worker_done_at)}. Sent automatically ${b.auto_release_at ? `on ${new Date(b.auto_release_at + "Z").toLocaleString()}` : "soon"} unless the resident reports a problem.` : "Waiting for the mjeshtër to finish the job."}</p>` : ""}
      ${b.admin_note ? `<p class="muted">Your note: ${esc(b.admin_note)}</p>` : ""}
      <div class="fix-actions">
        ${b.has_photo ? `<button class="btn ghost" data-bkphoto="${b.id}">View photo</button>` : ""}
        ${held ? `<button class="btn primary" data-bkrelease="${b.id}" data-name="${esc(b.worker_name)}" data-amount="${eur(b.worker_gets_cents, b.currency)}">Pay the mjeshtër</button>
        <button class="btn danger" data-bkrefund="${b.id}" data-amount="${eur(b.fee_cents, b.currency)}">Refund the resident</button>` : ""}
      </div>
    </div>`;
  }).join("");
}
$("#bk-filter").addEventListener("change", renderBookings);
$("#bk-list").addEventListener("click", async (e) => {
  const photo = e.target.closest("[data-bkphoto]");
  if (photo) {
    // Photos of people's homes are private: fetch with the admin token and open as a blob.
    const res = await fetch(`${API}/bookings/${photo.dataset.bkphoto}/photo`, { headers: { Authorization: `Bearer ${state.token}` } });
    if (!res.ok) return alert("Couldn't open the photo");
    window.open(URL.createObjectURL(await res.blob()), "_blank", "noopener");
    return;
  }
  const rel = e.target.closest("[data-bkrelease]");
  const ref = e.target.closest("[data-bkrefund]");
  if (!rel && !ref) return;
  const btn = rel || ref;
  const question = rel
    ? `Send ${btn.dataset.amount} to ${btn.dataset.name}? MendMap keeps its commission. This can't be undone here.`
    : `Refund ${btn.dataset.amount} to the resident? MendMap keeps nothing. This can't be undone.`;
  if (!confirm(question)) return;
  const note = prompt("Note for the resident and the mjeshtër (optional):", "") ?? null;
  if (note === null) return;
  btn.disabled = true;
  try {
    await api(`/admin/bookings/${rel ? rel.dataset.bkrelease : ref.dataset.bkrefund}/${rel ? "release" : "refund"}`,
      { method: "POST", body: JSON.stringify({ note: note.trim() || null }) });
  } catch (err) {
    alert(err.message);
  }
  renderBookings();
});

// ---------- navigation / filters ----------
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
  state.view = b.dataset.view;
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${state.view}`));
  render();
}));
$("#f-category").addEventListener("change", load);
$("#f-status").addEventListener("change", load);
$("#f-search").addEventListener("input", render);
$("#f-flagged").addEventListener("change", render);
$("#refresh").addEventListener("click", load);

async function start() {
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  $("#me-name").textContent = state.user?.name || "";
  try {
    if (!state.categories.length) {
      state.categories = await api("/categories");
      $("#f-category").insertAdjacentHTML("beforeend", state.categories.map((c) => `<option value="${c.id}">${icon(c)} ${esc(c.name)}</option>`).join(""));
    }
    await load();
  } catch (err) {
    console.error(err);
  }
}

if (state.token && state.user?.role === "admin") start();
else logout();
setInterval(() => state.token && !document.hidden && load(), 60_000);
