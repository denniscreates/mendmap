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
  if (q) list = list.filter((r) => `#${r.id}` === q || String(r.id) === q || (r.description || "").toLowerCase().includes(q) || r.category.name.toLowerCase().includes(q));
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

  const rows = await api("/admin/rewards");
  $("#reward-empty").classList.toggle("hidden", rows.length > 0);
  $("#reward-rows").innerHTML = rows.map((u) => `
    <tr>
      <td>${esc(u.name)}<br><small class="muted">${esc(u.email)}</small></td>
      <td>${esc(u.neighbourhood || "—")}</td>
      <td>${u.verified} <span class="muted">(${u.verified % 20}/20 to next)</span></td>
      <td>${u.rewards_earned}</td>
      <td>${u.rewards_paid}</td>
      <td>${u.owed_eur ? `<b class="owed">€${u.owed_eur}</b>` : '<span class="muted">—</span>'}</td>
      <td>${u.owed_eur ? `<button class="btn ghost" data-paid="${u.user_id}" data-name="${esc(u.name)}" data-eur="${u.owed_eur}">Mark paid</button>` : ""}</td>
    </tr>`).join("");
}
document.addEventListener("click", async (e) => {
  const v = e.target.closest("[data-verify]");
  if (v) {
    const ok = v.dataset.ok === "1";
    const comment = ok ? null : prompt("Why can't the city confirm the fix? (sent to the neighbour)") || null;
    await api(`/admin/reports/${v.dataset.verify}/verify-fix`, { method: "POST", body: JSON.stringify({ ok, comment }) });
    await load();
    return;
  }
  const p = e.target.closest("[data-paid]");
  if (p) {
    if (!confirm(`Record that ${p.dataset.name} was paid €${p.dataset.eur}? Pay them first; MendMap does not send money.`)) return;
    await api(`/admin/rewards/${p.dataset.paid}/paid`, { method: "POST" });
    renderFixers();
  }
});

function renderTable(list) {
  $("#empty").classList.toggle("hidden", list.length > 0);
  $("#rows").innerHTML = list.map((r) => `
    <tr data-id="${r.id}">
      <td class="muted">#${r.id}</td>
      <td>${prio(r)}</td>
      <td>${icon(r.category)} ${esc(r.category.name)}<br><small class="muted">${esc(r.neighbourhood || "")}</small></td>
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
    ${r.after_photo_url ? `<p><a href="${esc(API + r.after_photo_url)}" target="_blank" rel="noopener">Photo of the finished work ↗</a></p>` : ""}
    <p>${esc(r.description) || '<span class="muted">No description</span>'}</p>
    ${r.voice_url ? `<p><span class="muted">Voice note</span><br><audio controls preload="none" src="${esc(API + r.voice_url)}"></audio>
      ${r.voice_text ? `<br><q class="transcript">${esc(r.voice_text)}</q>` : ""}</p>` : ""}
    <dl>
      <dt>Priority</dt><dd>${prio(r)} ${r.priority_reasons.map((x) => `<span class="tag">${esc(REASON[x] || x)}</span>`).join(" ")}</dd>
      <dt>Severity</dt><dd>${r.severity ? `${r.severity} / 5` : '<span class="muted">—</span>'}</dd>
      <dt>Area</dt><dd>${esc(r.neighbourhood || "—")}</dd>
      <dt>Reported by</dt><dd>${esc(r.reporter_name || "—")}</dd>
      ${r.claimed_by ? `<dt>Neighbour fix</dt><dd>${esc(r.claimed_by_name || "A neighbour")} · ${
        { pending: "waiting for your check", verified: "accepted ✓" }[r.fix_status] || "working on it"}</dd>` : ""}
      <dt>AI check</dt><dd>${r.ai_is_problem == null
        ? '<span class="muted">Not checked</span>'
        : `${r.ai_is_problem ? `${esc(r.ai_category || "other")} · severity ${r.ai_severity ?? "—"}/5` : "⚠ May not be a street problem"}
           ${r.ai_is_problem ? `<span class="tag">${r.ai_neighbour_safe ? "✓ safe for neighbours" : "needs the crew"}</span>` : ""}
           ${r.ai_reason ? `<br><q class="transcript">${esc(r.ai_reason)}</q>` : ""}
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
