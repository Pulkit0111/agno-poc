"""Render the portfolio risk roll-up as an INTERACTIVE, single-screen dashboard.

Two panes, fixed to the viewport: filters + charts on the LEFT, the engagements table on the
RIGHT — only the engagements list scrolls, the page itself does not. All data + weekly history
embedded as JSON; Chart.js from a CDN; vanilla JS cross-filters everything live (click a chart
slice, search, toggle, sort) and recomputes KPIs/charts/table.

Pure: takes the aggregated Portfolio + history points + an 'as of' label, returns HTML."""

from __future__ import annotations

import html
import json

from bott.skills.portfolio.aggregate import Portfolio

_CHARTJS = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"

# Plain (non-f) string — JS/CSS braces would fight an f-string. Data injected via __DATA__ etc.
_PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Portfolio Risk Roll-up — Axelerant</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>
  :root{--orange:#FF5C00;--navy:#0D1B2A;--navy2:#111827;--off:#F1F3F5;--slate:#4B5563;--line:#e5e7eb;
    --up:#10b981;--down:#ef4444;--fh:'Inter',sans-serif;--fd:'Space Grotesk',sans-serif}
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%}
  body{font-family:var(--fh);background:var(--off);color:var(--navy);line-height:1.5;
    display:flex;flex-direction:column;height:100vh;overflow:hidden}
  /* ── compact header with inline KPIs ── */
  .header{background:var(--navy);color:#fff;padding:16px 28px;display:flex;align-items:center;gap:24px;flex-wrap:wrap}
  .header .brand{display:flex;flex-direction:column;gap:2px}
  .header .row1{display:flex;align-items:center;gap:10px}
  .logo{font-family:var(--fd);font-weight:700;color:var(--orange);font-size:16px}
  .badge{background:var(--orange);color:#fff;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;padding:3px 9px;border-radius:20px}
  .header h1{font-family:var(--fd);font-size:20px;font-weight:700;letter-spacing:-.3px}
  .header .sub{color:rgba(255,255,255,.5);font-size:12px}
  .kpis{display:flex;gap:10px;margin-left:auto;flex-wrap:wrap}
  .kpi{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:10px;padding:8px 16px;text-align:center;min-width:92px}
  .kpi .n{font-family:var(--fd);font-size:22px;font-weight:700;color:var(--orange);line-height:1}
  .kpi .l{font-size:10px;color:rgba(255,255,255,.6);text-transform:uppercase;letter-spacing:.4px;margin-top:4px}
  /* ── two-pane body; only the engagements list scrolls ── */
  .app{flex:1;display:flex;gap:16px;padding:16px 28px;min-height:0}
  .left{flex:1.45;display:flex;flex-direction:column;gap:12px;min-height:0;overflow-y:auto;padding-right:4px}
  .right{flex:1;display:flex;flex-direction:column;min-height:0}
  .filterbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  .search{flex:1;min-width:160px;padding:8px 12px;border:1px solid var(--line);border-radius:9px;font-size:13.5px;font-family:var(--fh)}
  .chip{border:1px solid var(--line);background:#fff;border-radius:20px;padding:6px 12px;font-size:12px;font-weight:600;cursor:pointer;color:var(--slate)}
  .chip.on{background:var(--navy);color:#fff;border-color:var(--navy)}
  .toggle{font-size:12px;font-weight:600;color:var(--slate);cursor:pointer;display:flex;gap:6px;align-items:center}
  .clear{margin-left:auto;font-size:12px;color:var(--orange);cursor:pointer;font-weight:600;background:none;border:none}
  .charts{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
  .card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:13px 15px;box-shadow:0 1px 4px rgba(0,0,0,.05)}
  .card h3{font-family:var(--fd);font-size:12.5px;font-weight:700;margin-bottom:8px}
  .card .hint{font-size:10px;color:#9aa3af;font-weight:500}
  .chartbox{position:relative;height:150px}
  .span2{grid-column:1 / -1}
  .placeholder{height:150px;display:flex;align-items:center;justify-content:center;text-align:center;color:#94a3b8;font-size:12px;padding:0 12px}
  /* right pane */
  .rhead{font-family:var(--fd);font-size:15px;font-weight:700;display:flex;align-items:center;gap:9px;margin-bottom:10px}
  .rhead::before{content:'';width:9px;height:9px;border-radius:50%;background:var(--orange)}
  .count{font-size:12px;color:var(--slate);font-weight:500}
  .tablewrap{flex:1;min-height:0;overflow-y:auto;background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 1px 4px rgba(0,0,0,.05)}
  table{width:100%;border-collapse:collapse}
  thead th{position:sticky;top:0;background:var(--navy);color:#fff;font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;padding:10px 14px;text-align:left;cursor:pointer;user-select:none;z-index:1}
  thead th:hover{color:var(--orange)}
  tbody tr{border-bottom:1px solid #f0f0f0}
  tbody tr:last-child{border-bottom:none}
  tbody tr:hover{background:#fafafa}
  tbody td{padding:9px 14px;font-size:13px;color:var(--slate)}
  tbody td.acct{color:var(--navy);font-weight:600}
  .pill{display:inline-block;font-size:10.5px;font-weight:700;padding:2px 9px;border-radius:20px;text-transform:uppercase;letter-spacing:.4px}
  .pill-high{background:#fef2f2;color:#b91c1c}.pill-medium{background:#fffbeb;color:#92400e}
  .pill-low{background:#ecfdf5;color:#065f46}.pill-unknown{background:#f1f5f9;color:#475569}
  .t-up{color:var(--up);font-weight:700}.t-down{color:var(--down);font-weight:700}.t-flat{color:#94a3b8}
  @media(max-width:860px){.app{flex-direction:column;overflow-y:auto}.left,.right{overflow:visible}.tablewrap{max-height:60vh}}
</style></head>
<body>
<div class="header">
  <div class="brand">
    <div class="row1"><span class="logo">Axelerant</span><span class="badge">Portfolio</span></div>
    <h1>Portfolio Risk Roll-up</h1><div class="sub">__ASOF__</div>
  </div>
  <div class="kpis">
    <div class="kpi"><div class="n" id="kpiTotal">–</div><div class="l">Shown</div></div>
    <div class="kpi"><div class="n" id="kpiAtRisk">–</div><div class="l">At-risk</div></div>
    <div class="kpi"><div class="n" id="kpiDeclining">–</div><div class="l">Declining</div></div>
    <div class="kpi"><div class="n" id="kpiImproving">–</div><div class="l">Improving</div></div>
  </div>
</div>
<div class="app">
  <div class="left">
    <div class="filterbar">
      <input class="search" id="searchInput" placeholder="Search engagements…">
      <button class="chip on" data-band="all">All</button>
      <button class="chip" data-band="high">🔴 High</button>
      <button class="chip" data-band="medium">🟡 Medium</button>
      <button class="chip" data-band="low">🟢 Low</button>
      <label class="toggle"><input type="checkbox" id="decliningToggle"> Declining only</label>
      <button class="clear" id="clearBtn">Clear ✕</button>
    </div>
    <div class="charts">
      <div class="card"><h3>Risk <span class="hint">· click to filter</span></h3><div class="chartbox"><canvas id="riskChart"></canvas></div></div>
      <div class="card"><h3>Sentiment trend</h3><div class="chartbox"><canvas id="sentChart"></canvas></div></div>
      <div class="card"><h3>Risk × sentiment <span class="hint">· each dot = engagement</span></h3><div class="chartbox"><canvas id="scatterChart"></canvas></div></div>
      <div class="card"><h3>Velocity <span class="hint">· last sprint</span></h3><div class="chartbox" id="velBox"><canvas id="velChart"></canvas></div></div>
      <div class="card span2"><h3>Sentiment over time</h3><div class="chartbox" id="trendBox"><canvas id="trendChart"></canvas></div></div>
    </div>
  </div>
  <div class="right">
    <div class="rhead">Engagements <span class="count" id="count"></span></div>
    <div class="tablewrap">
      <table><thead><tr>
        <th data-sort="account">Account</th><th data-sort="risk">Risk</th>
        <th data-sort="sentiment">Sent.</th><th data-sort="trend">Trend</th>
        <th data-sort="vel_stories">Last sprint</th>
      </tr></thead><tbody id="tbody"></tbody></table>
    </div>
  </div>
</div>
<script src="__CHARTJS__"></script>
<script>
const DATA = __DATA__;
const ALL = DATA.engagements, HIST = DATA.history || [];
const EPS = 0.05, dec = t => t < -EPS, imp = t => t > EPS;
const state = {q:"", band:"all", declining:false, sort:{key:"score", dir:-1}};
const esc = s => String(s==null?"":s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const $ = id => document.getElementById(id);
function filtered(){
  return ALL.filter(e => {
    if (state.band !== "all" && e.band !== state.band) return false;
    if (state.declining && !dec(e.trend)) return false;
    if (state.q && !String(e.account).toLowerCase().includes(state.q.toLowerCase())) return false;
    return true;
  });
}
const BANDO = {high:0, medium:1, low:2, unknown:3};
function sorted(rows){
  const {key, dir} = state.sort;
  return rows.slice().sort((a,b) => {
    let va = key==="risk" ? (BANDO[a.band]??3) : a[key], vb = key==="risk" ? (BANDO[b.band]??3) : b[key];
    if (key==="account"){ va=String(va).toLowerCase(); vb=String(vb).toLowerCase(); }
    if (va==null) va=-Infinity; if (vb==null) vb=-Infinity;
    return va<vb ? -dir : va>vb ? dir : 0;
  });
}
function trendCell(t){
  if (dec(t)) return "<span class='t-down'>▼ "+t.toFixed(2)+"</span>";
  if (imp(t)) return "<span class='t-up'>▲ +"+t.toFixed(2)+"</span>";
  return "<span class='t-flat'>▪ flat</span>";
}
function renderKPIs(rows){
  $("kpiTotal").textContent = rows.length + (rows.length!==ALL.length ? " / "+ALL.length : "");
  $("kpiAtRisk").textContent = rows.filter(e=>e.band==="high"||e.band==="medium").length;
  $("kpiDeclining").textContent = rows.filter(e=>dec(e.trend)).length;
  $("kpiImproving").textContent = rows.filter(e=>imp(e.trend)).length;
}
function renderTable(rows){
  $("tbody").innerHTML = rows.map(e =>
    "<tr><td class='acct'>"+esc(e.account)+"</td>"+
    "<td><span class='pill pill-"+esc(e.band)+"'>"+esc(e.band)+"</span></td>"+
    "<td>"+Number(e.sentiment).toFixed(2)+"</td><td>"+trendCell(e.trend)+"</td>"+
    "<td>"+esc(e.velocity)+"</td></tr>").join("") || "<tr><td colspan='5' style='padding:16px'>No matches.</td></tr>";
  $("count").textContent = rows.length + " shown";
}
let risk, sent, scatter, vel, trend;
function buildCharts(){
  risk = new Chart($("riskChart"), {type:'doughnut',
    data:{labels:['High','Medium','Low'], datasets:[{data:[0,0,0], backgroundColor:['#ef4444','#f59e0b','#10b981'], borderWidth:0}]},
    options:{cutout:'58%', plugins:{legend:{position:'bottom',labels:{boxWidth:10,font:{size:10}}}},
      onClick:(e,els)=>{ if(els.length){ const b=['high','medium','low'][els[0].index]; state.band = state.band===b?"all":b; syncChips(); refresh(); } }}});
  sent = new Chart($("sentChart"), {type:'doughnut',
    data:{labels:['Declining','Flat','Improving'], datasets:[{data:[0,0,0], backgroundColor:['#ef4444','#94a3b8','#10b981'], borderWidth:0}]},
    options:{cutout:'58%', plugins:{legend:{position:'bottom',labels:{boxWidth:10,font:{size:10}}}}}});
  scatter = new Chart($("scatterChart"), {type:'scatter',
    data:{datasets:[{data:[], pointRadius:4, pointHoverRadius:6}]},
    options:{plugins:{legend:{display:false}, tooltip:{callbacks:{label:c=>c.raw.a+" (risk "+c.raw.x.toFixed(2)+", sent "+c.raw.y.toFixed(2)+")"}}},
      scales:{x:{title:{display:true,text:'Risk'},min:0,max:1}, y:{title:{display:true,text:'Sentiment'}}}}});
  vel = new Chart($("velChart"), {type:'bar',
    data:{labels:[], datasets:[{label:'Stories', data:[], backgroundColor:'#FF5C00', borderRadius:4}]},
    options:{indexAxis:'y', plugins:{legend:{display:false}}, scales:{x:{beginAtZero:true,ticks:{precision:0}}}}});
  if (HIST.length >= 2){
    trend = new Chart($("trendChart"), {type:'line',
      data:{labels:HIST.map(h=>h.date), datasets:[
        {label:'Avg sentiment', data:HIST.map(h=>h.avg_sentiment), borderColor:'#FF5C00', tension:.3, yAxisID:'y'},
        {label:'At-risk count', data:HIST.map(h=>(h.high||0)+(h.medium||0)), borderColor:'#0D9488', tension:.3, yAxisID:'y1'}]},
      options:{plugins:{legend:{position:'bottom',labels:{boxWidth:10,font:{size:10}}}},
        scales:{y:{position:'left'}, y1:{position:'right',grid:{drawOnChartArea:false}}}}});
  } else {
    $("trendBox").innerHTML = "<div class='placeholder'>Trend lines appear once a few weekly snapshots have accrued (currently "+(HIST.length||1)+").</div>";
  }
}
function updateCharts(rows){
  const by = b => rows.filter(e=>e.band===b).length;
  risk.data.datasets[0].data = [by('high'), by('medium'), by('low')]; risk.update();
  sent.data.datasets[0].data = [rows.filter(e=>dec(e.trend)).length, rows.filter(e=>!dec(e.trend)&&!imp(e.trend)).length, rows.filter(e=>imp(e.trend)).length]; sent.update();
  scatter.data.datasets[0].data = rows.map(e=>({x:e.score, y:e.sentiment, a:e.account}));
  scatter.data.datasets[0].pointBackgroundColor = rows.map(e=>({high:'#ef4444',medium:'#f59e0b',low:'#10b981'}[e.band]||'#94a3b8'));
  scatter.update();
  const vrows = rows.filter(e=>e.vel_stories!=null).sort((a,b)=>b.vel_stories-a.vel_stories).slice(0,8);
  vel.data.labels = vrows.map(e=>e.account); vel.data.datasets[0].data = vrows.map(e=>e.vel_stories); vel.update();
  $("velBox").style.opacity = vrows.length ? 1 : .4;
}
function refresh(){ const rows = sorted(filtered()); renderKPIs(rows); renderTable(rows); updateCharts(rows); }
function syncChips(){ document.querySelectorAll('.chip').forEach(c=>c.classList.toggle('on', c.dataset.band===state.band)); }
$("searchInput").addEventListener('input', e=>{ state.q=e.target.value; refresh(); });
document.querySelectorAll('.chip').forEach(c=>c.addEventListener('click', ()=>{ state.band=c.dataset.band; syncChips(); refresh(); }));
$("decliningToggle").addEventListener('change', e=>{ state.declining=e.target.checked; refresh(); });
$("clearBtn").addEventListener('click', ()=>{ state.q=""; state.band="all"; state.declining=false; $("searchInput").value=""; $("decliningToggle").checked=false; syncChips(); refresh(); });
document.querySelectorAll('th[data-sort]').forEach(th=>th.addEventListener('click', ()=>{
  const k=th.dataset.sort; state.sort = {key:k, dir: state.sort.key===k ? -state.sort.dir : (k==="account"?1:-1)}; refresh(); }));
buildCharts(); refresh();
</script>
</body></html>
"""


def render_portfolio_dashboard(pf: Portfolio, history: list[dict], as_of: str) -> str:
    engagements = [{
        "account": r.account, "band": r.band, "score": round(r.score, 3),
        "sentiment": round(r.sentiment, 3), "trend": round(r.trend, 3),
        "velocity": r.velocity, "vel_stories": r.vel_stories,
    } for r in pf.rows]
    data_js = json.dumps({"engagements": engagements, "history": history}).replace("</", "<\\/")
    return (_PAGE
            .replace("__DATA__", data_js)
            .replace("__ASOF__", html.escape(as_of))
            .replace("__CHARTJS__", _CHARTJS))
