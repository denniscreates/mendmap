// MendMap public transparency page — no sign-in, served by the API at /city.
const API = location.origin;
const ICON = { pothole: "🕳️", streetlight: "💡", dumping: "🗑️", other: "📍", accessibility: "♿" };
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const get = (p) => fetch(API + p).then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.statusText))));
const days = (d) => (d == null ? "—" : `${d} days`);
const pct = (x) => `${Math.round(x * 100)}%`;

$("#theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("mm_theme", next);
});

async function stats() {
  const s = await get("/public/stats");
  $("#cards").innerHTML = `
    <div class="card"><span class="muted">Reported so far</span><span class="big">${s.total}</span></div>
    <div class="card fixed"><span class="muted">Fixed</span><span class="big" style="color:var(--fixed)">${s.fixed}</span></div>
    <div class="card"><span class="muted">Fix rate</span><span class="big">${pct(s.fix_rate)}</span></div>
    <div class="card in_progress"><span class="muted">Being worked on</span><span class="big" style="color:var(--amber)">${s.in_progress}</span></div>
    <div class="card"><span class="muted">Average time to fix</span><span class="big">${days(s.avg_days_to_fix)}</span></div>`;

  const max = Math.max(1, ...s.neighbourhoods.map((n) => n.total));
  $("#board").innerHTML = s.neighbourhoods.map((n, i) => `
    <li>
      <span class="rank">${i + 1}</span>
      <div>
        <div>${esc(n.name)} <span class="muted">· ${n.total} report${n.total === 1 ? "" : "s"}</span></div>
        <div class="meter" title="${n.fixed} fixed"><i style="width:${(n.fixed / max) * 100}%"></i></div>
      </div>
      <span class="muted">${pct(n.fix_rate)} fixed</span>
    </li>`).join("");

  const cmax = Math.max(1, ...s.per_category.map((c) => c.total));
  $("#cats").innerHTML = s.per_category.map((c) => `
    <div class="bar-row">
      <span>${esc(c.category)} <span class="muted">(${c.total})</span></span>
      <div class="bar" style="width:${(c.total / cmax) * 100}%">
        ${["reported", "in_progress", "fixed"].map((k) => (c[k] ? `<i class="${k}" style="flex:${c[k]}"></i>` : "")).join("")}
      </div>
      <span class="muted">${days(c.avg_days_to_fix)}</span>
    </div>`).join("");
}

async function heat() {
  const reports = await get("/reports?status=reported,in_progress&limit=2000");
  const map = L.map("heat", { scrollWheelZoom: false }).setView([42.6629, 21.1655], 13);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19, className: "mm-dark",
  }).addTo(map);
  // Weight by priority so urgent problems glow brighter.
  const pts = reports.map((r) => [r.latitude, r.longitude, 0.4 + r.priority / 100]);
  if (L.heatLayer) L.heatLayer(pts, { radius: 32, blur: 24, maxZoom: 16, gradient: { 0.3: "#2f63f0", 0.6: "#f5b638", 1: "#f26a2e" } }).addTo(map);
  if (pts.length) map.fitBounds(pts.map((p) => [p[0], p[1]]), { padding: [40, 40], maxZoom: 15 });
}

Promise.allSettled([stats(), heat()]).then((r) => r.forEach((x) => x.status === "rejected" && console.error(x.reason)));
