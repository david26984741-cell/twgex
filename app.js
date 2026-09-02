/* 台指選擇權曝險地圖 — 前端。無外部相依。
   資料是「積木」（買權/賣權的 gamma 項與 vega 項分開放），
   造市商方向假設與 beta 都在這裡即時組合，不需要重跑後端。 */
'use strict';

let E = 1e8;                                     // 顯示單位除數，載入後由 meta 決定
let UNIT = '億元';
const $ = (s) => document.querySelector(s);
const fmt = (v, d = 2) => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(d);
const fmtK = (v) => v.toLocaleString('en-US', { maximumFractionDigits: 0 });
/* KPI 磚用：上千就進位成整數並加千分位，不然一格塞不下也不好認 */
const fmtBig = (v) => Math.abs(v) >= 1000
  ? (v >= 0 ? '+' : '−') + Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 })
  : fmt(v);
const SHORT_UNIT = { '百萬美元': 'US$M', '億元': '億' };
const shortUnit = () => SHORT_UNIT[UNIT] || UNIT;
/* 未平倉增減：算不出來時是 null（例如選了單一到期別，而前一日只留下逐履約價合計） */
const fmtD = (v) => v == null ? '—' : (v >= 0 ? '+' : '−') + fmtK(Math.abs(v));
// 價格 / 履約價：台指是四五位數整數，美股是三位數帶小數，小數位要跟著量級走
const fmtP = (v) => v == null ? '—' : Math.abs(v) >= 10000
  ? v.toLocaleString('en-US', { maximumFractionDigits: 0 })
  : v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
// 座標軸刻度：不需要小數就不要印
const fmtA = (v) => v.toLocaleString('en-US',
  { maximumFractionDigits: Math.abs(v) >= 10000 ? 0 : (Number.isInteger(v) ? 0 : 1) });
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
// 字級倍率（CSS 變數 --fs），圖表的邊界與高度要跟著它走，不然標籤會擠在一起
const fsScale = () => parseFloat(getComputedStyle(document.documentElement)
  .getPropertyValue('--fs')) || 1;
const isNarrow = () => innerWidth < 760;

const S = {                                      // UI 狀態
  data: null, sym: null, exp: 'ALL', band: 0.20, bucket: null,
  sign: 'net', beta: 1.0, cvd: 0,
  // 使用者自己選過的顯示區間。null = 還沒選過，交給 pickBand 自動挑。
  // 一旦選過就不再自動覆蓋——換標的時保持原樣是使用者的預期。
  bandPref: null,
  // 分桶要逐標的記：台指是 50/100/200 點、美股是 0.5/1/2 元，數值本身跨標的沒有意義，
  // 但「在台指那頁選過 100 點」這件事應該在切回台指時還在。
  bucketBy: {},
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

/* --------------------------------------------------------- 取資料
   同一份 JSON 在一次瀏覽裡只抓一次。SPX 的 latest.json 解開有 2.6 MB，
   以前每次切分頁都重抓（cache: no-store），光網路來回就要 1.4 秒——
   那才是「切換很卡」的主因，不是繪圖。快取存的是 Promise，所以
   「滑過去先抓」與「點下去要用」不會變成兩個請求。 */
const CACHE = new Map();

function getJson(url, must) {
  if (CACHE.has(url)) return CACHE.get(url);
  const p = fetch(url, { cache: 'no-cache' })       // 仍會跟伺服器確認新舊，只是不重下載整包
    .then(r => {
      if (!r.ok) {
        if (must) throw new Error(`讀不到 ${url}（HTTP ${r.status}）`);
        return null;
      }
      return r.json();
    });
  p.catch(() => CACHE.delete(url));                 // 失敗不要留在快取裡，下次還能重試
  CACHE.set(url, p);
  return p;
}

const dataUrl = (sym, day) =>
  day ? `data/${sym}/history/${day}.json` : `data/${sym}/latest.json`;

async function load(sym, day) {
  if (window.__GEXMAP__ && !day) return window.__GEXMAP__;
  return getJson(dataUrl(sym, day), true);
}

function loadJson(url) {
  if (window.__GEXMAP__) return Promise.resolve(null);
  return getJson(url, false).catch(() => null);
}

// 滑鼠移到分頁上（或手指按下）就先開始抓，等真的點下去時通常已經到了
function prefetch(sym) {
  if (window.__GEXMAP__ || !sym) return;
  loadJson(dataUrl(sym));
  loadJson(`data/${sym}/index.json`);
}

function mountDates(idx) {
  const sel = $('#selDate');
  if (!idx || !idx.dates || idx.dates.length < 2) { $('#ctlDate').style.display = 'none'; return; }
  const cur = S.data.meta.trade_date.replace(/\//g, '');
  sel.innerHTML = idx.dates.slice().reverse()
    .map(d => `<option value="${d}"${d === cur ? ' selected' : ''}>${d.slice(0,4)}/${d.slice(4,6)}/${d.slice(6)}</option>`).join('');
  $('#ctlDate').style.display = '';
}

/* 網址狀態：#TXO 或 #QQQ@20260825。
   之前切標的完全不動網址，重新整理一定跳回第一個標的，也沒辦法把「QQQ 這一天」傳給別人。 */
function readHash() {
  const h = decodeURIComponent((location.hash || '').replace(/^#/, '')).trim();
  if (!h) return {};
  const [sym, day] = h.split('@');
  return { sym: (sym || '').toUpperCase(), day: /^\d{8}$/.test(day || '') ? day : undefined };
}
function writeHash() {
  const cur = S.data && S.data.meta, sel = $('#selDate');
  const isLatest = !sel.value || getComputedStyle($('#ctlDate')).display === 'none'
                   || sel.selectedIndex === 0;
  const h = '#' + S.sym + (isLatest ? '' : '@' + sel.value);
  if (location.hash !== h) history.replaceState(null, '', h);
  const p = loadPref(); p.sym = S.sym; savePref(p);       // 沒帶網址時回到上次看的標的
}

async function switchTo(sym, day) {
  const box = $('#err');
  try {
    // 兩個請求同時發：以前是先等資料再等日期清單，兩段來回加起來要一秒多
    const idxP = loadJson(`data/${sym}/index.json`);
    S.data = await load(sym, day);
    S.sym = sym;
    if (!day) S.exp = 'ALL';
    applyMeta();
    mountExpiries();
    mountDates(await idxP);
    methodology();
    howto();
    render();
    writeHash();
    box.style.display = 'none';
  } catch (err) {
    box.style.display = 'block';
    box.innerHTML = `<b>${sym} 的資料還沒產生：</b>${err.message}<br>` +
      '<span style="opacity:.8">排程跑過一次之後就會出現。</span>';
  }
}


/* --------------------------------------------------------- 各標的的身分說明
   同一個指數在不同交易所有不同的一本帳，結算方式也不同。這段是為了讓看圖的人
   一眼知道「這張圖畫的是哪一本帳」，不要拿 A 的地圖去走 B 的路。
   量級數字量測於 2026/08/21 收盤，會隨時間變動，只當數量級參考。 */
const SYM_NOTES = {
  TXO: {
    what: '臺灣期貨交易所的<b>台指選擇權</b>（TXO），<b>現金結算</b>，每口 = 指數 × NT$50。',
    more: '最終結算價在最後交易日的<b>次一營業日</b>開盤後 15 分鐘內決定，所以本站的 T 算到結算日、不是最後交易日。'
  },
  SPX: {
    what: '<b>CBOE</b> 的 S&P 500 <b>指數</b>選擇權（SPX / SPXW），<b>現金結算</b>、歐式，每口 = 指數 × $100。',
    more: '這是全美最大的一本 S&P gamma 帳。<b>如果你交易的是 CME 的 ES 日選，請看 ES 分頁</b>——那是另一個交易所、另一本帳，'
        + '同一個指數但部位分佈不一樣。另外本站把 <b>SPX（AM 結算月選）</b>與 <b>SPXW（PM 結算週選 / 日選）</b>拆成獨立的到期別。',
    size: '2026/08/21 未平倉名目約 $17.4 兆 — 約為 SPY 的 12 倍、CME ES 的 10 倍'
  },
  ES: {
    what: '<b>CME</b> 的 E-mini S&P 500 <b>期貨</b>選擇權，被指派後<b>會變成一口 ES 期貨部位</b>（不是現金結算），每口 = 指數 × $50。',
    more: 'Globex 幾乎 24 小時交易，台灣白天也能調部位。<b>想看整體 S&P 的 gamma 地形請切 SPX 分頁</b>，那本帳大得多；'
        + '但你實際成交、實際被避險的是這一本。每口只有 SPX 的一半大，部位顆粒度比較細。',
    size: '2026/08/21 未平倉名目約 $1.76 兆（SPX 的 1/10）；但「每日到期」那一段當日成交 79.8 萬口，與 SPXW 的 98.5 萬口同一量級'
  },
  SPY: {
    what: '<b>SPY ETF</b> 選擇權，美式，到期<b>交割 100 股 SPY</b>，每口 = 價格 × $100。',
    more: 'S&P 的 gamma 主體不在這裡，在 <b>SPX</b>（切上一個分頁）。SPY 適合看散戶與 ETF 端的部位，量級只有 SPX 的十二分之一。',
    size: '2026/08/21 未平倉名目約 $1.40 兆'
  },
  QQQ: {
    what: '<b>QQQ ETF</b> 選擇權，美式，到期<b>交割 100 股 QQQ</b>，每口 = 價格 × $100。',
    more: '跟 S&P 相反，<b>那斯達克的 gamma 主體就在這裡</b>：QQQ 比 NDX（約 $0.47 兆）和 CME 的 NQ 選擇權（約 $0.12 兆）都大，'
        + '所以本站沒有另外做 NQ 分頁——加了也幾乎不會改變畫面。',
    size: '2026/08/21 未平倉名目約 $0.91 兆'
  },
};

/* 標的說明不再佔畫面，改成標題旁邊那個 ⓘ 點開才看。 */
let SYM_HELP = '';
function renderSymNote(sym) {
  const n = SYM_NOTES[sym], m = S.data && S.data.meta;
  SYM_HELP = !n ? '' : (n.what + (n.more ? '　' + n.more : '')
    + (n.size ? `<div style="color:var(--ink3);margin-top:6px">${n.size}</div>` : ''));
  if (m) SYM_HELP += `<div style="color:var(--ink3);margin-top:8px;border-top:1px solid #22303f;padding-top:7px">`
    + `${m.source}<br>${m.price_note}<br>產生於 ${m.generated_at}`
    + (m.prev_trade_date ? `<br>OI 增減對比 ${m.prev_trade_date}` : '') + `</div>`;
}

/* 卡片右上角那幾顆膠囊。單位固定、顯示區間會變，所以每次重畫都叫一次。 */
function pills() {
  const m = S.data && S.data.meta; if (!m) return;
  const band = (S.band * 100).toFixed(0);
  // 單位已經畫在圖裡的軸標題上了，膠囊不要再重複一次
  $('#nGex').textContent = `圖表顯示${spotWord()} ±${band}%`;
  $('#nVex').textContent = '負值代表波動放大情境';
  $('#nCurve').textContent = `Sticky IV　·　β = ${S.beta.toFixed(1)}`;
  $('#nSum').textContent = (S.exp === 'ALL' ? '' : S.exp + '　·　')
    + `${fmtK(m.n_legs)} 份契約　·　${m.n_expiries} 個到期日`;
}

/* 預設顯示區間：±20% 常常把 8~9 成的曝險擠在中間三分之一，兩側全是幾乎為零的長條。
   改成挑「能涵蓋八成 |GEX| 的最窄選項」——一般日子會落在 ±10%，
   遇到曝險真的很分散的日子才自動放寬。上限用資料裡的 default_view_band。 */
function pickBand(cap) {
  const st = (S.data.views.ALL || {}).strikes || [], S0 = S.data.meta.s_ref;
  const opts = [...$('#selBand').options].map(o => parseFloat(o.value))
    .filter(v => v <= cap + 1e-9).sort((a, b) => a - b);
  if (!opts.length) return cap;
  if (!st.length || !S0) return opts[opts.length - 1];
  const g = r => Math.abs((r.gc || 0) - (r.gp || 0));
  const tot = st.reduce((a, r) => a + g(r), 0);
  if (!tot) return opts[opts.length - 1];
  for (const b of opts) {
    const inb = st.reduce((a, r) => a + (Math.abs(r.K / S0 - 1) <= b ? g(r) : 0), 0);
    if (inb / tot >= 0.80) return b;
  }
  return opts[opts.length - 1];
}

/* ---------------------------------------------------------- 資料過期偵測
   ES 是人工抓的、排程也可能整天沒跑，資料會安靜地停在某一天。
   這裡用休市日表數「資料日之後到今天為止還有幾個交易日」，超過該有的落差就跳提醒。 */
const CAL = {};
function loadCal(file) {
  if (!CAL[file]) {
    CAL[file] = fetch(file, { cache: 'no-cache' })
      .then(r => r.ok ? r.text() : '')
      .then(t => new Set(t.split('\n').map(l => l.trim())
        .filter(l => l && !l.startsWith('#')).map(l => l.replace(/-/g, '/'))))
      .catch(() => new Set());
  }
  return CAL[file];
}
const ymd = d => d.getUTCFullYear() + '/' + String(d.getUTCMonth() + 1).padStart(2, '0')
              + '/' + String(d.getUTCDate()).padStart(2, '0');
/* 以某個時區偏移看「今天」是哪一天（回傳一個 UTC 午夜的 Date，方便逐日加減） */
function todayIn(offsetHours) {
  const t = new Date(Date.now() + offsetHours * 3600e3);
  return new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), t.getUTCDate()));
}
/* 資料日之後到今天為止（含今天）有幾個交易日 */
function tradingDaysSince(tradeDate, hol, today) {
  const [y, m, d] = tradeDate.split('/').map(Number);
  const cur = new Date(Date.UTC(y, m - 1, d));
  let n = 0, guard = 0;
  while (cur < today && guard++ < 400) {
    cur.setUTCDate(cur.getUTCDate() + 1);
    const wd = cur.getUTCDay();
    if (wd !== 0 && wd !== 6 && !hol.has(ymd(cur))) n++;
  }
  return n;
}
async function staleNotice(meta) {
  const box = $('#staleWarn');
  if (!box || !meta.trade_date) return;
  const tw = meta.symbol === 'TXO';
  const hol = await loadCal(tw ? 'calendar_tw.txt' : 'calendar_us.txt');
  // 台指看台北的今天；美股看美東的今天（用 UTC−5 保守估，寧可少報不要誤報）
  const today = todayIn(tw ? 8 : -5);
  const n = tradingDaysSince(meta.trade_date, hol, today);
  // 該有的落差：台指當天更新（跑之前會落後 1 天）；美股本來就是前一個交易日（跑之前落後 2 天）
  const ok = tw ? 1 : 2;
  if (n <= ok) { box.style.display = 'none'; return; }
  const late = n - ok;
  const how = meta.symbol === 'ES'
    ? 'ES 要在自己的電腦上用 <code>tools/cme.html</code> 抓（CME 擋伺服器端的 IP），最可能是那班沒跑。'
    : tw ? '可能是期交所檔案延後上架，或排程沒跑——到 GitHub 的 Actions 手動按一次 Run workflow 就會補。'
         : '可能是排程沒跑或 CBOE 那邊還沒更新——到 GitHub 的 Actions 手動按一次 Run workflow 就會補。';
  box.style.display = '';
  box.innerHTML = `<b>這份資料已經 ${late} 個交易日沒更新。</b>`
    + `目前顯示的是 <b>${meta.trade_date}</b> 的收盤，`
    + `照正常節奏現在應該要有更新的資料了。<br>${how}`;
}

function applyMeta() {
  const m = S.data.meta;
  E = m.unit_div || 1e8;
  UNIT = m.unit || '億元';
  const sb = $('#selBand');                    // option 的字串與數值不一定字面相等，用數值比對
  const cap = m.default_view_band || 0.20;
  // 使用者自己選過顯示區間的話就沿用，不要每次換標的又被自動判斷蓋掉。
  // 只有還沒選過（bandPref 是 null）才讓 pickBand 挑一個適合這個標的的。
  // 沿用時仍受這個標的的輸出範圍限制——挑不超過 cap 的最接近選項。
  const want = S.bandPref != null ? Math.min(S.bandPref, cap) : pickBand(cap);
  const usable = [...sb.options].filter(o => parseFloat(o.value) <= cap + 1e-9);
  const opt = (usable.length ? usable : [...sb.options]).reduce((a, o) =>
    Math.abs(parseFloat(o.value) - want) < Math.abs(parseFloat(a.value) - want) ? o : a);
  sb.value = opt.value; S.band = parseFloat(opt.value);
  mountBuckets();
  $('#symTitle').textContent = m.label;
  $('#mSubline').innerHTML = `<b>${m.trade_date}</b> 收盤`;
  $('#hGex').textContent = m.label + ' 各履約價 GEX';
  $('#hVex').textContent = m.label + ' 各履約價 VEX';
  // 未平倉日與報價日不一致時要講出來（美股常見：OCC 隔一個營業日才發布未平倉量）
  const warn = $('#dateWarn');
  if (m.oi_as_of && m.price_as_of && m.oi_as_of !== m.price_as_of) {
    warn.style.display = '';
    // 報價到底是「前一個收盤」還是「當天盤中」，差很多。用 CBOE 給的報價時間判斷。
    const t = /T(\d\d):(\d\d)/.exec(m.quote_time || '');
    const mins = t ? (+t[1]) * 60 + (+t[2]) : null;
    const intra = mins != null && mins >= 9 * 60 + 30 && mins < 16 * 60;   // 美東 09:30–16:00
    const when = t ? `${m.price_as_of} ${t[1]}:${t[2]}（美東）` : m.price_as_of;
    warn.innerHTML = intra
      ? `<b>報價是盤中的，未平倉量是前一個收盤的：</b>未平倉量為 <b>${m.oi_as_of}</b> 收盤，` +
        `報價取自 <b>${when}</b> 的<b>盤中</b>報價。` +
        `隱含波動率、gamma、vanna 都跟著較新的報價走，未平倉量還停在前一天，` +
        `<b>兩者不是同一個時點</b>——當成「用昨天的部位、看今天的價格」來讀，不要當成前一日的收盤地圖。` +
        `（成因是排程被延遲到美股開盤之後才跑。）`
      : `<b>未平倉量與報價不同日：</b>未平倉量為 <b>${m.oi_as_of}</b> 收盤，` +
        `報價為 <b>${when}</b>。本頁以未平倉日標示，隱含波動率則來自較新的那組報價。` +
        `（OCC 每個營業日早上才發布前一日的未平倉量，排程若在發布前跑就會出現這個情況。）`;
  } else { warn.style.display = 'none'; }
  staleNotice(m);
  renderSymNote(m.symbol);
  pills();
  document.title = `${m.label} 選擇權曝險地圖`;
  [...document.querySelectorAll('#segSym button')].forEach(b =>
    b.setAttribute('aria-pressed', b.dataset.v === S.sym));
}

/* --------------------------------------------------------- 資料整形 */
function view() { return S.data.views[S.exp] || S.data.views.ALL; }
// 標的價的稱呼：指數 / ETF 是「現貨」，ES 這種期貨選擇權是「期貨」
function spotWord() { return (S.data && S.data.meta && S.data.meta.s_label) || '現貨'; }

function buckets() {
  const v = view(), S0 = S.data.meta.s_ref, b = S.bucket;
  const lo = S0 * (1 - S.band), hi = S0 * (1 + S.band);
  const m = new Map();
  for (const r of v.strikes) {
    if (r.K < lo || r.K > hi) continue;
    const k = b > 0 ? +(Math.round(r.K / b) * b).toFixed(4) : r.K;
    let a = m.get(k);
    if (!a) m.set(k, a = { K: k, gc: 0, gp: 0, wc: 0, wp: 0, vc: 0, vp: 0,
                           oc: 0, op: 0, dc: null, dp: null, ivn: 0, ivd: 0 });
    a.gc += r.gc; a.gp += r.gp; a.wc += r.wc; a.wp += r.wp; a.vc += r.vc; a.vp += r.vp;
    a.oc += r.oc; a.op += r.op;
    // 前一日未平倉不可得時是 null，不能當成 0 加進來（會變成「整批都是新倉」）
    if (r.dc != null) a.dc = (a.dc || 0) + r.dc;
    if (r.dp != null) a.dp = (a.dp || 0) + r.dp;
    if (r.iv != null) { a.ivn += r.iv * (r.oc + r.op); a.ivd += r.oc + r.op; }
  }
  const out = [...m.values()].sort((x, y) => x.K - y.K);
  for (const a of out) a.iv = a.ivd ? a.ivn / a.ivd : null;
  return out;
}

// 分桶後的網格間距（原始履約價時取相鄰履約價的最小間距，長條寬度要用）
function gridStep(rows) {
  if (S.bucket > 0) return S.bucket;
  let d = Infinity;
  for (let i = 1; i < rows.length; i++) d = Math.min(d, rows[i].K - rows[i - 1].K);
  return isFinite(d) && d > 0 ? d : 50;
}

// 原生履約價間距（台指 50 點、美股 0.5~5 元），分桶選項由它推出來
// 履約價的「原生間距」。不能直接取最小間距：調整後的非標準序列會毀掉它——
// 例如 QQQ 有一組 xxx.78 的調整履約價，和旁邊的標準履約價只差 0.22，
// 用最小值會讓分桶選項變成 0.44 / 0.88 這種沒意義的數字。
// 規則：取「最小的、夠常見（≥15%）、而且能整除主間距」的那個間距。
// 前一個條件擋掉零星雜訊，後一個條件擋掉調整履約價（0.22 除不進 1 或 5）。
// 台指同時有週選（50 點）與月選（100 點）時，50 佔三成以上且能整除 100 → 正確取到 50。
function nativeStep() {
  const ks = view().strikes.map(r => r.K).sort((a, b) => a - b);
  const cnt = new Map(); let tot = 0;
  for (let i = 1; i < ks.length; i++) {
    const g = +(ks[i] - ks[i - 1]).toFixed(6);
    if (g > 1e-9) { cnt.set(g, (cnt.get(g) || 0) + 1); tot++; }
  }
  if (!tot) return 50;
  let modal = null, modalN = -1;
  for (const [g, n] of cnt) if (n > modalN || (n === modalN && g < modal)) { modal = g; modalN = n; }
  for (const g of [...cnt.keys()].sort((a, b) => a - b)) {
    if (cnt.get(g) / tot < 0.15) continue;
    const q = modal / g;
    if (Math.abs(q - Math.round(q)) < 1e-6 && Math.round(q) >= 1) return g;
  }
  return modal;
}

function mountBuckets() {
  const g = nativeStep(), sel = $('#selBucket');
  const tw = S.data.meta.symbol === 'TXO';
  const opts = [[0, '原始履約價']].concat([2, 4, 10].map(k => {
    const v = +(g * k).toFixed(4);
    const n = Number.isInteger(v) ? fmtK(v) : v.toLocaleString('en-US', { maximumFractionDigits: 2 });
    return [v, tw ? `每 ${n} 點` : `每 $${n}`];
  }));
  // 這個標的上次選過什麼就用什麼；沒有的話才落到預設。
  const remembered = S.bucketBy[S.data.meta.symbol];
  if (remembered != null && opts.some(o => o[0] === remembered)) {
    S.bucket = remembered;
  } else if (S.bucket == null || !opts.some(o => o[0] === S.bucket)) {
    // 手機上原始履約價會擠成一片，預設挑一個讓長條數量落在 100 根以內的分桶
    const span = S.data.meta.s_ref * S.band * 2;
    S.bucket = isNarrow() ? (opts.find(o => o[0] > 0 && span / o[0] <= 100) || opts[1])[0] : 0;
  }
  sel.innerHTML = opts.map(([v, t]) =>
    `<option value="${v}"${v === S.bucket ? ' selected' : ''}>${t}</option>`).join('');
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
let tipTimer, lastTouch = 0;
const stampTouch = () => { lastTouch = Date.now(); };
addEventListener('touchstart', stampTouch, { passive: true, capture: true });
addEventListener('touchmove', stampTouch, { passive: true, capture: true });
addEventListener('touchend', stampTouch, { passive: true, capture: true });
const justTouched = () => Date.now() - lastTouch < 900;
function showTip(ev, html) {
  tip.innerHTML = html; tip.style.opacity = 1;
  const r = tip.getBoundingClientRect();
  const x = ev.clientX != null ? ev.clientX : (ev.touches && ev.touches[0] ? ev.touches[0].clientX : 0);
  const y = ev.clientY != null ? ev.clientY : (ev.touches && ev.touches[0] ? ev.touches[0].clientY : 0);
  tip.style.left = clamp(x + 14, 8, Math.max(8, innerWidth - r.width - 8)) + 'px';
  tip.style.top = clamp(y - r.height - 14, 8, Math.max(8, innerHeight - r.height - 8)) + 'px';
  // 觸控沒有 mouseleave，自己收掉
  clearTimeout(tipTimer);
  tipShownAt = Date.now();
  // 觸控事件本身、以及觸控後瀏覽器補送的相容滑鼠事件（mouseenter/mousemove），都要排自動關閉
  const byTouch = ev.pointerType === 'touch' || (ev.type || '').startsWith('touch') || justTouched();
  if (byTouch) tipTimer = setTimeout(hideTip, 3500);
}
const hideTip = () => { clearTimeout(tipTimer); tip.style.opacity = 0; };
let tipShownAt = 0;
// 捲動時收掉 tooltip；但點觸的當下常常伴隨一次微小捲動，剛顯示的那 500ms 不理它
addEventListener('scroll', () => { if (Date.now() - tipShownAt > 500) hideTip(); }, { passive: true });

/* --------------------------------------------------------- 長條圖 */
/* 一個委派的感應層，取代「每根長條各自一個透明矩形 + 四個事件」。
   SPX 一張圖有 500 多根，逐根綁會多出 500 個節點與 2,000 個監聽器，
   而且每次重繪（換 β、換慣例、換字級）都要整批重建。 */
function hoverBars(svg, g, geo, bars, locate, tipOf) {
  const hit = el('rect', { x: 0, y: 0, width: geo.iw, height: geo.ih, fill: 'transparent' }, g);
  let cur = -1;
  const off = () => { if (cur >= 0 && bars[cur]) bars[cur].removeAttribute('opacity'); cur = -1; };
  const move = (ev) => {
    const p = ev.touches ? ev.touches[0] : ev;
    if (!p) return;
    const box = svg.getBoundingClientRect();
    if (!box.width) return;
    const vw = (svg.viewBox && svg.viewBox.baseVal.width) || box.width;
    const i = locate((p.clientX - box.left) * (vw / box.width) - geo.left);
    if (i < 0 || i >= bars.length) { off(); hideTip(); return; }
    if (i !== cur) { off(); cur = i; bars[i].setAttribute('opacity', .72); }
    showTip(ev, tipOf(i));
  };
  hit.addEventListener('mouseenter', move);
  hit.addEventListener('mousemove', move);
  hit.addEventListener('touchstart', move, { passive: true });
  hit.addEventListener('touchmove', move, { passive: true });
  hit.addEventListener('mouseleave', () => {
    if (justTouched()) return;                 // 觸控後補送的滑鼠事件不要把 tooltip 關掉
    off(); hideTip();
  });
  return hit;
}

function drawBars(host, rows, valueFn, colorFn, opts) {
  host.innerHTML = '';
  const F = fsScale(), nar = isNarrow();
  const W = Math.max(host.clientWidth || 640, 260);
  const H = Math.round((opts.h || 268) * (nar ? 0.92 : 1) * (1 + (F - 1) * 0.4));
  const m = { t: Math.round(46 * F), r: Math.round(10 * F),   // 上緣留給參考線標籤
              b: Math.round(28 * F), l: Math.round((nar ? 44 : 56) * F) };
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

  const yT = niceTicks(lo, hi, nar ? 4 : 5);
  for (const t of yT) {
    const yy = y(t);
    el('line', { class: 'gl', x1: 0, x2: iw, y1: yy, y2: yy }, g);
    el('text', { class: 'ax', x: -8, y: yy + 3.5, 'text-anchor': 'end' }, g).textContent = t.toFixed(yT.dp);
  }
  el('line', { class: 'zero', x1: 0, x2: iw, y1: y(0), y2: y(0) }, g);
  el('text', { class: 'axname', x: -m.l + 4, y: -m.t + 12 * F }, g).textContent = opts.yLabel;

  const kt = niceTicks(kMin, kMax, nar ? 3 : 6);
  for (const t of kt) {
    if (t < kMin - step || t > kMax + step) continue;
    el('text', { class: 'ax', x: x(t), y: ih + 18 * F, 'text-anchor': 'middle' }, g).textContent = fmtA(t);
  }

  const vs = [], bars = rows.map((r, i) => {
    const v = valueFn(r); vs.push(v);
    return el('path', { d: barPath(x(r.K) - bw / 2, bw, y(0), y(v)),
                        fill: colorFn(r, v), 'shape-rendering': 'geometricPrecision' }, g);
  });

  (opts.refs || []).forEach((rf, i) => {
    if (rf.v == null || rf.v < kMin - step || rf.v > kMax + step) return;
    const xx = x(rf.v);
    el('line', { x1: xx, x2: xx, y1: -m.t + 6, y2: ih, stroke: rf.color, 'stroke-width': 2,
                 'stroke-dasharray': rf.dash, 'pointer-events': 'none' }, g);
    const at = xx > iw - (nar ? 70 : 96) * F;      // 靠右邊界就把標籤翻到左側
    el('text', { class: 'ax', x: xx + (at ? -5 : 5), y: -m.t + (15 + i * 12.5) * F, fill: rf.color,
                 'text-anchor': at ? 'end' : 'start', 'pointer-events': 'none' }, g)
      .textContent = rf.label;
  });

  // 由 x 反推最接近的那一根（rows 依履約價排序，二分搜尋即可；不假設格點連續）
  const locate = (px) => {
    if (px < 0 || px > iw) return -1;
    const k = kMin - step / 2 + (px / iw) * (kMax - kMin + step);
    let a = 0, b2 = rows.length - 1;
    while (a < b2) { const mid = (a + b2) >> 1; if (rows[mid].K < k) a = mid + 1; else b2 = mid; }
    if (a > 0 && Math.abs(rows[a - 1].K - k) < Math.abs(rows[a].K - k)) a--;
    return Math.abs(rows[a].K - k) <= step ? a : -1;   // 離最近的長條超過一格就當沒指到
  };
  hoverBars(svg, g, { iw, ih, left: m.l }, bars, locate, i => opts.tip(rows[i], vs[i]));
}

/* --------------------------------------------------------- 折線圖 */
function drawCurve(host, cv, refs) {
  host.innerHTML = '';
  const F = fsScale(), nar = isNarrow();
  const W = Math.max(host.clientWidth || 640, 260);
  const H = Math.round(268 * (nar ? 0.92 : 1) * (1 + (F - 1) * 0.4));
  const m = { t: Math.round(46 * F), r: Math.round(10 * F),
              b: Math.round(28 * F), l: Math.round((nar ? 44 : 56) * F) };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' }, host);
  const g = el('g', { transform: `translate(${m.l},${m.t})` }, svg);

  const all = cv.gex.concat(cv.gexp).map(v => v / E);
  let lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const xMin = cv.x[0], xMax = cv.x[cv.x.length - 1];
  const x = v => ((v - xMin) / (xMax - xMin)) * iw;
  const y = v => ih - ((v - lo) / (hi - lo)) * ih;

  const yT = niceTicks(lo, hi, nar ? 4 : 5);
  for (const t of yT) {
    const yy = y(t);
    el('line', { class: 'gl', x1: 0, x2: iw, y1: yy, y2: yy }, g);
    el('text', { class: 'ax', x: -8, y: yy + 3.5, 'text-anchor': 'end' }, g).textContent = t.toFixed(yT.dp);
  }
  el('line', { class: 'zero', x1: 0, x2: iw, y1: y(0), y2: y(0) }, g);
  el('text', { class: 'axname', x: -m.l + 4, y: -m.t + 12 * F }, g).textContent = UNIT + ' / 1%';
  for (const t of niceTicks(xMin, xMax, nar ? 3 : 6)) {
    if (t < xMin || t > xMax) continue;
    el('text', { class: 'ax', x: x(t), y: ih + 18 * F, 'text-anchor': 'middle' }, g).textContent = fmtA(t);
  }

  const path = (arr) => arr.map((v, i) => (i ? 'L' : 'M') + x(cv.x[i]).toFixed(1) + ' ' + y(v / E).toFixed(1)).join('');
  el('path', { d: path(cv.gexp), fill: 'none', stroke: 'var(--curve2)', 'stroke-width': 2, 'stroke-linecap': 'round' }, g);
  el('path', { d: path(cv.gex), fill: 'none', stroke: 'var(--curve1)', 'stroke-width': 2, 'stroke-linecap': 'round' }, g);

  refs.forEach((rf, i) => {
    if (rf.v == null || rf.v < xMin || rf.v > xMax) return;
    const xx = x(rf.v), at = xx > iw - (nar ? 70 : 96) * F;
    el('line', { x1: xx, x2: xx, y1: -m.t + 6, y2: ih, stroke: rf.color, 'stroke-width': 2, 'stroke-dasharray': rf.dash }, g);
    el('text', { class: 'ax', x: xx + (at ? -5 : 5), y: -m.t + (15 + i * 12.5) * F, fill: rf.color,
                 'text-anchor': at ? 'end' : 'start' }, g).textContent = rf.label;
  });

  // 十字準星
  const cross = el('line', { y1: -m.t + 6, y2: ih, stroke: '#4b5b6e', 'stroke-width': 1, opacity: 0 }, g);
  const d1 = el('circle', { r: 4.5, fill: 'var(--curve1)', stroke: 'var(--surface)', 'stroke-width': 2, opacity: 0 }, g);
  const d2 = el('circle', { r: 4.5, fill: 'var(--curve2)', stroke: 'var(--surface)', 'stroke-width': 2, opacity: 0 }, g);
  const hit = el('rect', { x: 0, y: 0, width: iw, height: ih, fill: 'transparent' }, g);
  const onMove = (ev) => {
    const bb = svg.getBoundingClientRect();
    const px = (ev.clientX - bb.left) * (W / bb.width) - m.l;
    const sv = xMin + (px / iw) * (xMax - xMin);
    let i = 0, best = Infinity;
    cv.x.forEach((v, j) => { const d = Math.abs(v - sv); if (d < best) { best = d; i = j; } });
    const xx = x(cv.x[i]);
    cross.setAttribute('x1', xx); cross.setAttribute('x2', xx); cross.setAttribute('opacity', 1);
    d1.setAttribute('cx', xx); d1.setAttribute('cy', y(cv.gex[i] / E)); d1.setAttribute('opacity', 1);
    d2.setAttribute('cx', xx); d2.setAttribute('cy', y(cv.gexp[i] / E)); d2.setAttribute('opacity', 1);
    showTip(ev, `<div class="t">標的 ${fmtP(cv.x[i])}（${((cv.x[i] / S.data.meta.s_ref - 1) * 100).toFixed(2)}%）</div>
      <div class="r"><span>GEX</span><span>${fmt(cv.gex[i] / E)}</span></div>
      <div class="r"><span>VEX</span><span>${fmt(cv.vex[i] / E)}</span></div>
      <div class="r"><span>GEX+（β=${S.beta.toFixed(1)}）</span><span>${fmt(cv.gexp[i] / E)}</span></div>`);
  };
  hit.addEventListener('mousemove', onMove);
  hit.addEventListener('touchstart', (e) => onMove(e.touches[0] || e), { passive: true });
  hit.addEventListener('touchmove', (e) => onMove(e.touches[0] || e), { passive: true });
  hit.addEventListener('mouseleave', () => {
    if (justTouched()) return;
    cross.setAttribute('opacity', 0); d1.setAttribute('opacity', 0); d2.setAttribute('opacity', 0); hideTip();
  });
}


/* --------------------------------------------------------- 到期日結構拆解 */
function drawExpiry(host) {
  host.innerHTML = '';
  const sg = SIGNS[S.sign], exps = S.data.expiries;
  const F = fsScale(), nar = isNarrow();
  const W = Math.max(host.clientWidth || 900, 260);
  const H = Math.round(250 * (1 + (F - 1) * 0.4));
  const m = { t: Math.round(18 * F), r: Math.round(10 * F),
              b: Math.round((nar ? 62 : 56) * F), l: Math.round((nar ? 44 : 56) * F) };
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

  const yT = niceTicks(lo, hi, nar ? 4 : 5);
  for (const t of yT) {
    const yy = y(t);
    el('line', { class: 'gl', x1: 0, x2: iw, y1: yy, y2: yy }, g);
    el('text', { class: 'ax', x: -8, y: yy + 3.5, 'text-anchor': 'end' }, g).textContent = t.toFixed(yT.dp);
  }
  el('line', { class: 'zero', x1: 0, x2: iw, y1: y(0), y2: y(0) }, g);
  el('text', { class: 'axname', x: -m.l + 4, y: -6 }, g).textContent = UNIT + ' / 1%';

  const bars = rows.map((r, i) => {
    const cx = cw * (i + 0.5);
    const on = S.exp !== 'ALL' && r.code === S.exp;      // 目前選的那一個到期別
    const p = el('path', { d: barPath(cx - bw / 2, bw, y(0), y(r.gex)),
                           fill: r.gex >= 0 ? 'var(--pos)' : 'var(--neg)' }, g);
    if (S.exp !== 'ALL' && !on) p.setAttribute('opacity', .28);   // 其他的淡掉
    if (on) {                                             // 選到的加一圈框，一眼看得出在哪
      const top = Math.min(y(0), y(r.gex));
      el('rect', { x: cx - bw / 2 - 3, y: top - 3,
                   width: bw + 6, height: Math.abs(y(r.gex) - y(0)) + 6,
                   fill: 'none', stroke: 'var(--ink)', 'stroke-width': 1.5, rx: 3,
                   'pointer-events': 'none' }, g);
      el('text', { class: 'ax', x: Math.min(Math.max(cx, 26), iw - 26),
                   y: Math.max(top - 9, 10), 'text-anchor': 'middle',
                   fill: 'var(--ink)', 'pointer-events': 'none' }, g).textContent = '目前選的';
    }
    el('text', { class: 'ax', x: cx, y: ih + 16 * F, 'text-anchor': 'end',
                 transform: `rotate(-38 ${cx} ${ih + 16 * F})`,
                 fill: on ? 'var(--ink)' : null }, g).textContent = r.ltd;
    return p;
  });

  const one = S.exp !== 'ALL';
  const d = rows.map((r, i) => (i ? 'L' : 'M') + (cw * (i + 0.5)).toFixed(1) + ' ' + y(r.gexp).toFixed(1)).join('');
  el('path', { d, fill: 'none', stroke: 'var(--curve2)', 'stroke-width': 2, 'stroke-linecap': 'round',
               opacity: one ? .3 : null }, g);
  rows.forEach((r, i) => el('circle', {
    cx: cw * (i + 0.5), cy: y(r.gexp), r: 4, fill: 'var(--curve2)',
    stroke: 'var(--surface)', 'stroke-width': 2, 'pointer-events': 'none',
    opacity: one && r.code !== S.exp ? .3 : null }, g));

  hoverBars(svg, g, { iw, ih, left: m.l }, bars,
    px => (px < 0 || px > iw) ? -1 : Math.floor(px / cw),
    i => { const r = rows[i]; return `<div class="t">${r.ltd}　${r.kind}　${r.code}</div>
        <div class="r"><span>GEX</span><span>${fmt(r.gex)} ${UNIT} / 1%</span></div>
        <div class="r"><span>VEX</span><span>${fmt(r.vex)} ${UNIT} / vol 點</span></div>
        <div class="r"><span>GEX+（β=${S.beta.toFixed(1)}）</span><span>${fmt(r.gexp)}</span></div>
        <div class="r"><span>剩餘交易日</span><span>${r.trading_days}</span></div>
        <div class="r"><span>未平倉</span><span>${fmtK(r.oi)} 口</span></div>
        <div class="r"><span>ATM 隱含波動率</span><span>${r.atm_iv == null ? '—' : (r.atm_iv * 100).toFixed(2) + '%'}</span></div>`; });
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

  pills();

  /* 六個 KPI 磚：現貨 / Gamma Flip / GEX+ Flip / 總 GEX / 總 VEX / 總 GEX+ */
  const col = x => x >= 0 ? 'var(--pos)' : 'var(--neg)';
  const iq = k => `<button class="iq" type="button" data-help="${k}" aria-expanded="false" aria-label="說明">i</button>`;
  $('#kpis').innerHTML = `
    <div class="kpi"><div class="k">${spotWord()} S ${iq('k-spot')}</div>
      <div class="v">${fmtP(S0)}</div><div class="s">${meta.s_ref_source}</div></div>
    <div class="kpi"><div class="k">Gamma Flip ${iq('k-flip')}</div>
      <div class="v" style="color:var(--flip)">${fmtP(flip)}</div>
      <div class="s">${flip == null ? '整條曲線都在零軸下方，沒有交叉點' : `距${spotWord()} ${dist(flip)}`}</div></div>
    <div class="kpi"><div class="k">GEX+ Flip ${iq('k-flipp')}</div>
      <div class="v" style="color:var(--flip2)">${fmtP(flipP)}</div>
      <div class="s">${flipP == null ? `同上・β=${S.beta.toFixed(1)}` : `距${spotWord()} ${dist(flipP)}・β=${S.beta.toFixed(1)}`}</div></div>
    <div class="kpi"><div class="k">總 GEX ${iq('k-gex')}</div>
      <div class="v" style="color:${col(totG)}">${fmtBig(totG / E)}<small>${shortUnit()}</small></div>
      <div class="s">每 1% 變動情境</div></div>
    <div class="kpi"><div class="k">總 VEX ${iq('k-vex')}</div>
      <div class="v" style="color:${col(totV)}">${fmtBig(totV / E)}<small>${shortUnit()}</small></div>
      <div class="s">每 1 vol point 情境</div></div>
    <div class="kpi"><div class="k">總 GEX+ ${iq('k-gexp')}</div>
      <div class="v" style="color:${col(totGp)}">${fmtBig(totGp / E)}<small>${shortUnit()}</small></div>
      <div class="s">β = ${S.beta.toFixed(1)}</div></div>`;

  $('#summary').innerHTML = `
    <div class="rowlist">
      <div><span class="lbl">正 GEX 集中</span>${up.map(r => `<span class="chip p">${fmtP(r.K)} ${fmt(gexOf(r, sg) / E)}</span>`).join('') || '<span style="color:var(--ink3)">無</span>'}</div>
      <div><span class="lbl">負 GEX 集中</span>${dn.map(r => `<span class="chip n">${fmtP(r.K)} ${fmt(gexOf(r, sg) / E)}</span>`).join('') || '<span style="color:var(--ink3)">無</span>'}</div>
      <div><span class="lbl">負 VEX 集中</span>${vn.map(r => `<span class="chip n">${fmtP(r.K)} ${fmt(vexOf(r, sg) / E)}</span>`).join('') || '<span style="color:var(--ink3)">無</span>'}</div>
      <div><span class="lbl">未平倉牆</span>
        <span class="chip">Call ${cw ? fmtP(cw.K) : '—'}・${cw ? fmtK(cw.oc) : 0} 口</span>
        <span class="chip">Put ${pw ? fmtP(pw.K) : '—'}・${pw ? fmtK(pw.op) : 0} 口</span>
        <span style="color:var(--ink3)">P/C = ${(v.oi_p / Math.max(v.oi_c, 1)).toFixed(2)}</span></div>
      <div><span class="lbl">總 vega 曝險</span>
        <span class="chip">${fmt(totVega / E)} ${UNIT} / vol 點</span>
        <span style="color:var(--ink3)">部位損益，不是避險流量</span></div>
      <div><span class="lbl">未平倉合計</span>
        <span class="chip">${fmtK(meta.oi_total)} 口</span>
        <span style="color:var(--ink3)">逐履約價明細涵蓋 ${(meta.oi_coverage * 100).toFixed(1)}%</span></div>
    </div>
    <div class="foot">${gTone}。<br>${vTone}。</div>`;

  /* 兩段長說明搬進 ⓘ，畫面上不再佔位置 */
  CARD_HELP['c-notes'] = `${gTone}。<br><br>${vTone}。<br><br>`
    + `資料產出時只保留${spotWord()} ±${(tr.band_pct * 100).toFixed(0)}% 內的逐履約價明細`
    + `（<b>跟「顯示區間」是兩回事</b>，改顯示區間不會改變這一行）；`
    + `再外面還有 ${tr.n_strikes_dropped} 個履約價、${fmtK(tr.oi_outside)} 口未平倉，`
    + `佔總 GEX ${(Math.abs(gexOf(tr, sg)) / Math.max(Math.abs(totG), 1) * 100).toFixed(2)}%，`
    + `<b>已經計入上方所有總量</b>。`;
}

/* --------------------------------------------------------- 表格 */
/* 兩張表都收在 <details> 裡，預設是關的。SPX 有 500 多列 × 9 欄 ＝ 近 5,000 個節點，
   佔整頁節點的六成，而且每次換 β、換慣例、換字級都要重建一次——沒人在看的時候不必建。 */
let tblDirty = true, expTblDirty = true;

function drawTable(rows) {
  if (!$('#dTable').open) {                 // 收起來時連舊內容都清掉，不然上一個標的的列會一直佔著 DOM
    tblDirty = true;
    $('#tbl').querySelector('tbody').innerHTML = '';
    return;
  }
  tblDirty = false;
  const sg = SIGNS[S.sign];
  $('#tbl').querySelector('thead').innerHTML =
    `<tr><th>履約價</th><th>GEX（${UNIT}/1%）</th><th>VEX（${UNIT}/vol點）</th><th>vega 曝險</th>` +
    '<th>Call OI</th><th>Put OI</th><th>ΔCall OI</th><th>ΔPut OI</th><th>隱含波動率</th></tr>';
  $('#tbl').querySelector('tbody').innerHTML = rows.map(r => `<tr>
    <td>${fmtP(r.K)}</td>
    <td style="color:${gexOf(r, sg) >= 0 ? 'var(--pos)' : 'var(--neg)'}">${fmt(gexOf(r, sg) / E)}</td>
    <td style="color:${vexOf(r, sg) >= 0 ? 'var(--pos)' : 'var(--neg)'}">${fmt(vexOf(r, sg) / E, 3)}</td>
    <td style="color:var(--ink2)">${fmt(vegaOf(r, sg) / E, 3)}</td>
    <td>${fmtK(r.oc)}</td><td>${fmtK(r.op)}</td>
    <td style="color:var(--ink2)">${fmtD(r.dc)}</td>
    <td style="color:var(--ink2)">${fmtD(r.dp)}</td>
    <td>${r.iv == null ? '—' : (r.iv * 100).toFixed(2) + '%'}</td></tr>`).join('');
}

function drawExpTable() {
  if (!$('#dExp').open) {
    expTblDirty = true;
    $('#tblExp').querySelector('tbody').innerHTML = '';
    return;
  }
  expTblDirty = false;
  $('#tblExp').querySelector('thead').innerHTML =
    '<tr><th>到期別</th><th>類型</th><th>最後交易日</th><th>剩餘交易日</th><th>遠期價</th>' +
    '<th>ATM IV</th><th>偏斜 dσ/dlnK</th><th>未平倉</th><th>GEX</th><th>VEX</th></tr>';
  const sg = SIGNS[S.sign];
  $('#tblExp').querySelector('tbody').innerHTML = S.data.expiries.map(e => `<tr>
    <td>${e.code}</td><td>${e.kind}</td><td>${e.ltd}</td><td>${e.trading_days}</td>
    <td>${fmtP(e.F)}</td><td>${e.atm_iv == null ? '—' : (e.atm_iv * 100).toFixed(2) + '%'}</td>
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
    { v: S0, color: 'var(--spot)', dash: '6 4', label: spotWord() + ' ' + fmtP(S0) },
    { v: flip, color: 'var(--flip)', dash: '2 4', label: 'Gamma Flip ' + (flip == null ? '' : fmtP(flip)) },
    { v: flipP, color: 'var(--flip2)', dash: '2 4', label: 'GEX+ Flip ' + (flipP == null ? '' : fmtP(flipP)) },
  ];

  // 圖例：色塊與文字包在同一個 span，換行時不會被拆開
  const lgi = (color, text, dash) =>
    `<span class="it"><i class="${dash ? 'd' : ''}" style="${dash ? 'border-top-color' : 'background'}:${color}"></i>${text}</span>`;
  const lg = (host, items) => { $(host).innerHTML = items.map(a => lgi(a[0], a[1], a[2])).join(''); };

  lg('#lgGex', [['var(--pos)', '正 GEX（穩定 / 壓回）'], ['var(--neg)', '負 GEX（放大 / 追價）'],
                ['var(--spot)', spotWord(), 1],
                ...(flip == null ? [] : [['var(--flip)', 'Gamma Flip', 1]])]);
  lg('#lgVex', [['var(--neg)', '負 VEX（波動上升 → 造市商賣出 → 放大）'], ['var(--pos)', '正 VEX'],
                ['var(--spot)', spotWord(), 1]]);
  lg('#lgCurve', [['var(--curve1)', 'GEX'], ['var(--curve2)', `GEX+（β=${S.beta.toFixed(1)}）`],
                  ['var(--spot)', spotWord(), 1]]);
  lg('#lgExp', [['var(--pos)', 'GEX（長條）'], ['var(--curve2)', `GEX+（折線，β=${S.beta.toFixed(1)}）`]]);

  drawBars($('#chGex'), rows, r => gexOf(r, sg) / E,
    (r, v) => v >= 0 ? 'var(--pos)' : 'var(--neg)',
    {
      yLabel: UNIT + ' / 1%', refs, step,
      tip: (r, v) => `<div class="t">履約價 ${fmtP(r.K)}</div>
        <div class="r"><span>GEX</span><span>${fmt(v)} ${UNIT} / 1%</span></div>
        <div class="r"><span>VEX</span><span>${fmt(vexOf(r, sg) / E, 3)} ${UNIT} / vol 點</span></div>
        <div class="r"><span>Call OI</span><span>${fmtK(r.oc)}（${fmtD(r.dc)}）</span></div>
        <div class="r"><span>Put OI</span><span>${fmtK(r.op)}（${fmtD(r.dp)}）</span></div>
        <div class="r"><span>隱含波動率</span><span>${r.iv == null ? '—' : (r.iv * 100).toFixed(2) + '%'}</span></div>`,
    });

  drawBars($('#chVex'), rows, r => vexOf(r, sg) / E,
    (r, v) => v >= 0 ? 'var(--pos)' : 'var(--neg)',
    {
      yLabel: UNIT + ' / vol 點', refs: [refs[0], refs[1]], step,
      tip: (r, v) => `<div class="t">履約價 ${fmtP(r.K)}</div>
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
/* β 拉桿一路拖會連發數十個 input 事件，每一發都整頁重畫。
   併到同一個動畫影格，畫面只會跟著更新一次。 */
let rafQueued = false;
function renderSoon() {
  if (rafQueued) return;
  rafQueued = true;
  requestAnimationFrame(() => { rafQueued = false; render(); });
}

function segment(host, key, cast, after) {
  if (!host) return;
  host.addEventListener('click', (ev) => {
    const b = ev.target.closest('button'); if (!b) return;
    [...host.querySelectorAll('button')].forEach(x => x.setAttribute('aria-pressed', x === b));
    S[key] = cast(b.dataset.v); (after || render)();
  });
}

function methodology() {
  const m = S.data.meta, sym = m.symbol;
  const tw = sym === 'TXO', cme = sym === 'ES', cboe = !tw && !cme;
  const cur = m.currency || 'NT$';
  const exch = tw ? '臺灣期貨交易所' : cme ? 'CME' : 'CBOE';
  const oiPub = tw ? '期交所' : cme ? 'CME' : 'OCC';
  const cal = tw ? 'calendar_tw.txt' : 'calendar_us.txt';
  const und = cme ? '主力月 ES 期貨結算價'
            : tw ? '證交所的發行量加權股價指數收盤'
                 : 'CBOE 的標的前一交易日收盤價';

  const sigWord = tw ? '期交所公布的是全市場逐履約價的未平倉量'
                     : `${oiPub} 公布的是全市場逐履約價的未平倉量`;

  const secPrice = tw
    ? `只取<b>一般交易時段</b>與<b>結算價</b>（大量履約價當天沒有成交，收盤價是空的）。`
    : cme
    ? `價格取 CME <b>每日結算表</b>的結算價。未平倉量<b>不是</b>取結算表上那一欄——
       那一欄是<b>前一交易日</b>的；當日收盤的未平倉在<b>成交量表</b>的 <code>atClose</code>，
       本站把兩張表按（買/賣權、履約價）合併，並用「前一日 ＋ 當日變動 － 當日收盤 = 0」對帳。
       日選的兩者差距可以到四成以上，取錯整張圖會偏掉。`
    : `價格取每個合約的<b>前一交易日收盤價</b>（<code>prev_day_close</code>），標的價同樣取前一交易日收盤。
       這是刻意的：CBOE 的即時報價是活的，但未平倉量要等 ${oiPub} <b>隔天美東上午</b>才發布，
       <b>沒有任何一個時點能同時拿到對齊的價格與未平倉</b>。用即時價配昨天的未平倉會得到兩個時點混在一起的圖，
       Flip 位置會錯。本站寧可整份晚一天，也不混。`;

  const secT = tw
    ? `臺指選擇權的最終結算價在「最後交易日之<b>次一營業日</b>」開盤後 15 分鐘決定，所以把結算日也算進來，`
    : `到期時間從資料日算到<b>結算日</b>，`;

  const todo = tw
    ? '・只做 TXO，沒有納入電子、金融、小型台指選擇權。'
    : cme
    ? '・只做 ES，沒有納入 NQ、RTY、CL 等其他 CME 商品。'
    : '・沒有納入個股選擇權，只做指數與大型 ETF。';

  $('#meth').innerHTML = `
  <div class="warn"><b>先講最重要的限制。</b>「造市商曝險」這個名字是慣例，不是觀測。
  ${sigWord}，<b>沒有</b>任何欄位告訴你哪些部位屬於造市商、方向是多還是空。
  這張圖是在「買權由造市商作多、賣權由造市商放空」這個<b>假設</b>下算出來的，
  跟真實的造市商帳本可能相差很遠。把它當成<b>全市場 gamma / vanna 結構的描述</b>來用是合理的；
  把它當成訊號來下單之前，請自己先做過檢定。</div>

  <h3>1. 三個定義式</h3>
  <code>GEX(K) = M × S² × 0.01 × Σ sign × gamma × OI</code>　→　標的每移動 1%，造市商 delta 名目金額的變動量<br>
  <code>VEX(K) = −M × S ÷ 100 × Σ sign × vanna × OI</code>　→　隱含波動率每上升 1 個百分點，造市商 delta 名目金額的變動量<br>
  <code>GEX+ = GEX + β × VEX</code>　→　β 的意思是「標的每移動 1%，隱含波動率反向變動 β 個波動點」<br>
  <code>M = ${cur}${m.multiplier} / 點</code>（${m.label} 契約乘數）。sign 由上方「造市商假設」決定，三個式子共用。

  <h3>2. VEX 用 vanna 不用 vega</h3>
  這張圖描述的是造市商<b>被迫調整的避險流量</b>。vega 講的是部位損益（波動率動了賺賠多少），
  vanna 講的才是流量（波動率動了必須去市場上買賣多少標的）——跟 gamma 是同一類的東西。<br>
  還有一個現實理由：同履約價的買賣權 vega 完全相等（put-call parity 的直接結果），
  所以 <code>Σ sign × vega × OI</code> 在買權多賣權空的慣例下會互相抵消、恆在零附近，沒有資訊。
  vanna 不會，因為它在價平兩側變號，跟 <code>Call OI − Put OI</code> 的變號剛好互相配合，
  於是兩側同號、價平附近趨近於零——這就是 VEX 圖中間那個凹陷的來源。
  vega 曝險仍然有意義（造市商是波動率的多方還是空方），放在摘要與資料表裡當附加欄位。

  <h3>3. 參考標的價與遠期</h3>
  摘要卡上的 <b>${spotWord()} S</b> 取的是${und}，所以 Flip 講出來直接是你看盤軟體上的價位。<br>
  但<b>選擇權定價不用它</b>：每個到期別由自己的${m.price_note} put-call parity 反解遠期
  <code>F = K + (C − P)</code>（價平 ±3% 取中位數）。${cme
    ? '期貨選擇權的標的本來就是期貨，反解出來的 F 會很接近該月期貨，這一步主要是吸收各到期別之間的差異。'
    : '用現貨當標的會讓 parity 破裂，同一履約價的買權與賣權會反解出不同的隱含波動率。'}
  情境曲線平移時，各到期別遠期依 <code>F_e × (S / S₀)</code> 同比例移動，保持基差比例。

  <h3>4. 隱含波動率只取價外那一側</h3>
  <code>K &lt; F</code> 用賣權、<code>K ≥ F</code> 用買權反解，再讓同履約價的買賣權共用這個 IV。
  深度價內的${m.price_note}時間價值常常只有一兩點，IV 對它極度敏感，拿來反解會出現假的高波動率。
  反解用二分法保證收斂加牛頓法收尾，不用純割線法（會在深度價內停滯）。

  <h3>5. 到期時間 T</h3>
  ${secT}再用 252 個交易日折成年（休市日表在 <code>${cal}</code>）。當日到期的契約直接排除。<br>
  <b>T 的慣例對 GEX 幾乎沒有影響</b>：IV 是從價格反解的，<code>σ√T</code> 被市價釘住，
  而 <code>gamma ≈ φ(d₁)/(F·σ√T)</code>，兩邊的 T 互相抵消。VEX 與 vega 曝險則會受影響。
  ${sym === 'SPX' ? '<br>SPX 與 SPXW 是兩個不同的根（AM / PM 結算），本站拆成獨立的到期別，不合併。' : ''}

  <h3>6. 資料與更新</h3>
  來源：${m.source}。${secPrice}<br>
  本日採計 ${fmtK(m.n_legs)} 份契約、${m.n_expiries} 個到期日、${fmtK(m.oi_total)} 口未平倉，
  OI 覆蓋率 ${(m.oi_coverage * 100).toFixed(1)}%（反解不出隱含波動率的會被剔除）。<br>
  盤中沒有即時未平倉量，${oiPub} 的 OI 是盤後才公布，所以這張圖描述的是<b>收盤</b>的結構，
  不是盤中即時曝險。${m.tz_note}。資料產生時間 ${m.generated_at}。<br>
  逐履約價明細只保留${spotWord()} ±${(view().truncated.band_pct * 100).toFixed(0)}% 內的部分，
  再外面的合併成一筆，但<b>所有總量都是用全部履約價算的</b>。

  <h3>7. 已知還沒做的事</h3>
  ・沒有做流動性加權，冷門履約價的${m.price_note}是交易所用模型算的，權重跟熱門履約價一樣。<br>
  ・情境曲線假設隱含波動率的水準不隨標的變動（β 只補了一階的線性回饋）。<br>
  ${todo}
  `;
}

function mountExpiries() {
  // 所有標的一律用下拉：到期別多寡不影響版面，頂欄永遠是同一條、同一個位置。
  const seg = $('#segExp'), sel = $('#selExp'), ex = S.data.expiries;
  if (!S.data.views[S.exp]) S.exp = 'ALL';
  seg.style.display = 'none'; seg.innerHTML = '';     // 舊標的的按鈕不要留在 DOM 裡
  sel.style.display = '';
  sel.innerHTML = `<option value="ALL">合併（全部 ${ex.length} 個）</option>` +
    ex.map(e => `<option value="${e.code}"${e.code === S.exp ? ' selected' : ''}>${e.ltd}　${e.kind}　${fmtK(e.oi)} 口</option>`).join('');
  sel.value = S.exp;
}


/* --------------------------------------------------------- 說明用圖解 */
const figSvg = (vb, inner, extra) =>
  `<svg class="figsvg${extra ? ' ' + extra : ''}" viewBox="${vb}" preserveAspectRatio="xMidYMid meet" role="img" aria-hidden="true">${inner}</svg>`;
const fT = (x, y, s, txt, o) => { o = o || {};
  return `<text x="${x}" y="${y}" font-size="${(+s).toFixed(1)}" fill="${o.fill || 'var(--ink3)'}"` +
         `${o.anchor ? ` text-anchor="${o.anchor}"` : ''}${o.w ? ' font-weight="600"' : ''}>${txt}</text>`; };
const fL = (x1, y1, x2, y2, o) => { o = o || {};
  return `<line x1="${(+x1).toFixed(1)}" y1="${(+y1).toFixed(1)}" x2="${(+x2).toFixed(1)}" y2="${(+y2).toFixed(1)}" ` +
         `stroke="${o.s || 'var(--grid)'}" stroke-width="${o.w || 1}"${o.dash ? ` stroke-dasharray="${o.dash}"` : ''}` +
         `${o.cap ? ' stroke-linecap="round"' : ''}/>`; };
const fP = (d, o) => { o = o || {};
  return `<path d="${d}" fill="${o.fill || 'none'}" stroke="${o.s || 'none'}" stroke-width="${o.w || 1.8}" ` +
         `stroke-linejoin="round" stroke-linecap="round"${o.dash ? ` stroke-dasharray="${o.dash}"` : ''}/>`; };
const fD = (x, y, r, c) => `<circle cx="${(+x).toFixed(1)}" cy="${(+y).toFixed(1)}" r="${r}" fill="${c}"/>`;
const fR = (x, y, w, h, c, rx) =>
  `<rect x="${(+x).toFixed(1)}" y="${(+y).toFixed(1)}" width="${(+w).toFixed(1)}" height="${Math.max(0, h).toFixed(1)}" fill="${c}"${rx ? ` rx="${rx}"` : ''}/>`;
const fPoly = (pts, c) => `<polyline points="${pts}" fill="none" stroke="${c}" stroke-width="1.1"/>`;

/* 步驟 1：三個總量看的是斜率，不是絕對值 */
function fig1(T) {
  const rows = [
    { lab: '總 GEX',  v: [18, 17, 14, 13, 11],           lo: 0,  hi: 21, c: 'var(--pos)',    n: '+18 → +11' },
    { lab: '總 VEX',  v: [-4.0, -4.6, -5.3, -6.0, -6.6], lo: -8, hi: 0,  c: 'var(--neg)',    n: '−4.0 → −6.6' },
    { lab: '總 GEX+', v: [14, 12, 9, 6, 4.4],            lo: 0,  hi: 17, c: 'var(--curve2)', n: '+14 → +4.4' },
  ];
  const x0 = 92, x1 = 274, H = 164;
  let s = '';
  rows.forEach((r, i) => {
    const cy = 32 + i * 46, h = 14;
    const y = v => cy + h - ((v - r.lo) / (r.hi - r.lo)) * (2 * h);
    const px = j => x0 + (x1 - x0) * j / (r.v.length - 1);
    s += fR(x0 - 20, cy - h - 4, (x1 + 4) - (x0 - 20), 2 * h + 8, 'rgba(255,255,255,.04)', 4);
    s += fT(2, cy + h * 0.3, T, r.lab, { fill: 'var(--ink2)' });
    s += fL(x0 - 2, y(0), x1 + 3, y(0), { s: '#4a5a6e', dash: '3 3' });
    s += fT(x0 - 6, y(0) + T * 0.34, T * 0.85, '0', { anchor: 'end' });
    s += fP(r.v.map((v, j) => (j ? 'L' : 'M') + px(j).toFixed(1) + ' ' + y(v).toFixed(1)).join(''), { s: r.c, w: 2, cap: 1 });
    r.v.forEach((v, j) => { s += fD(px(j), y(v), j === r.v.length - 1 ? 3.2 : 1.9, r.c); });
    s += fT(x1 + 11, y(r.v[4]) + T * 0.34, T, r.n, { fill: r.c, w: 1 });
  });
  s += fT(x0, H - 7, T * 0.88, '5 天前', { anchor: 'middle' });
  s += fT(x1, H - 7, T * 0.88, '今天', { anchor: 'middle' });
  return figSvg('0 0 420 ' + H, s);
}

/* 步驟 2：同一個今天，兩種來歷 */
function fig2p(T, spot, flip) {
  const W = 214, H = 134, x0 = 32, x1 = 146, yT = 16, yB = 100;
  const lo = 43800, hi = 46600;
  const y = v => yB - ((v - lo) / (hi - lo)) * (yB - yT);
  const px = j => x0 + (x1 - x0) * j / 4;
  let s = '';
  [44000, 45000, 46000].forEach(t => {
    s += fL(x0 - 3, y(t), x1 + 3, y(t));
    s += fT(x0 - 6, y(t) + T * 0.34, T * 0.85, (t / 1000).toFixed(0) + 'k', { anchor: 'end' });
  });
  const mk = (arr, col, dash) => {
    s += fP(arr.map((v, j) => (j ? 'L' : 'M') + px(j).toFixed(1) + ' ' + y(v).toFixed(1)).join(''), { s: col, w: 2, dash, cap: 1 });
    s += fD(px(4), y(arr[4]), 3.2, col);
  };
  mk(flip, 'var(--flip)', '3.5 3');
  mk(spot, 'var(--spot)');
  const gx = x1 + 13, ys = y(spot[4]), yf = y(flip[4]);
  s += fL(gx, ys, gx, yf, { s: 'var(--ink2)', w: 1.2 });
  s += fL(gx - 3, ys, gx + 3, ys, { s: 'var(--ink2)', w: 1.2 });
  s += fL(gx - 3, yf, gx + 3, yf, { s: 'var(--ink2)', w: 1.2 });
  const gap = spot[4] - flip[4];
  s += fT(gx + 6, (ys + yf) / 2 - 1, T, gap.toLocaleString('en-US'), { fill: 'var(--ink)', w: 1 });
  s += fT(gx + 6, (ys + yf) / 2 + T + 1, T * 0.88, '−' + (gap / spot[4] * 100).toFixed(1) + '%', {});
  s += fT(x0, H - 6, T * 0.88, '5 天前', { anchor: 'middle' });
  s += fT(x1, H - 6, T * 0.88, '今天', { anchor: 'middle' });
  return figSvg('0 0 ' + W + ' ' + H, s, 'half');
}

/* 步驟 3：厚度是誰撐的、什麼時候脫掉 */
function fig3(T) {
  const W = 420, H = 176, x0 = 30, x1 = 402, yB = 124, yT = 46;
  const ex = [
    { d: '08-26', g: 6.2, oi: 2100 }, { d: '08-28', g: 0.4, oi: 900 },
    { d: '09-02', g: 0.5, oi: 1200 }, { d: '09-04', g: 0.3, oi: 800 },
    { d: '09-16', g: 1.1, oi: 3400 }, { d: '10-21', g: 0.2, oi: 700 },
  ];
  const n = ex.length, cw = (x1 - x0) / n, bw = cw * 0.4;
  const yg = v => yB - (v / 7) * (yB - yT);
  const yo = v => yB - 10 - (v / 4200) * (yB - yT - 26);
  const cx = i => x0 + cw * (i + 0.5);
  let s = fL(x0, yB, x1, yB, { s: '#3a4a5e', w: 1.2 });
  ex.forEach((e, i) => {
    s += fR(cx(i) - bw / 2, yg(e.g), bw, yB - yg(e.g), 'var(--pos)', 2);
    s += fT(cx(i), yB + T + 4, T * 0.88, e.d, { anchor: 'middle' });
  });
  s += fP(ex.map((e, i) => (i ? 'L' : 'M') + cx(i).toFixed(1) + ' ' + yo(e.oi).toFixed(1)).join(''), { s: 'var(--ink3)', w: 1.2, dash: '4 3' });
  ex.forEach((e, i) => {
    s += `<circle cx="${cx(i).toFixed(1)}" cy="${yo(e.oi).toFixed(1)}" r="3.2" fill="var(--bg)" stroke="var(--ink2)" stroke-width="1.4"/>`;
  });
  s += fL(cx(0) + 6, yg(6.2) + 4, cx(0) + 22, 26, { s: 'var(--ink3)' });
  s += fT(cx(0) + 25, 26 + T * 0.34, T, '整張圖 68% 的厚度在這一格', { fill: 'var(--ink2)' });
  s += fL(cx(4) - 5, yo(3400) - 3, cx(4) - 20, 62, { s: 'var(--ink3)' });
  s += fT(cx(4) - 23, 62 + T * 0.34, T, '未平倉最多的卻是這一格', { anchor: 'end', fill: 'var(--ink2)' });
  return figSvg('0 0 ' + W + ' ' + H, s);
}

/* 步驟 4：會跟著價格跑的假牆 vs 釘住的真牆 */
function fig4(T) {
  const W = 420, H = 148, x0 = 26, x1 = 402, yB = 112, yT = 46;
  const g  = [.1, .15, .3, .5, .9, 1.4, 3.0, 1.2, 3.0, 1.1, .7, .4, .25, .15];
  const oi = [120, 180, 300, 420, 600, 700, 300, 650, 2100, 540, 480, 300, 260, 180];
  const n = g.length, cw = (x1 - x0) / n, bw = cw * 0.5, spotI = 6, wallI = 8;
  const cx = i => x0 + cw * (i + 0.5);
  const y = v => yB - (v / 3.8) * (yB - yT);
  let s = fL(x0, yB, x1, yB, { s: '#3a4a5e', w: 1.2 });
  g.forEach((v, i) => {
    s += fR(cx(i) - bw / 2, y(v), bw, yB - y(v),
            (i === spotI || i === wallI) ? 'var(--pos)' : 'var(--grid)', 2);
  });
  s += fL(cx(spotI), yT - 20, cx(spotI), yB + 6, { s: 'var(--spot)', w: 1.6, dash: '4 4' });
  s += fT(cx(spotI) + 5, yT - 20 + T * 0.9, T * 0.9, '現貨', { fill: 'var(--spot)' });
  s += fL(cx(spotI) - 5, y(3.0) - 3, cx(spotI) - 24, 22, { s: 'var(--ink3)' });
  s += fT(cx(spotI) - 27, 18, T, '未平倉只有 300 口', { anchor: 'end', fill: 'var(--ink2)' });
  s += fT(cx(spotI) - 27, 18 + T * 1.4, T * 0.92, '價平 gamma 最大', { anchor: 'end' });
  s += fL(cx(wallI) + 5, y(3.0) - 3, cx(wallI) + 22, 46, { s: 'var(--ink3)' });
  s += fT(cx(wallI) + 25, 42, T, '未平倉 2,100 口', { fill: 'var(--ink2)' });
  s += fT(cx(wallI) + 25, 42 + T * 1.4, T * 0.92, '釘在這個價位不動', {});
  s += fT(x0, H - 7, T * 0.88, '← 低履約價', {});
  s += fT(x1, H - 7, T * 0.88, '高履約價 →', { anchor: 'end' });
  return figSvg('0 0 ' + W + ' ' + H, s);
}

/* 步驟 5：同一批部位的兩張臉 */
function fig5(T) {
  const W = 420, H = 156, x0 = 88, x1 = 402, mid = 92, hUp = 44, hDn = 38;
  const gx  = [.2, .4, .7, 1.1, 1.6, 2.2, 1.2, 2.8, 3.3, 2.9, 1.0, .6, .3];
  const vx  = [.04, .07, .09, .11, .14, .17, .09, .25, .30, .27, .08, .05, .03];
  const hot = [7, 8, 9];
  const n = gx.length, cw = (x1 - x0) / n, bw = cw * 0.52;
  const cx = i => x0 + cw * (i + 0.5);
  let s = '';
  hot.forEach(i => { s += fR(cx(i) - cw * 0.44, mid - hUp - 12, cw * 0.88, hUp + hDn + 24, 'rgba(255,255,255,.055)', 3); });
  gx.forEach((v, i) => { s += fR(cx(i) - bw / 2, mid - 6 - (v / 3.5) * hUp, bw, (v / 3.5) * hUp, 'var(--pos)', 2); });
  vx.forEach((v, i) => { s += fR(cx(i) - bw / 2, mid + 6, bw, (v / .32) * hDn, 'var(--neg)', 2); });
  s += fT(x0 - 8, mid - 6 - hUp * 0.45, T, '正 GEX 集中', { anchor: 'end', fill: 'var(--pos)' });
  s += fT(x0 - 8, mid + 6 + hDn * 0.55, T, '負 VEX 集中', { anchor: 'end', fill: 'var(--neg)' });
  s += fL(cx(hot[0]) - cw * 0.44, mid - hUp - 16, cx(hot[2]) + cw * 0.44, mid - hUp - 16, { s: 'var(--ink3)' });
  s += fT((cx(hot[0]) + cx(hot[2])) / 2, mid - hUp - 22, T, '同一批履約價', { anchor: 'middle', fill: 'var(--ink2)' });
  s += fT(x0 - 10, H - 12, T * 0.88, '← 低履約價', { anchor: 'end' });
  s += fT(x1, H - 12, T * 0.88, '高履約價 →', { anchor: 'end' });
  return figSvg('0 0 ' + W + ' ' + H, s);
}

function figBlock(svg, cap, legend) {
  return `<div class="fig">${legend ? `<div class="figlg">${legend}</div>` : ''}${svg}` +
         `${cap ? `<div class="figcap">${cap}</div>` : ''}</div>`;
}

function howto() {
  const m = S.data.meta, us = m.symbol !== 'TXO';
  const T = isNarrow() ? 12.6 : 11;          // 圖解內文字大小（user unit）
  $('#howto').innerHTML = `
  <p style="margin:0 0 12px">這張圖畫的是<b>地形</b>，不是天氣。它告訴你造市商在哪些價位會被迫買、
  在哪些價位會被迫賣，不告訴你價格會往哪邊走。下面五步是<b>使用順序</b>，照著跑一遍再看盤。</p>
  <p style="margin:0 0 14px;padding:9px 12px;background:var(--surface2);border:1px solid #2b4763;border-radius:9px">
  <b>看不懂這一段？</b>先看 <a href="easy.html" style="color:#a9cdf0">五分鐘看懂這張圖</a>——
  那一頁用生活上的例子（護欄與結冰、結冰線、水泥牆與影子）把整套講完，不用先懂術語。<br>
  想查<b>單一格</b>的意思——某個數字是什麼、那張圖怎麼讀、某個控制項會改變什麼——
  看 <a href="guide.html" style="color:#a9cdf0">每個數字怎麼用</a>，那是逐項的字典。</p>

  <h3>步驟 1　先看三個總量的「方向」，不是絕對值</h3>
  總 GEX 為正，造市商要逆勢調整，行情傾向被磨在區間裡；為負則要順勢調整，一有變動就被放大。<br>
  總 VEX 幾乎永遠是負的（結構使然），所以要看的是<b>有多負</b>，那是波動率上升時會被倒出來的量。<br>
  總 GEX+ 是兩者合成，最接近真實環境。<br>
  <b>單日數字沒有意義，要跟前幾天比。</b> 用左上角的「資料日期」切回前幾天，看這三個數字往哪個方向動。
  ${figBlock(fig1(T),
    '這五天裡，三個數字沒有一個跨過零：總 GEX 還是正的、總 GEX+ 也還是正的。' +
    '但三條線一起往同一個方向走——正的那兩個一路變薄、負的那個一路變厚。' +
    '<b>只看今天，你會說「結構還行」；看斜率，你會說「這面牆正在被拆」。</b>' +
    '示意數字，非實際盤面。')}

  <h3>步驟 2　分清楚「門檻有沒有動」與「距離有沒有變遠」</h3>
  <div class="warn">這是整套讀法最容易搞錯、也最值錢的一件事。</div>
  「距現貨 %」變大只有兩種來歷，它們的賠率完全不同：<br>
  兩條 Flip 幾乎沒動、但現貨往上跑了一段 → 安全距離是<b>價格自己墊出來的</b>，不是結構撐出來的。
  哪天原路走回去，門檻還在原地等，一點都沒少。<br>
  現貨沒怎麼動、Flip 自己往下退 → 才是<b>結構真的多讓出了一層</b>，那是有人在下面補了正 gamma。<br>
  兩件事在<b>今天這一格</b>上長得一模一樣，都是「離翻負還很遠」。要分辨只能把兩條線分開看。
  ${figBlock(
    `<div class="figrow">
       <div class="figcol"><div class="figt">A　門檻沒動，是價格跑掉了</div>${fig2p(T, [44300,44700,45200,45700,46000], [44300,44320,44290,44310,44300])}</div>
       <div class="figcol"><div class="figt">B　現貨沒動，是門檻退開了</div>${fig2p(T, [45900,46100,45950,46050,46000], [45900,45500,45000,44600,44300])}</div>
     </div>`,
    '兩張圖的<b>今天</b>完全相同：現貨 46,000、Gamma Flip 44,300、距現貨 −3.7%。' +
    '摘要卡上看到的就只有這一格，兩者無從分辨。<br>' +
    'A 的 1,700 點全部是現貨自己跑出來的，門檻五天沒挪過一步——跌回 44,300，處境和五天前一模一樣。' +
    'B 的 1,700 點是門檻自己退下去讓出來的，同樣跌到 44,300 才翻負，但那是真的多出來的空間。<br>' +
    '<b>做法：用「資料日期」往回切幾天，分別記下現貨和兩條 Flip，看是誰在動。</b>',
    '<span style="color:var(--spot)">━</span> 現貨　<span style="color:var(--flip)">┅</span> Gamma Flip')}

  <h3>步驟 3　看到期日結構拆解，找出「護甲什麼時候脫掉」</h3>
  翻到最下面那張「到期日結構拆解」。要問的問題只有一個：<b>現在這些厚度是誰撐的？</b><br>
  如果單一到期日的 GEX 比全部到期日加總還大，代表整張圖看起來的穩定幾乎都是那一格給的——
  那天結算完，扶著的手就鬆了。<br>
  還有一個容易誤判的地方：<b>未平倉最多的到期日，不一定是 GEX 最大的到期日。</b>
  越接近到期，每一口的 gamma 越大，所以近月常常用比較少的口數撐出更大的曝險。
  結算之後接手的那批遠月，撐不出同樣的厚度。<br>
  這一步給的是<b>時間軸</b>，不是價位。價位可以每天重算，日期不會挪。
  ${figBlock(fig3(T),
    '左邊第一格撐起整張圖的絕大部分——它結算完，剩下的到期日補不上同樣的厚度。' +
    '同時注意 09-16 那一格：<b>未平倉是全場最多的，GEX 卻只有第二</b>。' +
    '越遠的到期日，每一口的 gamma 越小，堆再多口數也撐不出厚度。' +
    '示意數字，非實際盤面。',
    '<span style="color:var(--pos)">▮</span> 各到期日 GEX　<span style="color:var(--ink3)">◦┈</span> 各到期日未平倉')}

  <h3>步驟 4　讀牆與坑，但別把未平倉當成 gamma</h3>
  「正 GEX 集中」是上方的牆，「負 GEX 集中」是下方的坑。看距離現貨幾 % 比看絕對價位有用。<br>
  注意榜上常常會出現一個<b>貼著現價、未平倉其實不多</b>的履約價——它上榜純粹是因為價平的每口
  gamma 最大。這種牆會跟著價格移動，不是固定的地形。想分辨，把資料表打開對照該履約價的未平倉口數。<br>
  ${us ? '美股這邊還要留意：長天期履約價會有很大的未平倉，但每口 gamma 很小，在 GEX 上幾乎不佔份量。'
       : '台指這邊週選與月選的履約價間距不同（50 點 vs 100 點），合併看時建議把「履約價分桶」調成 100 點。'}
  ${figBlock(fig4(T),
    '兩根一樣高的柱子，來歷完全不同。貼著現價那根靠的是「價平每口 gamma 最大」，' +
    '未平倉其實很少——<b>它是現價的影子，明天現價換位置，它就跟著換</b>。' +
    '右邊那根靠的是實打實的兩千多口未平倉，價格走到哪它都在原地。' +
    '想分辨，把「資料表（逐履約價）」打開，比對該履約價的 Call / Put 未平倉口數。' +
    '示意數字，非實際盤面。')}

  <h3>步驟 5　對照「正 GEX 集中」與「負 VEX 集中」有沒有重疊</h3>
  如果同一批履約價同時出現在兩張榜上，那是<b>同一批部位的兩張臉</b>。<br>
  賣上方買權收租的部位，在平常的日子裡提供正 gamma，幫忙把價格壓在區間裡磨；
  但同一批部位的 vanna 是負的，波動率一跳，避險需求就反轉。<br>
  <b>平常幫忙壓波動的那幾堵牆，就是波動來的時候最先鬆手的那幾堵。</b>
  這是持倉留下的形狀，不是有人在佈局。
  ${figBlock(fig5(T),
    '上下兩排是同一條履約價軸。被框起來的那幾根，在「正 GEX 集中」和「負 VEX 集中」兩張榜上同時出現——' +
    '那是同一批賣方部位：gamma 是正的（幫忙磨），vanna 是負的（波動一跳就翻臉）。' +
    '<b>兩張榜的重疊程度，就是這張地圖有多脆的量尺。</b>' +
    '示意數字，非實際盤面。')}

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

/* --------------------------------------------------------- 偏好設定（存在瀏覽器）*/
const PREF = 'gexmap.pref';
function loadPref() {
  try { return JSON.parse(localStorage.getItem(PREF) || '{}'); } catch (e) { return {}; }
}
function savePref(p) {
  try { localStorage.setItem(PREF, JSON.stringify(p)); } catch (e) { /* 無痕模式等情況，忽略 */ }
}
function applyFs(v) {
  document.documentElement.style.setProperty('--fs', String(v));
  [...$('#segFs').querySelectorAll('button')].forEach(b =>
    b.setAttribute('aria-pressed', Math.abs(parseFloat(b.dataset.v) - v) < 1e-9));
}

/* --------------------------------------------------------- ⓘ 說明與設定抽屜 */
/* 畫面上只留數字，說明全部收進每一格右上角的 ⓘ。桌機滑過或點一下都會開，手機點一下開。 */
const CARD_HELP = {
  'k-spot': { t: '現貨 S', a: 'h-spot', h:
    '這張圖所有計算的基準價。台指與美股用<b>現貨收盤價</b>，ES 用<b>主力月期貨結算價</b>（所以 ES 那頁寫的是「期貨」）。'
    + '下面每一個「距現貨 ⋯%」都是跟這個數字比出來的。' },
  'k-flip': { t: 'Gamma Flip', a: 'c-flip', h:
    '總 GEX 由負轉正的那個價位。<b>在它下面</b>，造市商的避險是追漲殺跌，波動會被放大；'
    + '<b>在它上面</b>，避險變成逆勢調整，波動被壓抑。<br><br>'
    + '它是一條每天都會移動的線，<b>不是支撐壓力</b>——不要拿來當進出場點。' },
  'k-flipp': { t: 'GEX+ Flip', a: 'c-flipp', h:
    '把「跌的時候隱含波動率通常會漲」這件事也算進去之後的翻轉點。β 調得越大，它離 Gamma Flip 越遠。'
    + '實際行情多半落在這兩條線之間。' },
  'k-gex': { t: '總 GEX', a: 'c-gex', h:
    '標的每動 <b>1%</b>，造市商為了維持避險要買賣多少金額。<br><br>'
    + '<b>正的</b>＝他們逆勢調整（漲了賣、跌了買），行情容易被拉回、波動偏低。<br>'
    + '<b>負的</b>＝他們順勢調整（漲了追、跌了殺），波動容易被放大。' },
  'k-vex': { t: '總 VEX', a: 'c-vex', h:
    '隱含波動率每動 <b>1 個百分點</b>，造市商要調整的金額。用的是 <b>vanna</b> 不是 vega——'
    + 'vega 講的是部位損益，vanna 講的才是被迫產生的避險流量。<br><br>'
    + '負的代表 IV 上升時他們得賣標的，會讓跌勢更兇。' },
  'k-gexp': { t: '總 GEX+', a: 'c-gexp', h:
    '＝ 總 GEX ＋ β × 總 VEX。把價格與波動率的連動合成一個數字。'
    + 'β = 0 時它就退化成純 GEX；β 可以在右上角「設定」裡調。' },
  'c-gex': { t: '各履約價 GEX', a: 'g-gex', h:
    '每一個履約價各自貢獻多少 GEX。<b>看的是「哪幾根特別長」</b>，不是每一根的絕對值。<br><br>'
    + '長條特別長的價位，代表標的走到那附近時造市商要調整的量最大，行情容易在那裡卡住或加速。' },
  'c-vex': { t: '各履約價 VEX', a: 'g-vex', h:
    '同樣逐履約價，但看的是<b>波動率</b>變動造成的避險流量。'
    + '多半整片是負的，所以重點一樣放在「哪幾根特別深」，那是波動一旦擴大時壓力最集中的位置。' },
  'c-curve': { t: 'GEX 與 GEX+ 曲線', a: 'g-curve', h:
    '假設標的平移到各個價位、<b>重新把整本選擇權簿算一次</b>，畫出總量怎麼變。<br><br>'
    + '曲線跟零軸的交點，就是上面那兩個 Flip。曲線越陡，代表那一段價格區間的結構變化越劇烈。' },
  'c-exp': { t: '到期日結構拆解', a: 'g-exp', h:
    '曝險集中在哪一個結算日。<b>越近的到期通常越大</b>，因為快到期的合約 gamma 最集中。<br><br>'
    + '在上方「到期別」選單挑單一到期日，其他圖會跟著只看那一天。' },
  'c-notes': { t: '結構摘要', a: 'c-conc', h: '' },     // 內容在 drawSummary 裡動態塞
  'sym': { t: '這個標的', a: 'k-where', h: '' },        // 內容由 renderSymNote 塞
};

let popFor = null;
function closePop() {
  if (!popFor) return;
  popFor.setAttribute('aria-expanded', 'false');
  $('#pop').classList.remove('on');
  popFor = null;
}
function openPop(btn) {
  const key = btn.dataset.help, d = CARD_HELP[key];
  if (!d) return;
  const body = key === 'sym' ? SYM_HELP : (d.h || CARD_HELP[key].h);
  if (!body) return;
  const pop = $('#pop');
  pop.innerHTML = `<button class="x" type="button" aria-label="關閉">×</button>`
    + `<div class="pt">${d.t}</div><div>${body}</div>`
    + (d.a ? `<a class="more" href="guide.html#${d.a}">看完整說明 →</a>` : '');
  pop.classList.add('on');
  btn.setAttribute('aria-expanded', 'true');
  popFor = btn;
  // 先貼在按鈕下方，再夾回視窗內
  const r = btn.getBoundingClientRect(), pr = pop.getBoundingClientRect();
  let left = Math.min(r.left, window.innerWidth - pr.width - 10);
  let top = r.bottom + 8;
  if (top + pr.height > window.innerHeight - 10) top = Math.max(10, r.top - pr.height - 8);
  pop.style.left = Math.max(10, left) + 'px';
  pop.style.top = top + 'px';
}

function wireHelp() {
  const canHover = window.matchMedia('(hover:hover)').matches;
  document.addEventListener('click', ev => {
    const x = ev.target.closest('#pop .x');
    if (x) { closePop(); return; }
    if (ev.target.closest('#pop')) return;              // 彈出層裡面的連結照常運作
    const btn = ev.target.closest('.iq');
    if (!btn) { closePop(); return; }
    ev.preventDefault();
    if (popFor === btn) closePop(); else { closePop(); openPop(btn); }
  });
  if (canHover) {
    document.addEventListener('pointerover', ev => {
      const btn = ev.target.closest && ev.target.closest('.iq');
      if (btn && popFor !== btn) { closePop(); openPop(btn); }
    });
  }
  document.addEventListener('keydown', ev => {
    if (ev.key !== 'Escape') return;
    if (popFor) closePop(); else closeSetts();
  });
  window.addEventListener('scroll', closePop, { passive: true });
  window.addEventListener('resize', closePop);
}

/* ---- 設定抽屜 ---- */
function openSetts() {
  $('#setts').classList.add('on'); $('#backdrop').classList.add('on');
  $('#setts').setAttribute('aria-hidden', 'false');
  $('#btnAdv').setAttribute('aria-expanded', 'true');
}
function closeSetts() {
  $('#setts').classList.remove('on'); $('#backdrop').classList.remove('on');
  $('#setts').setAttribute('aria-hidden', 'true');
  $('#btnAdv').setAttribute('aria-expanded', 'false');
}
function wireSetts() {
  $('#btnAdv').addEventListener('click', () =>
    $('#setts').classList.contains('on') ? closeSetts() : openSetts());
  $('#settsClose').addEventListener('click', closeSetts);
  $('#backdrop').addEventListener('click', closeSetts);
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
  const warm = ev => { const b = ev.target.closest('button'); if (b) prefetch(b.dataset.v); };
  $('#segSym').addEventListener('pointerover', warm);
  $('#segSym').addEventListener('touchstart', warm, { passive: true });

  wireHelp();
  wireSetts();

  const pref = loadPref();
  applyFs(pref.fs || 1);
  if (pref.cvd === '1') { S.cvd = '1'; document.documentElement.setAttribute('data-cvd', '1'); }
  // 上次調好的設定接著用。要在第一次 switchTo 之前套，第一張圖才會直接是對的。
  if (pref.band != null && isFinite(+pref.band)) S.bandPref = +pref.band;
  if (pref.bucketBy && typeof pref.bucketBy === 'object') S.bucketBy = { ...pref.bucketBy };
  if (pref.sign === 'net' || pref.sign === 'gross') S.sign = pref.sign;
  if (pref.beta != null && isFinite(+pref.beta)) {
    S.beta = Math.max(0, Math.min(3, +pref.beta));
    $('#rngBeta').value = String(S.beta);
    $('#valBeta').textContent = S.beta.toFixed(1);
  }
  [...$('#segSign').querySelectorAll('button')].forEach(b =>
    b.setAttribute('aria-pressed', b.dataset.v === S.sign));

  const has = c => syms.some(x => x.code === c);
  const h = readHash();
  const start = has(h.sym) ? h.sym : (has(pref.sym) ? pref.sym : syms[0].code);
  try {
    await switchTo(start, has(h.sym) ? h.day : undefined);
  } catch (e) {
    await switchTo(syms[0].code);                  // 網址寫錯就退回預設，不要卡在錯誤畫面
  }
  [...$('#segCvd').querySelectorAll('button')].forEach(b =>
    b.setAttribute('aria-pressed', b.dataset.v === String(S.cvd)));

  $('#selDate').addEventListener('change', e => switchTo(S.sym, e.target.value));

  // 只改 hash 的導覽不會重新載入頁面，要自己接
  window.addEventListener('hashchange', () => {
    const h = readHash();
    if (!h.sym || !$(`#segSym button[data-v="${h.sym}"]`)) return;
    const sel = $('#selDate');
    const curDay = getComputedStyle($('#ctlDate')).display === 'none' ? '' : sel.value;
    if (h.sym === S.sym && (h.day || '') === (sel.selectedIndex === 0 ? '' : curDay)) return;
    switchTo(h.sym, h.day).catch(() => {});
  });
  $('#segExp').addEventListener('click', ev => {
    const b = ev.target.closest('button'); if (!b) return;
    [...$('#segExp').querySelectorAll('button')].forEach(x => x.setAttribute('aria-pressed', x === b));
    S.exp = b.dataset.v; render();
  });
  $('#selExp').addEventListener('change', e => { S.exp = e.target.value; render(); });
  segment($('#segSign'), 'sign', v => v, () => {
    savePref({ ...loadPref(), sign: S.sign }); render();
  });
  segment($('#segCvd'), 'cvd', v => v, () => {
    document.documentElement.setAttribute('data-cvd', S.cvd);
    savePref({ ...loadPref(), cvd: S.cvd }); render();
  });
  $('#segFs').addEventListener('click', ev => {
    const b = ev.target.closest('button'); if (!b) return;
    const v = parseFloat(b.dataset.v);
    applyFs(v); savePref({ ...loadPref(), fs: v }); render();
  });
  $('#selBand').addEventListener('change', e => {
    S.band = +e.target.value;
    S.bandPref = S.band;                     // 選過就記住，之後換標的不再自動挑
    savePref({ ...loadPref(), band: S.bandPref });
    mountBuckets(); render();
  });
  $('#selBucket').addEventListener('change', e => {
    S.bucket = parseFloat(e.target.value);
    S.bucketBy[S.sym] = S.bucket;            // 分桶逐標的記
    savePref({ ...loadPref(), bucketBy: S.bucketBy });
    render();
  });
  $('#rngBeta').addEventListener('input', e => {
    S.beta = +e.target.value; $('#valBeta').textContent = S.beta.toFixed(1); renderSoon();
  });
  // 存檔放在 change（放開滑鼠）而不是 input，不然拖一次會寫幾十筆
  $('#rngBeta').addEventListener('change', () => savePref({ ...loadPref(), beta: S.beta }));
  // 表格展開時才補畫（收起來的時候 drawTable / drawExpTable 會直接跳過）
  $('#dTable').addEventListener('toggle', () => {
    if ($('#dTable').open) { if (tblDirty) drawTable(buckets()); }
    else drawTable(null);                   // 收起就清空
  });
  $('#dExp').addEventListener('toggle', () => {
    if ($('#dExp').open) { if (expTblDirty) drawExpTable(); }
    else drawExpTable();
  });
  let t; const redraw = () => { clearTimeout(t); t = setTimeout(() => { mountExpiries(); render(); }, 160); };
  addEventListener('resize', redraw);
  addEventListener('orientationchange', redraw);

  // 第一頁畫完之後，趁瀏覽器空檔把其他標的也先抓好，之後切分頁就不用等網路。
  // 省流量模式或慢速連線就不做——這幾份加起來壓縮後約 2 MB。
  const net = navigator.connection || {};
  if (!window.__GEXMAP__ && !net.saveData && !/2g/.test(net.effectiveType || '')) {
    const rest = syms.map(x => x.code).filter(c => c !== S.sym);
    const idle = window.requestIdleCallback || (f => setTimeout(f, 1200));
    const next = () => { const c = rest.shift(); if (!c) return; prefetch(c); idle(next, { timeout: 5000 }); };
    idle(next, { timeout: 5000 });
  }
})();
