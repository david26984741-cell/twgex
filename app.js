/* 台指選擇權曝險地圖 — 前端。無外部相依。
   資料是「積木」（買權/賣權的 gamma 項與 vega 項分開放），
   造市商方向假設與 beta 都在這裡即時組合，不需要重跑後端。 */
'use strict';

let E = 1e8;                                     // 顯示單位除數，載入後由 meta 決定
let UNIT = '億元';
const $ = (s) => document.querySelector(s);
const fmt = (v, d = 2) => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(d);
const fmtK = (v) => v.toLocaleString('en-US', { maximumFractionDigits: 0 });
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

const S = {                                      // UI 狀態
  data: null, sym: null, exp: 'ALL', band: 0.20, bucket: 1,
  sign: 'net', beta: 1.0, cvd: 0,
};

/* --------------------------------------------------------- 慣例與定義
   GEX  = sg.c*gc + sg.p*gp            元 / 標的移動 1%          （gamma 曝險）
   VEX  = sg.c*wc + sg.p*wp            元 / 隱含波動率 1 個百分點（vanna 曝險）
   GEX+ = GEX + beta * VEX
   後端已經把乘數、S 的尺度、vanna 的負號都算進 gc/gp/wc/wp 裡了。      */
// net   : 造市商買權作多、賣權放空（經典慣例，會產生 Gamma Flip）
// gross : 造市商兩邊都是賣方
const SIGNS = { net: { c: +1, p: -1 }, gross: { c: -1, p: -1 } };

const gexOf = (r, sg) => sg.c * r.gc + sg.p * r.gp;
const vexOf = (r, sg) => sg.c * r.wc + sg.p * r.wp;
const vegaOf = (r, sg) => sg.c * r.vc + sg.p * r.vp;

/* --------------------------------------------------------- 取資料 */
async function load(sym, day) {
  if (window.__GEXMAP__ && !day) return window.__GEXMAP__;
  const url = day ? `data/${sym}/history/${day}.json` : `data/${sym}/latest.json`;
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`讀不到 ${url}（HTTP ${r.status}）`);
  return r.json();
}

async function loadJson(url) {
  if (window.__GEXMAP__) return null;
  try { const r = await fetch(url, { cache: 'no-store' }); return r.ok ? r.json() : null; }
  catch (e) { return null; }
}

async function mountDates() {
  const idx = await loadJson(`data/${S.sym}/index.json`);
  const sel = $('#selDate');
  if (!idx || !idx.dates || idx.dates.length < 2) { $('#ctlDate').style.display = 'none'; return; }
  const cur = S.data.meta.trade_date.replace(/\//g, '');
  sel.innerHTML = idx.dates.slice().reverse()
    .map(d => `<option value="${d}"${d === cur ? ' selected' : ''}>${d.slice(0,4)}/${d.slice(4,6)}/${d.slice(6)}</option>`).join('');
  $('#ctlDate').style.display = '';
}

async function switchTo(sym, day) {
  const box = $('#err');
  try {
    S.data = await load(sym, day);
    S.sym = sym;
    if (!day) S.exp = 'ALL';
    applyMeta();
    mountExpiries();
    await mountDates();
    methodology();
    howto();
    render();
    box.style.display = 'none';
  } catch (err) {
    box.style.display = 'block';
    box.innerHTML = `<b>${sym} 的資料還沒產生：</b>${err.message}<br>` +
      '<span style="opacity:.8">排程跑過一次之後就會出現。</span>';
  }
}

function applyMeta() {
  const m = S.data.meta;
  E = m.unit_div || 1e8;
  UNIT = m.unit || '億元';
  S.band = m.default_view_band || 0.20;
  $('#selBand').value = String(S.band);
  $('#mDate').textContent = m.trade_date;
  $('#mSpot').textContent = fmtK(m.s_ref);
  $('#mLegs').textContent = fmtK(m.n_legs);
  $('#mExp').textContent = m.n_expiries;
  $('#mOI').textContent = fmtK(m.oi_total);
  $('#mCov').textContent = (m.oi_coverage * 100).toFixed(1) + '%';
  $('#mSrc').textContent = m.source + '　・　' + m.price_note + '　・　產生於 ' + m.generated_at +
    (m.prev_trade_date ? '　・　OI 增減對比 ' + m.prev_trade_date : '');
  $('#nGex').textContent = UNIT + ' / 標的移動 1%';
  $('#nVex').textContent = 'vanna 曝險・' + UNIT + ' / 波動率 1 點';
  document.title = `${m.label} 選擇權曝險地圖`;
  [...document.querySelectorAll('#segSym button')].forEach(b =>
    b.setAttribute('aria-pressed', b.dataset.v === S.sym));
}

/* --------------------------------------------------------- 資料整形 */
function view() { return S.data.views[S.exp] || S.data.views.ALL; }

function buckets() {
  const v = view(), S0 = S.data.meta.s_ref, b = S.bucket;
  const lo = S0 * (1 - S.band), hi = S0 * (1 + S.band);
  const m = new Map();
  for (const r of v.strikes) {
    if (r.K < lo || r.K > hi) continue;
    const k = b > 1 ? Math.round(r.K / b) * b : r.K;
    let a = m.get(k);
    if (!a) m.set(k, a = { K: k, gc: 0, gp: 0, wc: 0, wp: 0, vc: 0, vp: 0,
                           oc: 0, op: 0, dc: 0, dp: 0, ivn: 0, ivd: 0 });
    a.gc += r.gc; a.gp += r.gp; a.wc += r.wc; a.wp += r.wp; a.vc += r.vc; a.vp += r.vp;
    a.oc += r.oc; a.op += r.op; a.dc += r.dc; a.dp += r.dp;
    if (r.iv != null) { a.ivn += r.iv * (r.oc + r.op); a.ivd += r.oc + r.op; }
  }
  const out = [...m.values()].sort((x, y) => x.K - y.K);
  for (const a of out) a.iv = a.ivd ? a.ivn / a.ivd : null;
  return out;
}

// 分桶後的網格間距（原始履約價時取相鄰履約價的最小間距，長條寬度要用）
function gridStep(rows) {
  if (S.bucket > 1) return S.bucket;
  let d = Infinity;
  for (let i = 1; i < rows.length; i++) d = Math.min(d, rows[i].K - rows[i - 1].K);
  return isFinite(d) && d > 0 ? d : 50;
}

function curve(clip) {
  const c = view().curve, sg = SIGNS[S.sign], b = S.beta, S0 = S.data.meta.s_ref;
  const w2 = Math.min(S.band, 0.12), lo = S0 * (1 - w2), hi = S0 * (1 + w2);
  const x = [], gex = [], vex = [], gexp = [];
  for (let i = 0; i < c.x.length; i++) {
    if (clip && (c.x[i] < lo || c.x[i] > hi)) continue;
    const g = sg.c * c.gc[i] + sg.p * c.gp[i];
    const w = sg.c * c.wc[i] + sg.p * c.wp[i];
    x.push(c.x[i]); gex.push(g); vex.push(w); gexp.push(g + b * w);
  }
  return { x, gex, vex, gexp };
}

function crossings(x, y, near) {
  const out = [];
  for (let i = 0; i < x.length - 1; i++) {
    if (y[i] === 0) out.push(x[i]);
    else if (y[i] * y[i + 1] < 0) {
      const t = y[i] / (y[i] - y[i + 1]);
      out.push(x[i] + t * (x[i + 1] - x[i]));
    }
  }
  if (!out.length) return null;
  return out.reduce((a, v) => (Math.abs(v - near) < Math.abs(a - near) ? v : a));
}

/* --------------------------------------------------------- SVG 小工具 */
const NS = 'http://www.w3.org/2000/svg';
function el(n, a = {}, parent) {
  const e = document.createElementNS(NS, n);
  for (const k in a) if (a[k] != null) e.setAttribute(k, a[k]);
  if (parent) parent.appendChild(e);
  return e;
}
// 長條：離基線那一端做 4px 圓角（marks-and-anatomy）
function barPath(x, w, yBase, yVal, r = 4) {
  const up = yVal < yBase, h = Math.abs(yVal - yBase);
  const rr = Math.min(r, w / 2, h);
  if (h < 0.6) return `M${x} ${yBase}h${w}`;
  return up
    ? `M${x} ${yBase} L${x} ${yVal + rr} Q${x} ${yVal} ${x + rr} ${yVal} L${x + w - rr} ${yVal} Q${x + w} ${yVal} ${x + w} ${yVal + rr} L${x + w} ${yBase} Z`
    : `M${x} ${yBase} L${x} ${yVal - rr} Q${x} ${yVal} ${x + rr} ${yVal} L${x + w - rr} ${yVal} Q${x + w} ${yVal} ${x + w} ${yVal - rr} L${x + w} ${yBase} Z`;
}
function niceTicks(lo, hi, n = 5) {
  const span = hi - lo || 1, raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * p).find(s => s >= raw) || 10 * p;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  out.step = step;
  out.dp = clamp(Math.ceil(-Math.log10(step)), 0, 4);      // 小數位跟著刻度間距走
  return out;
}

/* --------------------------------------------------------- tooltip */
const tip = $('#tip');
function showTip(ev, html) {
  tip.innerHTML = html; tip.style.opacity = 1;
  const r = tip.getBoundingClientRect();
  tip.style.left = clamp(ev.clientX + 14, 8, innerWidth - r.width - 8) + 'px';
  tip.style.top = clamp(ev.clientY - r.height - 12, 8, innerHeight - r.height - 8) + 'px';
}
const hideTip = () => { tip.style.opacity = 0; };

/* --------------------------------------------------------- 長條圖 */
function drawBars(host, rows, valueFn, colorFn, opts) {
  host.innerHTML = '';
  const W = Math.max(host.clientWidth || 640, 320), H = opts.h || 268;
  const m = { t: 48, r: 14, b: 30, l: 58 };          // 上緣留給參考線標籤
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' }, host);
  const g = el('g', { transform: `translate(${m.l},${m.t})` }, svg);

  const vals = rows.map(valueFn);
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  if (hi === lo) { hi = 1; lo = -1; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const ks = rows.map(r => r.K);
  const kMin = Math.min(...ks), kMax = Math.max(...ks), step = opts.step || S.bucket;
  const x = k => ((k - kMin + step / 2) / (kMax - kMin + step)) * iw;
  const y = v => ih - ((v - lo) / (hi - lo)) * ih;
  const bw = Math.max(1, iw / ((kMax - kMin) / step + 1) - 2);   // 2px 表面間隙

  const yT = niceTicks(lo, hi, 5);
  for (const t of yT) {
    const yy = y(t);
    el('line', { class: 'gl', x1: 0, x2: iw, y1: yy, y2: yy }, g);
    el('text', { class: 'ax', x: -8, y: yy + 3.5, 'text-anchor': 'end' }, g).textContent = t.toFixed(yT.dp);
  }
  el('line', { class: 'zero', x1: 0, x2: iw, y1: y(0), y2: y(0) }, g);
  el('text', { class: 'axname', x: -m.l + 4, y: -m.t + 12 }, g).textContent = opts.yLabel;

  const kt = niceTicks(kMin, kMax, 6);
  for (const t of kt) {
    if (t < kMin - step || t > kMax + step) continue;
    el('text', { class: 'ax', x: x(t), y: ih + 18, 'text-anchor': 'middle' }, g).textContent = fmtK(t);
  }

  rows.forEach((r, i) => {
    const v = valueFn(r), xx = x(r.K) - bw / 2;
    const p = el('path', { d: barPath(xx, bw, y(0), y(v)), fill: colorFn(r, v), 'shape-rendering': 'geometricPrecision' }, g);
    const hit = el('rect', { x: xx - 1, y: 0, width: bw + 2, height: ih, fill: 'transparent' }, g);
    const on = (ev) => { p.setAttribute('opacity', .72); showTip(ev, opts.tip(r, v)); };
    hit.addEventListener('mouseenter', on); hit.addEventListener('mousemove', on);
    hit.addEventListener('mouseleave', () => { p.removeAttribute('opacity'); hideTip(); });
  });

  (opts.refs || []).forEach((rf, i) => {
    if (rf.v == null || rf.v < kMin - step || rf.v > kMax + step) return;
    const xx = x(rf.v);
    el('line', { x1: xx, x2: xx, y1: -m.t + 6, y2: ih, stroke: rf.color, 'stroke-width': 2, 'stroke-dasharray': rf.dash }, g);
    const at = xx > iw - 96;                       // 靠右邊界就把標籤翻到左側
    el('text', { class: 'ax', x: xx + (at ? -5 : 5), y: -m.t + 15 + i * 12, fill: rf.color,
                 'text-anchor': at ? 'end' : 'start' }, g).textContent = rf.label;
  });
}

/* --------------------------------------------------------- 折線圖 */
function drawCurve(host, cv, refs) {
  host.innerHTML = '';
  const W = Math.max(host.clientWidth || 640, 320), H = 268;
  const m = { t: 48, r: 14, b: 30, l: 58 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' }, host);
  const g = el('g', { transform: `translate(${m.l},${m.t})` }, svg);

  const all = cv.gex.concat(cv.gexp).map(v => v / E);
  let lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const xMin = cv.x[0], xMax = cv.x[cv.x.length - 1];
  const x = v => ((v - xMin) / (xMax - xMin)) * iw;
  const y = v => ih - ((v - lo) / (hi - lo)) * ih;

  const yT = niceTicks(lo, hi, 5);
  for (const t of yT) {
    const yy = y(t);
    el('line', { class: 'gl', x1: 0, x2: iw, y1: yy, y2: yy }, g);
    el('text', { class: 'ax', x: -8, y: yy + 3.5, 'text-anchor': 'end' }, g).textContent = t.toFixed(yT.dp);
  }
  el('line', { class: 'zero', x1: 0, x2: iw, y1: y(0), y2: y(0) }, g);
  el('text', { class: 'axname', x: -m.l + 4, y: -m.t + 12 }, g).textContent = UNIT + ' / 1%';
  for (const t of niceTicks(xMin, xMax, 6)) {
    if (t < xMin || t > xMax) continue;
    el('text', { class: 'ax', x: x(t), y: ih + 18, 'text-anchor': 'middle' }, g).textContent = fmtK(t);
  }

  const path = (arr) => arr.map((v, i) => (i ? 'L' : 'M') + x(cv.x[i]).toFixed(1) + ' ' + y(v / E).toFixed(1)).join('');
  el('path', { d: path(cv.gexp), fill: 'none', stroke: 'var(--curve2)', 'stroke-width': 2, 'stroke-linecap': 'round' }, g);
  el('path', { d: path(cv.gex), fill: 'none', stroke: 'var(--curve1)', 'stroke-width': 2, 'stroke-linecap': 'round' }, g);

  refs.forEach((rf, i) => {
    if (rf.v == null || rf.v < xMin || rf.v > xMax) return;
    const xx = x(rf.v), at = xx > iw - 96;
    el('line', { x1: xx, x2: xx, y1: -m.t + 6, y2: ih, stroke: rf.color, 'stroke-width': 2, 'stroke-dasharray': rf.dash }, g);
    el('text', { class: 'ax', x: xx + (at ? -5 : 5), y: -m.t + 15 + i * 12, fill: rf.color,
                 'text-anchor': at ? 'end' : 'start' }, g).textContent = rf.label;
  });

  // 十字準星
  const cross = el('line', { y1: -m.t + 6, y2: ih, stroke: '#4b5b6e', 'stroke-width': 1, opacity: 0 }, g);
  const d1 = el('circle', { r: 4.5, fill: 'var(--curve1)', stroke: 'var(--surface)', 'stroke-width': 2, opacity: 0 }, g);
  const d2 = el('circle', { r: 4.5, fill: 'var(--curve2)', stroke: 'var(--surface)', 'stroke-width': 2, opacity: 0 }, g);
  const hit = el('rect', { x: 0, y: 0, width: iw, height: ih, fill: 'transparent' }, g);
  hit.addEventListener('mousemove', (ev) => {
    const bb = svg.getBoundingClientRect();
    const px = (ev.clientX - bb.left) * (W / bb.width) - m.l;
    const sv = xMin + (px / iw) * (xMax - xMin);
    let i = 0, best = Infinity;
    cv.x.forEach((v, j) => { const d = Math.abs(v - sv); if (d < best) { best = d; i = j; } });
    const xx = x(cv.x[i]);
    cross.setAttribute('x1', xx); cross.setAttribute('x2', xx); cross.setAttribute('opacity', 1);
    d1.setAttribute('cx', xx); d1.setAttribute('cy', y(cv.gex[i] / E)); d1.setAttribute('opacity', 1);
    d2.setAttribute('cx', xx); d2.setAttribute('cy', y(cv.gexp[i] / E)); d2.setAttribute('opacity', 1);
    showTip(ev, `<div class="t">標的 ${fmtK(cv.x[i])}（${((cv.x[i] / S.data.meta.s_ref - 1) * 100).toFixed(2)}%）</div>
      <div class="r"><span>GEX</span><span>${fmt(cv.gex[i] / E)}</span></div>
      <div class="r"><span>VEX</span><span>${fmt(cv.vex[i] / E)}</span></div>
      <div class="r"><span>GEX+（β=${S.beta.toFixed(1)}）</span><span>${fmt(cv.gexp[i] / E)}</span></div>`);
  });
  hit.addEventListener('mouseleave', () => {
    cross.setAttribute('opacity', 0); d1.setAttribute('opacity', 0); d2.setAttribute('opacity', 0); hideTip();
  });
}


/* --------------------------------------------------------- 到期日結構拆解 */
function drawExpiry(host) {
  host.innerHTML = '';
  const sg = SIGNS[S.sign], exps = S.data.expiries;
  const W = Math.max(host.clientWidth || 900, 320), H = 250;
  const m = { t: 18, r: 14, b: 56, l: 58 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' }, host);
  const g = el('g', { transform: `translate(${m.l},${m.t})` }, svg);

  const rows = exps.map(e => {
    const gx = gexOf(e.totals, sg) / E, vx = vexOf(e.totals, sg) / E;
    return { ...e, gex: gx, vex: vx, gexp: gx + S.beta * vx };
  });
  const all = rows.flatMap(r => [r.gex, r.gexp]).concat([0]);
  let lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo) * 0.12 || 1; lo -= pad; hi += pad;
  const y = v => ih - ((v - lo) / (hi - lo)) * ih;
  const cw = iw / rows.length;
  const bw = Math.max(6, cw * 0.55);

  const yT = niceTicks(lo, hi, 5);
  for (const t of yT) {
    const yy = y(t);
    el('line', { class: 'gl', x1: 0, x2: iw, y1: yy, y2: yy }, g);
    el('text', { class: 'ax', x: -8, y: yy + 3.5, 'text-anchor': 'end' }, g).textContent = t.toFixed(yT.dp);
  }
  el('line', { class: 'zero', x1: 0, x2: iw, y1: y(0), y2: y(0) }, g);
  el('text', { class: 'axname', x: -m.l + 4, y: -6 }, g).textContent = UNIT + ' / 1%';

  rows.forEach((r, i) => {
    const cx = cw * (i + 0.5), x0 = cx - bw / 2;
    const p = el('path', { d: barPath(x0, bw, y(0), y(r.gex)),
                           fill: r.gex >= 0 ? 'var(--pos)' : 'var(--neg)' }, g);
    const hit = el('rect', { x: cw * i, y: 0, width: cw, height: ih, fill: 'transparent' }, g);
    const on = (ev) => {
      p.setAttribute('opacity', .72);
      showTip(ev, `<div class="t">${r.ltd}　${r.kind}　${r.code}</div>
        <div class="r"><span>GEX</span><span>${fmt(r.gex)} ${UNIT} / 1%</span></div>
        <div class="r"><span>VEX</span><span>${fmt(r.vex)} ${UNIT} / vol 點</span></div>
        <div class="r"><span>GEX+（β=${S.beta.toFixed(1)}）</span><span>${fmt(r.gexp)}</span></div>
        <div class="r"><span>剩餘交易日</span><span>${r.trading_days}</span></div>
        <div class="r"><span>未平倉</span><span>${fmtK(r.oi)} 口</span></div>
        <div class="r"><span>ATM 隱含波動率</span><span>${r.atm_iv == null ? '—' : (r.atm_iv * 100).toFixed(2) + '%'}</span></div>`);
    };
    hit.addEventListener('mouseenter', on); hit.addEventListener('mousemove', on);
    hit.addEventListener('mouseleave', () => { p.removeAttribute('opacity'); hideTip(); });
    const tx = el('text', { class: 'ax', x: cx, y: ih + 16, 'text-anchor': 'end',
                            transform: `rotate(-38 ${cx} ${ih + 16})` }, g);
    tx.textContent = r.ltd;
  });

  const d = rows.map((r, i) => (i ? 'L' : 'M') + (cw * (i + 0.5)).toFixed(1) + ' ' + y(r.gexp).toFixed(1)).join('');
  el('path', { d, fill: 'none', stroke: 'var(--curve2)', 'stroke-width': 2, 'stroke-linecap': 'round' }, g);
  rows.forEach((r, i) => el('circle', {
    cx: cw * (i + 0.5), cy: y(r.gexp), r: 4, fill: 'var(--curve2)',
    stroke: 'var(--surface)', 'stroke-width': 2 }, g));
}

/* --------------------------------------------------------- 摘要面板 */
function drawSummary(rows, cv, flip, flipP) {
  const sg = SIGNS[S.sign], meta = S.data.meta, S0 = meta.s_ref;
  const v = view(), tr = v.truncated, tt = v.totals;
  const totG = gexOf(tt, sg);                  // totals 已含輸出範圍外的部分
  const totV = vexOf(tt, sg);
  const totGp = totG + S.beta * totV;
  const totVega = vegaOf(tt, sg);

  const up = rows.filter(r => gexOf(r, sg) > 0).sort((a, b) => gexOf(b, sg) - gexOf(a, sg)).slice(0, 5);
  const dn = rows.filter(r => gexOf(r, sg) < 0).sort((a, b) => gexOf(a, sg) - gexOf(b, sg)).slice(0, 5);
  const vn = rows.filter(r => vexOf(r, sg) < 0).sort((a, b) => vexOf(a, sg) - vexOf(b, sg)).slice(0, 5);
  const cw = rows.reduce((a, r) => (!a || r.oc > a.oc ? r : a), null);
  const pw = rows.reduce((a, r) => (!a || r.op > a.op ? r : a), null);

  const gTone = totG >= 0
    ? '正 — 造市商需逆勢調整，具壓抑波動、把價格拉回的效果'
    : '負 — 造市商需順勢調整，具追漲殺跌、放大波動的效果';
  const vTone = totV < 0
    ? '負 — 隱含波動率上升時造市商需賣出標的，會放大行情'
    : '正 — 隱含波動率上升時造市商需買進標的，會壓抑行情';
  const dist = (x) => x == null ? '—' : ((x / S0 - 1) * 100).toFixed(2) + '%';

  $('#nSum').textContent = S.exp === 'ALL' ? '全到期別合計' : S.exp;
  $('#summary').innerHTML = `
    <div class="hero">
      <div class="k">總 GEX（${S.sign === 'net' ? '買權多・賣權空' : '兩邊皆空'}）</div>
      <div class="v" style="color:${totG >= 0 ? 'var(--pos)' : 'var(--neg)'}">${fmt(totG / E)} ${UNIT} / 1%</div>
      <div class="s">${gTone}</div>
    </div>
    <div class="sumgrid">
      <div class="tile"><div class="k">現貨 S</div><div class="v">${fmtK(S0)}</div><div class="s">${meta.s_ref_source}</div></div>
      <div class="tile"><div class="k">Gamma Flip</div>
        <div class="v" style="color:var(--flip)">${flip == null ? '—' : fmtK(Math.round(flip))}</div>
        <div class="s">距現貨 ${dist(flip)}</div></div>
      <div class="tile"><div class="k">GEX+ Flip</div>
        <div class="v" style="color:var(--flip2)">${flipP == null ? '—' : fmtK(Math.round(flipP))}</div>
        <div class="s">距現貨 ${dist(flipP)}・β=${S.beta.toFixed(1)}</div></div>
      <div class="tile"><div class="k">總 VEX</div>
        <div class="v" style="font-size:17px;color:${totV >= 0 ? 'var(--pos)' : 'var(--neg)'}">${fmt(totV / E)}</div>
        <div class="s">${UNIT} / vol 點（vanna）</div></div>
      <div class="tile"><div class="k">總 GEX+</div>
        <div class="v" style="font-size:17px;color:${totGp >= 0 ? 'var(--pos)' : 'var(--neg)'}">${fmt(totGp / E)}</div>
        <div class="s">= GEX + β×VEX</div></div>
      <div class="tile"><div class="k">總 vega 曝險</div>
        <div class="v" style="font-size:17px;color:var(--ink)">${fmt(totVega / E)}</div>
        <div class="s">${UNIT} / vol 點（部位損益）</div></div>
    </div>
    <div class="rowlist">
      <div><span class="lbl">正 GEX 集中</span>${up.map(r => `<span class="chip p">${fmtK(r.K)} ${fmt(gexOf(r, sg) / E)}</span>`).join('') || '<span style="color:var(--ink3)">無</span>'}</div>
      <div><span class="lbl">負 GEX 集中</span>${dn.map(r => `<span class="chip n">${fmtK(r.K)} ${fmt(gexOf(r, sg) / E)}</span>`).join('') || '<span style="color:var(--ink3)">無</span>'}</div>
      <div><span class="lbl">負 VEX 集中</span>${vn.map(r => `<span class="chip n">${fmtK(r.K)} ${fmt(vexOf(r, sg) / E)}</span>`).join('') || '<span style="color:var(--ink3)">無</span>'}</div>
      <div><span class="lbl">未平倉牆</span>
        <span class="chip">Call ${cw ? fmtK(cw.K) : '—'}・${cw ? fmtK(cw.oc) : 0} 口</span>
        <span class="chip">Put ${pw ? fmtK(pw.K) : '—'}・${pw ? fmtK(pw.op) : 0} 口</span>
        <span style="color:var(--ink3);font-size:11.5px">P/C = ${(v.oi_p / Math.max(v.oi_c, 1)).toFixed(2)}</span></div>
      <div style="color:var(--ink3);font-size:11.5px;margin-top:6px">
        ${vTone}。輸出範圍（±${(tr.band_pct * 100).toFixed(0)}%）外還有 ${tr.n_strikes_dropped} 個履約價、${fmtK(tr.oi_outside)} 口未平倉，
        佔總 GEX ${(Math.abs(gexOf(tr, sg)) / Math.max(Math.abs(totG), 1) * 100).toFixed(2)}%，已計入上方總量。</div>
    </div>`;
}

/* --------------------------------------------------------- 表格 */
function drawTable(rows) {
  const sg = SIGNS[S.sign];
  $('#tbl').querySelector('thead').innerHTML =
    `<tr><th>履約價</th><th>GEX（${UNIT}/1%）</th><th>VEX（${UNIT}/vol點）</th><th>vega 曝險</th>` +
    '<th>Call OI</th><th>Put OI</th><th>ΔCall OI</th><th>ΔPut OI</th><th>隱含波動率</th></tr>';
  $('#tbl').querySelector('tbody').innerHTML = rows.map(r => `<tr>
    <td>${fmtK(r.K)}</td>
    <td style="color:${gexOf(r, sg) >= 0 ? 'var(--pos)' : 'var(--neg)'}">${fmt(gexOf(r, sg) / E)}</td>
    <td style="color:${vexOf(r, sg) >= 0 ? 'var(--pos)' : 'var(--neg)'}">${fmt(vexOf(r, sg) / E, 3)}</td>
    <td style="color:var(--ink2)">${fmt(vegaOf(r, sg) / E, 3)}</td>
    <td>${fmtK(r.oc)}</td><td>${fmtK(r.op)}</td>
    <td style="color:var(--ink2)">${r.dc >= 0 ? '+' : '−'}${fmtK(Math.abs(r.dc))}</td>
    <td style="color:var(--ink2)">${r.dp >= 0 ? '+' : '−'}${fmtK(Math.abs(r.dp))}</td>
    <td>${r.iv == null ? '—' : (r.iv * 100).toFixed(2) + '%'}</td></tr>`).join('');
}

function drawExpTable() {
  $('#tblExp').querySelector('thead').innerHTML =
    '<tr><th>到期別</th><th>類型</th><th>最後交易日</th><th>剩餘交易日</th><th>遠期價</th>' +
    '<th>ATM IV</th><th>偏斜 dσ/dlnK</th><th>未平倉</th><th>GEX</th><th>VEX</th></tr>';
  const sg = SIGNS[S.sign];
  $('#tblExp').querySelector('tbody').innerHTML = S.data.expiries.map(e => `<tr>
    <td>${e.code}</td><td>${e.kind}</td><td>${e.ltd}</td><td>${e.trading_days}</td>
    <td>${fmtK(e.F)}</td><td>${e.atm_iv == null ? '—' : (e.atm_iv * 100).toFixed(2) + '%'}</td>
    <td>${e.skew.toFixed(3)}</td><td>${fmtK(e.oi)}</td>
    <td>${fmt(gexOf(e.totals, sg) / E)}</td><td>${fmt(vexOf(e.totals, sg) / E)}</td></tr>`).join('');
}

/* --------------------------------------------------------- 主繪製 */
function render() {
  const meta = S.data.meta, S0 = meta.s_ref, sg = SIGNS[S.sign];
  const rows = buckets();
  const step = gridStep(rows);
  const cvFull = curve(false);                 // 找 flip 用完整曲線
  const cv = curve(true);                      // 畫圖只畫顯示區間
  const flip = crossings(cvFull.x, cvFull.gex, S0);
  const flipP = crossings(cvFull.x, cvFull.gexp, S0);

  const refs = [
    { v: S0, color: 'var(--spot)', dash: '6 4', label: '現貨 ' + fmtK(S0) },
    { v: flip, color: 'var(--flip)', dash: '2 4', label: 'Gamma Flip ' + (flip == null ? '' : fmtK(Math.round(flip))) },
    { v: flipP, color: 'var(--flip2)', dash: '2 4', label: 'GEX+ Flip ' + (flipP == null ? '' : fmtK(Math.round(flipP))) },
  ];

  $('#lgGex').innerHTML =
    `<span style="color:var(--pos)"><i style="background:currentColor"></i></span><span>正 GEX（穩定 / 壓回）</span>
     <span style="color:var(--neg)"><i style="background:currentColor"></i></span><span>負 GEX（放大 / 追價）</span>
     <span style="color:var(--spot)"><i class="d"></i></span><span>現貨</span>
     <span style="color:var(--flip)"><i class="d"></i></span><span>Gamma Flip</span>`;
  $('#lgVex').innerHTML =
    `<span style="color:var(--neg)"><i style="background:currentColor"></i></span><span>負 VEX（波動上升 → 造市商賣出 → 放大）</span>
     <span style="color:var(--pos)"><i style="background:currentColor"></i></span><span>正 VEX</span>
     <span style="color:var(--spot)"><i class="d"></i></span><span>現貨</span>`;
  $('#lgCurve').innerHTML =
    `<span style="color:var(--curve1)"><i style="background:currentColor"></i></span><span>GEX</span>
     <span style="color:var(--curve2)"><i style="background:currentColor"></i></span><span>GEX+（β=${S.beta.toFixed(1)}）</span>
     <span style="color:var(--spot)"><i class="d"></i></span><span>現貨</span>`;
  $('#lgExp').innerHTML =
    `<span style="color:var(--pos)"><i style="background:currentColor"></i></span><span>GEX（長條）</span>
     <span style="color:var(--curve2)"><i style="background:currentColor"></i></span><span>GEX+（折線，β=${S.beta.toFixed(1)}）</span>`;

  drawBars($('#chGex'), rows, r => gexOf(r, sg) / E,
    (r, v) => v >= 0 ? 'var(--pos)' : 'var(--neg)',
    {
      yLabel: '億元 / 1%', refs, step,
      tip: (r, v) => `<div class="t">履約價 ${fmtK(r.K)}</div>
        <div class="r"><span>GEX</span><span>${fmt(v)} ${UNIT} / 1%</span></div>
        <div class="r"><span>VEX</span><span>${fmt(vexOf(r, sg) / E, 3)} ${UNIT} / vol 點</span></div>
        <div class="r"><span>Call OI</span><span>${fmtK(r.oc)}（${r.dc >= 0 ? '+' : '−'}${fmtK(Math.abs(r.dc))}）</span></div>
        <div class="r"><span>Put OI</span><span>${fmtK(r.op)}（${r.dp >= 0 ? '+' : '−'}${fmtK(Math.abs(r.dp))}）</span></div>
        <div class="r"><span>隱含波動率</span><span>${r.iv == null ? '—' : (r.iv * 100).toFixed(2) + '%'}</span></div>`,
    });

  drawBars($('#chVex'), rows, r => vexOf(r, sg) / E,
    (r, v) => v >= 0 ? 'var(--pos)' : 'var(--neg)',
    {
      yLabel: '億元 / vol 點', refs: [refs[0], refs[1]], step,
      tip: (r, v) => `<div class="t">履約價 ${fmtK(r.K)}</div>
        <div class="r"><span>VEX（vanna）</span><span>${fmt(v, 3)} ${UNIT} / vol 點</span></div>
        <div class="r"><span>vega 曝險</span><span>${fmt(vegaOf(r, sg) / E, 3)} ${UNIT} / vol 點</span></div>
        <div class="r"><span>Call / Put OI</span><span>${fmtK(r.oc)} / ${fmtK(r.op)}</span></div>`,
    });

  drawCurve($('#chCurve'), cv, refs);
  drawExpiry($('#chExp'));
  drawSummary(rows, cvFull, flip, flipP);
  drawTable(rows);
  drawExpTable();
}

/* --------------------------------------------------------- 事件 */
function segment(host, key, cast, after) {
  if (!host) return;
  host.addEventListener('click', (ev) => {
    const b = ev.target.closest('button'); if (!b) return;
    [...host.querySelectorAll('button')].forEach(x => x.setAttribute('aria-pressed', x === b));
    S[key] = cast(b.dataset.v); (after || render)();
  });
}

function methodology() {
  const m = S.data.meta;
  $('#meth').innerHTML = `
  <div class="warn"><b>先講最重要的限制。</b>「造市商曝險」這個名字是慣例，不是觀測。
  期交所公布的是全市場逐履約價的未平倉量，<b>沒有</b>任何欄位告訴你哪些部位屬於造市商、方向是多還是空。
  這張圖是在「買權由造市商作多、賣權由造市商放空」這個<b>假設</b>下算出來的，
  跟真實的造市商帳本可能相差很遠。把它當成<b>全市場 gamma / vanna 結構的描述</b>來用是合理的；
  把它當成訊號來下單之前，請自己先做過檢定。</div>

  <h3>1. 三個定義式</h3>
  <code>GEX(K) = M × S² × 0.01 × Σ sign × gamma × OI</code>　→　標的每移動 1%，造市商 delta 名目金額的變動量<br>
  <code>VEX(K) = −M × S ÷ 100 × Σ sign × vanna × OI</code>　→　隱含波動率每上升 1 個百分點，造市商 delta 名目金額的變動量<br>
  <code>GEX+ = GEX + β × VEX</code>　→　β 的意思是「標的每移動 1%，隱含波動率反向變動 β 個波動點」<br>
  <code>M = ${m.multiplier} 元/點</code>（TXO 契約乘數）。sign 由上方「造市商假設」決定，三個式子共用。

  <h3>2. VEX 用 vanna 不用 vega</h3>
  這張圖描述的是造市商<b>被迫調整的避險流量</b>。vega 講的是部位損益（波動率動了賺賠多少），
  vanna 講的才是流量（波動率動了必須去市場上買賣多少標的）——跟 gamma 是同一類的東西。<br>
  還有一個現實理由：同履約價的買賣權 vega 完全相等（put-call parity 的直接結果），
  所以 <code>Σ sign × vega × OI</code> 在買權多賣權空的慣例下會互相抵消、恆在零附近，沒有資訊。
  vanna 不會，因為它在價平兩側變號，跟 <code>Call OI − Put OI</code> 的變號剛好互相配合，
  於是兩側同號、價平附近趨近於零——這就是 VEX 圖中間那個凹陷的來源。
  vega 曝險仍然有意義（造市商是波動率的多方還是空方），放在摘要與資料表裡當附加欄位。

  <h3>3. 參考標的價用加權指數現貨</h3>
  S 用證交所的發行量加權股價指數收盤，所以 Gamma Flip 講出來直接是現貨價位，跟看盤軟體對得起來。<br>
  但<b>選擇權定價不用現貨</b>：每個到期別由自己的結算價 put-call parity 反解遠期
  <code>F = K + (C − P)</code>（價平 ±3% 取中位數）。用現貨當標的會讓 parity 破裂，
  同一履約價的買權與賣權會反解出不同的隱含波動率。
  情境曲線平移時，各到期別遠期依 <code>F_e × (S / S₀)</code> 同比例移動，保持基差比例。

  <h3>4. 隱含波動率只取價外那一側</h3>
  <code>K &lt; F</code> 用賣權、<code>K ≥ F</code> 用買權反解，再讓同履約價的買賣權共用這個 IV。
  深度價內的結算價時間價值常常只有一兩點，IV 對它極度敏感，拿來反解會出現假的高波動率。
  反解用二分法保證收斂加牛頓法收尾，不用純割線法（會在深度價內停滯）。

  <h3>5. 到期時間 T</h3>
  臺指選擇權的最終結算價在「最後交易日之次一營業日」開盤後 15 分鐘決定，所以把結算日也算進來，
  再用 252 個交易日折成年（休市日表在 <code>calendar_tw.txt</code>）。當日到期的契約直接排除。<br>
  <b>T 的慣例對 GEX 幾乎沒有影響</b>：IV 是從價格反解的，<code>σ√T</code> 被市價釘住，
  而 <code>gamma ≈ φ(d₁)/(F·σ√T)</code>，兩邊的 T 互相抵消。VEX 與 vega 曝險則會受影響。

  <h3>6. 資料與更新</h3>
  來源：${m.source}。只取<b>一般交易時段</b>與<b>結算價</b>（大量履約價當天沒有成交，收盤價是空的）。
  本日採計 ${fmtK(m.n_legs)} 份契約、${m.n_expiries} 個到期日、${fmtK(m.oi_total)} 口未平倉，
  OI 覆蓋率 ${(m.oi_coverage * 100).toFixed(1)}%（反解不出隱含波動率的會被剔除）。<br>
  盤中沒有即時未平倉量，期交所的 OI 是盤後才公布，所以這張圖描述的是<b>前一個收盤</b>的結構，
  不是盤中即時曝險。資料產生時間 ${m.generated_at}。

  <h3>7. 已知還沒做的事</h3>
  ・沒有做流動性加權，冷門履約價的結算價是期交所用模型算的，權重跟熱門履約價一樣。<br>
  ・情境曲線假設隱含波動率的水準不隨標的變動（β 只補了一階的線性回饋）。<br>
  ・只做 TXO，沒有納入電子、金融、小型台指選擇權。
  `;
}

function mountExpiries() {
  const seg = $('#segExp'), sel = $('#selExp'), ex = S.data.expiries;
  if (!S.data.views[S.exp]) S.exp = 'ALL';
  if (ex.length > 12) {                       // 美股到期別太多，改用下拉
    seg.style.display = 'none'; sel.style.display = '';
    sel.innerHTML = `<option value="ALL">合併（全部 ${ex.length} 個）</option>` +
      ex.map(e => `<option value="${e.code}"${e.code === S.exp ? ' selected' : ''}>${e.ltd}　${e.kind}　${fmtK(e.oi)} 口</option>`).join('');
  } else {
    sel.style.display = 'none'; seg.style.display = '';
    seg.innerHTML = `<button data-v="ALL">合併</button>` +
      ex.map(e => `<button data-v="${e.code}" title="${e.kind}・到期 ${e.ltd}・${fmtK(e.oi)} 口">${e.ltd.slice(5)}</button>`).join('');
    [...seg.querySelectorAll('button')].forEach(b => b.setAttribute('aria-pressed', b.dataset.v === S.exp));
  }
}


function howto() {
  const m = S.data.meta, us = m.symbol !== 'TXO';
  $('#howto').innerHTML = `
  <p style="margin:0 0 12px">這張圖畫的是<b>地形</b>，不是天氣。它告訴你造市商在哪些價位會被迫買、
  在哪些價位會被迫賣，不告訴你價格會往哪邊走。下面五步是使用順序，照著跑一遍再看盤。</p>

  <h3>步驟 1　先看三個總量的「方向」，不是絕對值</h3>
  總 GEX 為正，造市商要逆勢調整，行情傾向被磨在區間裡；為負則要順勢調整，一有變動就被放大。<br>
  總 VEX 幾乎永遠是負的（結構使然），所以要看的是<b>有多負</b>，那是波動率上升時會被倒出來的量。<br>
  總 GEX+ 是兩者合成，最接近真實環境。<br>
  <b>單日數字沒有意義，要跟前幾天比。</b> 用左上角的「資料日期」切回前幾天，看這三個數字往哪個方向動。

  <h3>步驟 2　分清楚「門檻有沒有動」與「距離有沒有變遠」</h3>
  <div class="warn">這是整套讀法最容易搞錯、也最值錢的一件事。</div>
  兩條 Flip 幾乎沒動、但現貨往上跑了一段 → 安全距離是<b>價格自己墊出來的</b>，不是結構撐出來的。
  哪天原路走回去，門檻還在原地等，一點都沒少。<br>
  Flip 自己往上移動 → 才是真的有人在下面多加了一層。<br>
  兩件事在圖上看起來都是「離翻負還很遠」，但賠率完全不同。摘要卡上的「距現貨 %」就是給你追這個用的。

  <h3>步驟 3　看到期日結構拆解，找出「護甲什麼時候脫掉」</h3>
  翻到最下面那張「到期日結構拆解」。要問的問題只有一個：<b>現在這些厚度是誰撐的？</b><br>
  如果單一到期日的 GEX 比全部到期日加總還大，代表整張圖看起來的穩定幾乎都是那一格給的——
  那天結算完，扶著的手就鬆了。<br>
  還有一個容易誤判的地方：<b>未平倉最多的到期日，不一定是 GEX 最大的到期日。</b>
  越接近到期，每一口的 gamma 越大，所以近月常常用比較少的口數撐出更大的曝險。
  結算之後接手的那批遠月，撐不出同樣的厚度。<br>
  這一步給的是<b>時間軸</b>，不是價位。價位可以每天重算，日期不會挪。

  <h3>步驟 4　讀牆與坑，但別把未平倉當成 gamma</h3>
  「正 GEX 集中」是上方的牆，「負 GEX 集中」是下方的坑。看距離現貨幾 % 比看絕對價位有用。<br>
  注意榜上常常會出現一個<b>貼著現價、未平倉其實不多</b>的履約價——它上榜純粹是因為價平的每口
  gamma 最大。這種牆會跟著價格移動，不是固定的地形。想分辨，把資料表打開對照該履約價的未平倉口數。<br>
  ${us ? '美股這邊還要留意：長天期履約價會有很大的未平倉，但每口 gamma 很小，在 GEX 上幾乎不佔份量。'
       : '台指這邊週選與月選的履約價間距不同（50 點 vs 100 點），合併看時建議把「履約價分桶」調成 100 點。'}

  <h3>步驟 5　對照「正 GEX 集中」與「負 VEX 集中」有沒有重疊</h3>
  如果同一批履約價同時出現在兩張榜上，那是<b>同一批部位的兩張臉</b>。<br>
  賣上方買權收租的部位，在平常的日子裡提供正 gamma，幫忙把價格壓在區間裡磨；
  但同一批部位的 vanna 是負的，波動率一跳，避險需求就反轉。<br>
  <b>平常幫忙壓波動的那幾堵牆，就是波動來的時候最先鬆手的那幾堵。</b>
  這是持倉留下的形狀，不是有人在佈局。

  <h3>最後：這張圖不能拿來做什麼</h3>
  有坑不代表一定會跌，沒坑也不代表跌不下去——只代表跌下去的時候，<b>沒有人幫你踩煞車</b>。<br>
  這是<b>波動結構圖，不是買賣訊號</b>。把 GEX 當進出場訊號用，等於把地圖當導航。<br>
  ${m.tz_note}，是<b>收盤快照</b>不是盤中即時；期交所與 OCC 的未平倉量都要等盤後才公布。<br>
  遇到財報、結算這種事件，如果事件的隱含振幅大過整張地圖的寬度，那些牆與坑就不再是路障，只是里程碑。<br>
  還有最根本的一條：<b>造市商的方向是假設，不是觀測。</b>詳見下一區「怎麼算的」。

  <p style="color:var(--ink3);font-size:11.5px;margin-top:14px">
  這套讀圖順序整理自羊叔開講（gooptions.cc）對 GEX 結構圖的實例解說，用我自己的話重寫並對應到本站的控制項。
  數字與計算全部由本專案自己從公開資料算出，與該站無關。</p>`;
}

/* --------------------------------------------------------- 啟動 */
(async function boot() {
  const embedded = window.__GEXMAP__;
  const syms = embedded
    ? [{ code: embedded.meta.symbol, label: embedded.meta.label, desc: embedded.meta.desc }]
    : ((await loadJson('data/symbols.json')) || {}).symbols ||
      [{ code: 'TXO', label: '台指 TXO', desc: '臺灣加權股價指數選擇權' }];

  $('#segSym').innerHTML = syms.map(x =>
    `<button data-v="${x.code}"><b>${x.label}</b><i>${x.desc}</i></button>`).join('');
  $('#segSym').addEventListener('click', ev => {
    const b = ev.target.closest('button'); if (!b) return;
    switchTo(b.dataset.v);
  });

  await switchTo(syms[0].code);

  $('#selDate').addEventListener('change', e => switchTo(S.sym, e.target.value));
  $('#segExp').addEventListener('click', ev => {
    const b = ev.target.closest('button'); if (!b) return;
    [...$('#segExp').querySelectorAll('button')].forEach(x => x.setAttribute('aria-pressed', x === b));
    S.exp = b.dataset.v; render();
  });
  $('#selExp').addEventListener('change', e => { S.exp = e.target.value; render(); });
  segment($('#segSign'), 'sign', v => v);
  segment($('#segCvd'), 'cvd', v => v, () => {
    document.documentElement.setAttribute('data-cvd', S.cvd); render();
  });
  $('#selBand').addEventListener('change', e => { S.band = +e.target.value; render(); });
  $('#selBucket').addEventListener('change', e => { S.bucket = +e.target.value; render(); });
  $('#rngBeta').addEventListener('input', e => {
    S.beta = +e.target.value; $('#valBeta').textContent = S.beta.toFixed(1); render();
  });
  let t; addEventListener('resize', () => { clearTimeout(t); t = setTimeout(render, 140); });
})();
