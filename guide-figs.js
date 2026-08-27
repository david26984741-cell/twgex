/* ===========================================================================
   教學頁的示意圖。
   每一則配一張，用 SVG 畫成「長得像網站那一塊」的樣子再標註。
   刻意不用截圖：站上的數字每天會變，截圖過幾天就跟實際畫面對不上；
   SVG 還能跟著字級與色盲配色一起變。圖裡的數字都是示意，不是實際盤面。
   =========================================================================== */
(function () {
  'use strict';

  /* ---------- 基礎元件 ---------------------------------------------------- */
  const W = 380;                                   // 所有圖共用的座標寬度
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const at = o => Object.entries(o)
    .filter(([, v]) => v !== null && v !== undefined && v !== false)
    .map(([k, v]) => `${k}="${v}"`).join(' ');

  let uid = 0;                                     // 每張圖的箭頭 marker 要有自己的 id，不然整頁 id 重複
  const svg = (h, body) => {
    const n = ++uid;
    const out = `<svg viewBox="0 0 ${W} ${h}" role="img" preserveAspectRatio="xMidYMid meet">
       <defs>
         <marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6"
                 orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8 z" fill="context-stroke"/></marker>
       </defs>${body}</svg>`;
    return out.split('#ah)').join(`#ah${n})`).split('id="ah"').join(`id="ah${n}"`);
  };

  const T = (x, y, s, o = {}) => `<text ${at({
    x, y, 'text-anchor': o.a || 'start', fill: o.fill || 'var(--ink2)',
    'font-size': o.s || 11.5, 'font-weight': o.b ? 600 : null,
    'font-family': o.mono ? 'ui-monospace,monospace' : null,
    'letter-spacing': o.ls || null, opacity: o.op || null,
  })}>${esc(s)}</text>`;

  const R = (x, y, w, h, o = {}) => `<rect ${at({
    x, y, width: Math.max(0, w), height: Math.max(0, h), rx: o.r == null ? 6 : o.r,
    fill: o.fill || 'var(--surface2)', stroke: o.stroke || 'var(--line)',
    'stroke-width': o.sw || 1, 'stroke-dasharray': o.dash || null, opacity: o.op || null,
  })}/>`;

  const L = (x1, y1, x2, y2, o = {}) => `<line ${at({
    x1, y1, x2, y2, stroke: o.stroke || 'var(--grid)', 'stroke-width': o.sw || 1,
    'stroke-dasharray': o.dash || null, opacity: o.op || null,
    'marker-end': o.arrow ? 'url(#ah)' : null,
    'marker-start': o.arrow === 2 ? 'url(#ah)' : null,
  })}/>`;

  const P = (d, o = {}) => `<path ${at({
    d, fill: o.fill || 'none', stroke: o.stroke || null, 'stroke-width': o.sw || 1.8,
    'stroke-linecap': 'round', 'stroke-linejoin': 'round',
    'stroke-dasharray': o.dash || null, opacity: o.op || null,
    'marker-end': o.arrow ? 'url(#ah)' : null,
  })}/>`;

  /* 圈出重點：外框 + 可選標籤 */
  const ring = (x, y, w, h, label, o = {}) =>
    R(x - 3, y - 3, w + 6, h + 6, { fill: 'none', stroke: o.c || 'var(--flip)', sw: 1.6, r: 8 }) +
    (label ? T(o.lx == null ? x + w / 2 : o.lx, o.ly == null ? y - 8 : o.ly, label,
      { a: o.la || 'middle', fill: o.c || 'var(--flip)', s: 11.5, b: 1 }) : '');

  /* 迷你長條圖：vals 可正可負，回傳 {svg, x(i), y(v), zero} */
  function bars(x, y, w, h, vals, o = {}) {
    const mx = Math.max(...vals.map(Math.abs), 1e-9);
    const zero = o.baseline === 'bottom' ? y + h : o.baseline === 'top' ? y : y + h / 2;
    const unit = o.baseline ? h : h / 2;
    const bw = Math.max(2, (w / vals.length) * (o.gap || 0.6));
    let s = L(x, zero, x + w, zero, { stroke: '#3a4a5e', sw: 1.2 });
    vals.forEach((v, i) => {
      const cx = x + (w / vals.length) * (i + 0.5);
      const hh = Math.abs(v) / mx * unit * 0.92;
      const col = o.color ? o.color(v, i) : (v >= 0 ? 'var(--pos)' : 'var(--neg)');
      s += R(cx - bw / 2, v >= 0 ? zero - hh : zero, bw, hh,
        { fill: col, stroke: 'none', r: 1, op: o.op ? o.op(v, i) : null });
    });
    return { s, cx: i => x + (w / vals.length) * (i + 0.5), zero, bw };
  }

  /* 摘要卡上的那種小方塊 */
  const tile = (x, y, w, h, k, v, sub, col) =>
    R(x, y, w, h, { r: 7 }) + T(x + 9, y + 15, k, { s: 10.5, fill: 'var(--ink2)' }) +
    T(x + 9, y + 34, v, { s: 16, b: 1, fill: col || 'var(--ink)' }) +
    (sub ? T(x + 9, y + h - 8, sub, { s: 10.5, fill: 'var(--ink3)' }) : '');

  /* 控制列上的那種分段按鈕 */
  function seg(x, y, items, onIdx, o = {}) {
    const w = o.w || 84, h = o.h || 22;
    let s = '';
    items.forEach((t, i) => {
      const on = i === onIdx;
      s += R(x + i * w, y, w, h, { r: i === 0 ? 5 : (i === items.length - 1 ? 5 : 2),
        fill: on ? '#22304a' : 'var(--surface2)' }) +
        T(x + i * w + w / 2, y + h / 2 + 4, t, { a: 'middle', s: o.s || 10.5,
          fill: on ? '#fff' : 'var(--ink3)' });
    });
    return s;
  }

  /* 面板外框（模擬網站上的一張圖卡） */
  const panel = (x, y, w, h, title, note) =>
    R(x, y, w, h, { fill: 'var(--surface)', r: 9 }) +
    (title ? T(x + 11, y + 17, title, { s: 12.5, b: 1, fill: 'var(--ink)' }) : '') +
    (note ? T(x + w - 11, y + 17, note, { a: 'end', s: 10.5, fill: 'var(--ink3)' }) : '');

  /* ---------- 圖 --------------------------------------------------------- */
  const F = {};

  /* 一、造市商被迫做什麼 */
  F.b1 = () => ({
    h: 176,
    body:
      T(0, 15, '同樣是上漲 1%，兩種環境引來的單子剛好相反', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      R(0, 24, 184, 140, { r: 8 }) +
      T(92, 42, '總 GEX 為正', { a: 'middle', s: 11.5, b: 1, fill: 'var(--pos)' }) +
      L(20, 62, 164, 62, { stroke: 'var(--line)' }) +
      T(14, 82, '價格 ↑ 1%', { s: 10.5 }) +
      P('M92 92 L92 108', { stroke: 'var(--pos)', arrow: 1, sw: 2 }) +
      T(92, 126, '造市商賣出', { a: 'middle', s: 11.5, b: 1, fill: 'var(--pos)' }) +
      T(92, 146, '→ 把價格拉回來', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
      R(196, 24, 184, 140, { r: 8 }) +
      T(288, 42, '總 GEX 為負', { a: 'middle', s: 11.5, b: 1, fill: 'var(--neg)' }) +
      L(216, 62, 360, 62, { stroke: 'var(--line)' }) +
      T(210, 82, '價格 ↑ 1%', { s: 10.5 }) +
      P('M288 92 L288 108', { stroke: 'var(--neg)', arrow: 1, sw: 2 }) +
      T(288, 126, '造市商買進', { a: 'middle', s: 11.5, b: 1, fill: 'var(--neg)' }) +
      T(288, 146, '→ 把價格推更遠', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
    cap: '所有「壓波動 / 放大波動」的說法都是從這裡來的：<b>同一個上漲，正 GEX 引來賣單，負 GEX 引來買單</b>。',
  });

  /* 二、方向是假設 */
  F.b2 = () => {
    const v = [0.3, 0.8, 1.5, 2.4, 1.9, 1.1, 0.5];
    const a = bars(24, 48, 150, 62, v);
    const b = bars(216, 48, 150, 62, v.map(x => -x));
    return {
      h: 178,
      body:
        T(0, 15, '同一天、同一批未平倉，換一個假設整張圖翻過來', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        R(0, 22, 184, 128, { r: 8 }) + T(92, 38, '買權多・賣權空（預設）', { a: 'middle', s: 10.5, fill: 'var(--ink2)' }) +
        a.s +
        T(92, 124, '總 GEX ＋18.2 億', { a: 'middle', s: 11.5, b: 1, fill: 'var(--pos)' }) +
        T(92, 140, 'Gamma Flip 45,106', { a: 'middle', s: 10.5, fill: 'var(--flip)' }) +
        R(196, 22, 184, 128, { r: 8 }) + T(288, 38, '兩邊皆空', { a: 'middle', s: 10.5, fill: 'var(--ink2)' }) +
        b.s +
        T(288, 124, '總 GEX −57.8 億', { a: 'middle', s: 11.5, b: 1, fill: 'var(--neg)' }) +
        T(288, 140, 'Gamma Flip —', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        T(190, 172, '看到任何結論，先確認它站在哪個假設上', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
      cap: '未平倉量沒有告訴你誰是買方。<b>右邊不是另一天的資料，是同一天換一個假設</b>——結論完全相反。示意數字。',
    };
  };

  /* 三、地形圖不是天氣 */
  F.b3 = () => ({
    h: 182,
    body:
      T(0, 15, '地圖畫的是路面，不是車子會往哪開', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      P('M20 108 L96 108 C108 108 108 138 120 138 L152 138 C164 138 164 108 176 108 L244 108 ' +
        'C256 108 256 74 268 74 L300 74 C312 74 312 108 324 108 L360 108',
        { stroke: 'var(--ink3)', sw: 2 }) +
      R(120, 108, 32, 30, { fill: 'var(--neg)', stroke: 'none', r: 0, op: .18 }) +
      R(268, 74, 32, 34, { fill: 'var(--pos)', stroke: 'none', r: 0, op: .18 }) +
      T(136, 158, '坑', { a: 'middle', s: 11.5, b: 1, fill: 'var(--neg)' }) +
      T(284, 64, '牆', { a: 'middle', s: 11.5, b: 1, fill: 'var(--pos)' }) +
      L(210, 40, 210, 150, { stroke: 'var(--spot)', sw: 1.4 }) +
      T(210, 34, '現在在這', { a: 'middle', s: 10.5, fill: 'var(--spot)' }) +
      P('M204 96 C186 92 168 96 150 116', { stroke: 'var(--ink2)', arrow: 1, dash: '4 3' }) +
      P('M216 96 C234 92 250 88 264 80', { stroke: 'var(--ink2)', arrow: 1, dash: '4 3' }) +
      T(28, 158, '掉進去會加速', { s: 10.5, fill: 'var(--ink3)' }) +
      T(352, 64, '會被推回來', { a: 'end', s: 10.5, fill: 'var(--ink3)' }) +
      T(190, 180, '兩條虛線都可能發生，地圖不預測是哪一條', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
    cap: '它只說：<b>往那邊走的時候，路面是被鋪平的還是有坑</b>。有坑不代表會跌，只代表跌下去的時候沒有人幫你踩煞車。',
  });

  /* 交易日：台指當天、美股慢一個交易日 */
  F['h-date'] = () => {
    const day = (x, lbl, on, col) =>
      R(x, 44, 58, 30, { fill: on ? 'var(--surface2)' : 'none', stroke: on ? (col || 'var(--line)') : 'var(--line)',
                         dash: on ? null : '3 3', r: 5 }) +
      T(x + 29, 63, lbl, { a: 'middle', s: 10.5, fill: on ? 'var(--ink)' : 'var(--ink3)' });
    return {
      h: 198,
      body:
        T(0, 15, '你今天打開網頁，看到的是哪一天的收盤？', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        T(380, 36, '今天＝週四早上', { a: 'end', s: 11.5, fill: 'var(--spot)' }) +
        day(0, '08/24', 1) + day(66, '08/25', 1) + day(132, '08/26', 1) + day(198, '08/27', 0) + day(264, '08/28', 0) +
        L(194, 42, 194, 88, { stroke: 'var(--spot)', sw: 1.4 }) +
        ring(132, 44, 58, 30, null, { c: 'var(--pos)' }) +
        L(161, 80, 161, 92, { stroke: 'var(--pos)' }) +
        T(161, 105, '台指', { a: 'middle', s: 11.5, b: 1, fill: 'var(--pos)' }) +
        ring(66, 44, 58, 30, null, { c: 'var(--flip)' }) +
        L(95, 80, 95, 110, { stroke: 'var(--flip)' }) +
        T(95, 123, '美股四檔', { a: 'middle', s: 11.5, b: 1, fill: 'var(--flip)' }) +
        T(0, 150, '美股的未平倉量要等 OCC 隔天美東上午才發布，所以價格與', { s: 10.5, fill: 'var(--ink3)' }) +
        T(0, 166, '未平倉一起退到前一個交易日收盤——寧可晚一天，', { s: 10.5, fill: 'var(--ink3)' }) +
        T(0, 182, '也不把兩個時點混在一起。', { s: 10.5, fill: 'var(--ink3)' }),
      cap: '週四早上打開，台指是 <b>08/26</b>、美股是 <b>08/25</b>，這是正常的不是資料壞掉。真正要警戒的是標題上方跳出黃色提醒。',
    };
  };

  /* 現貨 S / 期貨 */
  F['h-spot'] = () => ({
    h: 168,
    body:
      T(0, 15, '同一個 S&P，兩個座標系差幾十點', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      L(30, 60, 350, 60, { stroke: 'var(--line)' }) +
      T(0, 64, 'SPX', { s: 10.5, fill: 'var(--ink2)' }) +
      L(180, 50, 180, 70, { stroke: 'var(--spot)', sw: 2 }) +
      T(180, 44, '7,677', { a: 'middle', s: 12.5, b: 1, fill: 'var(--ink)' }) +
      L(30, 118, 350, 118, { stroke: 'var(--line)' }) +
      T(0, 122, 'ES', { s: 10.5, fill: 'var(--ink2)' }) +
      L(210, 108, 210, 128, { stroke: 'var(--spot)', sw: 2 }) +
      T(210, 102, '7,692', { a: 'middle', s: 12.5, b: 1, fill: 'var(--ink)' }) +
      L(180, 74, 210, 104, { stroke: 'var(--flip)', dash: '3 3', arrow: 1 }) +
      T(360, 92, '＋15 點（基差）', { a: 'end', s: 10.5, fill: 'var(--flip)' }) +
      T(0, 152, 'ES 分頁上寫的是「期貨 S」不是「現貨 S」，Flip 也是期貨的價位。', { s: 10.5, fill: 'var(--ink3)' }),
    cap: '拿 <b>ES 的 Flip 直接對照 SPX 現貨</b>會系統性偏移一個基差。看夜盤連動用 ES，看整體結構用 SPX。示意數字。',
  });

  /* 契約數 / 到期日數：拿來看資料有沒有缺 */
  F['h-legs'] = () => {
    const v = [9905, 9880, 9910, 9890, 4120, 9900];   // 第五天來源缺資料
    const b = bars(30, 40, 320, 70, v, { baseline: 'bottom',
      color: (x) => x < 6000 ? 'var(--neg)' : 'var(--pos)', op: x => x < 6000 ? 1 : .55 });
    return {
      h: 176,
      body:
        T(0, 15, '這兩個數字唯一的用途：看今天的資料有沒有缺', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        b.s +
        ['08/19', '08/20', '08/21', '08/24', '08/25', '08/26'].map((d, i) =>
          T(b.cx(i), 124, d, { a: 'middle', s: 10.5, fill: 'var(--ink3)' })).join('') +
        T(0, 30, 'SPY 每日契約數', { s: 10.5, fill: 'var(--ink3)' }) +
        ring(b.cx(4) - 18, 78, 36, 32, '掉到一半', { c: 'var(--neg)', ly: 72 }) +
        T(0, 148, '這不是市場變了，是來源那天缺資料——', { s: 10.5, fill: 'var(--ink3)' }) +
        T(0, 164, '當天的所有總量都會偏小，不要拿來跟其他天比。', { s: 10.5, fill: 'var(--ink3)' }),
      cap: '正常量級：台指約 1,600 份 / 9 個到期日，SPX 約 2 萬 / 近 60 個，ES 約 1 萬 / 約 50 個，SPY、QQQ 各約 9 千 / 31 個。',
    };
  };

  /* 未平倉總量 */
  F['h-oi'] = () => {
    const v = [78, 79, 80, 46, 52, 58, 57, 50];
    const b = bars(30, 40, 320, 68, v, { baseline: 'bottom',
      color: (x, i) => i === 3 ? 'var(--pos)' : i === 7 ? 'var(--neg)' : 'var(--ink3)',
      op: (x, i) => (i === 3 || i === 7) ? 1 : .5 });
    return {
      h: 176,
      body:
        T(0, 15, '總量掉下來有兩種：一種正常，一種要注意', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        b.s +
        T(0, 30, '台指未平倉總口數（萬口）', { s: 10.5, fill: 'var(--ink3)' }) +
        L(b.cx(3), 112, b.cx(3), 124, { stroke: 'var(--pos)' }) +
        T(b.cx(3), 138, '結算日隔天', { a: 'middle', s: 10.5, fill: 'var(--pos)' }) +
        T(b.cx(3), 152, '正常', { a: 'middle', s: 10.5, fill: 'var(--pos)' }) +
        L(b.cx(7), 112, b.cx(7), 124, { stroke: 'var(--neg)' }) +
        T(b.cx(7), 138, '沒結算卻縮水', { a: 'middle', s: 10.5, fill: 'var(--neg)' }) +
        T(b.cx(7), 152, '有人在平倉', { a: 'middle', s: 10.5, fill: 'var(--neg)' }),
      cap: '結算後的斷崖是那批到期了，本來就會掉。<b>在沒有結算的日子縮水</b>才是訊號——圖上的牆會跟著變薄。示意數字。',
    };
  };

  /* OI 覆蓋 */
  F['h-cov'] = () => {
    const bar = (y, pct, col, lbl) =>
      R(30, y, 300, 22, { fill: 'var(--surface2)', r: 4 }) +
      R(30, y, 300 * pct, 22, { fill: col, stroke: 'none', r: 4 }) +
      T(336, y + 16, lbl, { s: 11.5, b: 1, fill: col });
    return {
      h: 172,
      body:
        T(0, 15, '有未平倉的合約，有多少比例真的進得了計算', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        T(0, 44, '正常', { s: 10.5, fill: 'var(--ink2)' }) + bar(30, 1, 'var(--pos)', '100%') +
        T(0, 92, '這天', { s: 10.5, fill: 'var(--ink2)' }) + bar(78, 0.74, 'var(--neg)', '74%') +
        R(252, 78, 78, 22, { fill: 'none', stroke: 'var(--neg)', dash: '3 3', r: 4 }) +
        T(291, 116, '反解不出隱含波動率', { a: 'middle', s: 10.5, fill: 'var(--neg)' }) +
        T(291, 130, '被剔除的部分', { a: 'middle', s: 10.5, fill: 'var(--neg)' }) +
        T(0, 158, '低於 80% 就代表相當一部分未平倉沒算進去，總量偏小、Flip 位置也可能偏掉。',
          { s: 10.5, fill: 'var(--ink3)' }),
      cap: '覆蓋率突然掉下來的那一天，當成<b>「這天資料品質差」</b>處理，不要拿它跟其他天做趨勢比較。',
    };
  };


  /* 總 GEX：看方向不看絕對值 */
  F['c-gex'] = () => {
    const days = ['08/20', '08/21', '08/24', '08/25', '08/26'];
    const row = (y, lbl, vals, col, unit) => {
      const b = bars(96, y, 190, 34, vals, { baseline: 'bottom', color: () => col, op: () => .8 });
      return T(0, y + 22, lbl, { s: 10.5, fill: 'var(--ink2)' }) + b.s +
        T(380, y + 22, unit, { a: 'end', s: 10.5, b: 1, fill: col });
    };
    return {
      h: 208,
      body:
        T(0, 15, '五天裡沒有一個數字跨過零，但三條一起往同一邊走', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        row(26, '總 GEX', [28, 25, 22, 20, 18], 'var(--pos)', '＋18 億') +
        row(72, '總 VEX', [3.1, 4.0, 5.0, 6.0, 6.8], 'var(--neg)', '−6.8 億') +
        row(118, '總 GEX+', [25, 21, 17, 13, 11], 'var(--curve2)', '＋11 億') +
        days.map((d, i) => T(96 + 190 / 5 * (i + 0.5), 168, d,
          { a: 'middle', s: 10.5, fill: 'var(--ink3)' })).join('') +
        T(0, 194, '只看今天：「結構還行」。看斜率：「這面牆正在被拆」。', { s: 11.5, b: 1, fill: 'var(--flip)' }),
      cap: '正的兩個一路變薄、負的那個一路變厚。<b>單日數字沒有意義，要用「資料日期」往回切幾天比。</b>示意數字。',
    };
  };

  /* Gamma Flip：兩張圖 */
  F['c-flip'] = () => [
    {
      h: 176,
      body:
        T(0, 15, 'Flip＝把價格假設性地平移，總 GEX 由正翻負的那一點', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        L(28, 100, 366, 100, { stroke: '#3a4a5e', sw: 1.3 }) + T(14, 104, '0', { s: 10.5, fill: 'var(--ink3)' }) +
        P('M40 142 C110 132 150 116 176 100 C214 78 280 50 360 40', { stroke: 'var(--curve1)', sw: 2.4 }) +
        L(176, 34, 176, 152, { stroke: 'var(--flip)', dash: '3 3', sw: 1.5 }) +
        `<circle cx="176" cy="100" r="4.5" fill="var(--flip)"/>` +
        T(176, 166, 'Gamma Flip', { a: 'middle', s: 10.5, b: 1, fill: 'var(--flip)' }) +
        L(286, 34, 286, 152, { stroke: 'var(--spot)', sw: 1.5 }) +
        T(286, 166, '現貨', { a: 'middle', s: 10.5, b: 1, fill: 'var(--spot)' }) +
        T(48, 126, '總 GEX 為負', { s: 10.5, fill: 'var(--neg)' }) +
        T(310, 72, '總 GEX 為正', { s: 10.5, fill: 'var(--pos)' }) +
        L(180, 42, 282, 42, { stroke: 'var(--ink3)', arrow: 2 }) +
        T(231, 36, '緩衝', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
      cap: '在「情境曲線」那張圖上可以直接看到這一點，還能看出<b>穿過零軸時有多陡</b>——陡＝破了就變得很快，平＝跨過去也還在模糊地帶。',
    },
    (() => {
      const spotA = [44300, 44700, 45200, 45700, 46000], flipA = [44300, 44320, 44290, 44310, 44300];
      const spotB = [45900, 46100, 45950, 46050, 46000], flipB = [45900, 45500, 45000, 44600, 44300];
      const lo = 43900, hi = 46400, X0 = 44, Xw = 248;
      const pnl = (y, title, sp, fl) => {
        const px = i => X0 + Xw / 4 * i, py = v => y + 72 - (v - lo) / (hi - lo) * 64;
        return T(0, y + 8, title, { s: 12.5, b: 1, fill: 'var(--ink)' }) +
          P(sp.map((v, i) => (i ? 'L' : 'M') + px(i) + ' ' + py(v)).join(' '), { stroke: 'var(--spot)', sw: 2 }) +
          P(fl.map((v, i) => (i ? 'L' : 'M') + px(i) + ' ' + py(v)).join(' '),
            { stroke: 'var(--flip)', sw: 2, dash: '4 3' }) +
          T(380, py(sp[4]) + 4, sp[4].toLocaleString(), { a: 'end', s: 10.5, fill: 'var(--spot)' }) +
          T(380, py(fl[4]) + 4, fl[4].toLocaleString(), { a: 'end', s: 10.5, fill: 'var(--flip)' });
      };
      return {
        h: 234,
        body:
          T(0, 15, '「距現貨 −3.7%」有兩種來歷，賠率完全不同', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
          pnl(22, 'A　門檻沒動，是價格自己跑掉了', spotA, flipA) +
          pnl(126, 'B　現貨沒動，是門檻自己退開了', spotB, flipB) +
          T(0, 224, 'A 跌回 44,300 處境跟五天前一樣；B 是真的多讓出一層。' , { s: 10.5, fill: 'var(--ink3)' }) +
          T(300, 216, '━ 現貨', { s: 10.5, fill: 'var(--spot)' }) +
          T(300, 230, '┅ Gamma Flip', { s: 10.5, fill: 'var(--flip)' }),
        cap: '兩張圖的<b>今天完全相同</b>：現貨 46,000、Flip 44,300、距現貨 −3.7%。摘要卡上只看得到這一格，分不出來。' +
             '<b>要分辨只能用「資料日期」往回切，看是誰在動。</b>示意數字。',
      };
    })(),
  ];

  /* GEX+ Flip */
  F['c-flipp'] = () => ({
    h: 180,
    body:
      T(0, 15, '把「跌的時候波動率會上升」算進去，門檻會提前到來', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      L(28, 104, 366, 104, { stroke: '#3a4a5e', sw: 1.3 }) + T(14, 108, '0', { s: 10.5, fill: 'var(--ink3)' }) +
      P('M40 148 C110 138 150 122 176 104 C214 80 280 52 360 42', { stroke: 'var(--curve1)', sw: 2.2 }) +
      P('M40 162 C120 152 176 130 232 104 C280 82 320 64 360 56', { stroke: 'var(--curve2)', sw: 2.2 }) +
      L(176, 36, 176, 118, { stroke: 'var(--flip)', dash: '3 3' }) +
      L(232, 36, 232, 118, { stroke: 'var(--flip2)', dash: '3 3' }) +
      R(176, 96, 56, 16, { fill: 'var(--flip2)', stroke: 'none', r: 3, op: .2 }) +
      T(204, 132, '被波動率', { a: 'middle', s: 10.5, fill: 'var(--flip2)' }) +
      T(204, 146, '吃掉的緩衝', { a: 'middle', s: 10.5, fill: 'var(--flip2)' }) +
      T(176, 30, 'Gamma Flip', { a: 'middle', s: 10.5, fill: 'var(--flip)' }) +
      T(258, 30, 'GEX+ Flip', { s: 10.5, fill: 'var(--flip2)' }) +
      T(300, 168, '━ GEX', { s: 10.5, fill: 'var(--curve1)' }) +
      T(300, 154, '━ GEX+（β=1）', { s: 10.5, fill: 'var(--curve2)' }) +
      T(0, 168, '實務上以 GEX+ Flip 為主要門檻', { s: 10.5, b: 1, fill: 'var(--ink2)' }),
    cap: '總 VEX 幾乎永遠是負的，所以 GEX+ Flip <b>通常比 Gamma Flip 高</b>。兩條之間的距離＝這個結構對波動率有多敏感。',
  });

  /* 總 VEX：自我強化的迴圈 */
  F['c-vex'] = () => {
    const box = (x, y, w, t1, t2, col) =>
      R(x, y, w, 40, { r: 7, stroke: col }) +
      T(x + w / 2, y + (t2 ? 18 : 25), t1, { a: 'middle', s: 10.5, b: 1, fill: col }) +
      (t2 ? T(x + w / 2, y + 33, t2, { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) : '');
    return {
      h: 190,
      body:
        T(0, 15, '總 VEX 很負，代表這個迴圈轉得動', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        box(0, 30, 104, '標的下跌', null, 'var(--neg)') +
        P('M108 50 L136 50', { stroke: 'var(--ink3)', arrow: 1 }) +
        box(140, 30, 104, '隱含波動率跳升', null, 'var(--neg)') +
        P('M248 50 L276 50', { stroke: 'var(--ink3)', arrow: 1 }) +
        box(280, 30, 100, '造市商被迫', '賣出標的', 'var(--neg)') +
        P('M330 74 L330 96 L50 96 L50 74', { stroke: 'var(--neg)', arrow: 1, dash: '4 3' }) +
        T(190, 114, '又跌 → 再轉一圈', { a: 'middle', s: 11.5, b: 1, fill: 'var(--neg)' }) +
        T(0, 144, '總 VEX 越負，這一圈每轉一次倒出來的量越大。', { s: 10.5, fill: 'var(--ink3)' }) +
        T(0, 162, '它不是「波動率會不會上升」的預測，是「如果上升了會怎樣」的換算——', { s: 10.5, fill: 'var(--ink3)' }) +
        T(0, 180, '平靜的日子它一樣很負，什麼都不會發生。', { s: 10.5, fill: 'var(--ink3)' }),
      cap: '要看的不是正負（它幾乎永遠是負的），是<b>有多負</b>。跟總 GEX 一起變薄的時候最值得縮部位。',
    };
  };

  /* 總 GEX+ 與 β */
  F['c-gexp'] = () => {
    const mark = (x, col, top, lbl) =>
      L(x, top, x, 108, { stroke: col, dash: '3 3', sw: 1.4 }) +
      `<circle cx="${x}" cy="108" r="4" fill="${col}"/>` +
      T(x, top - 6, lbl, { a: 'middle', s: 10.5, b: 1, fill: col });
    return {
      h: 196,
      body:
        T(0, 15, '把 β 從 0 拉到 2，看 GEX+ Flip 跑多遠', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        L(30, 108, 360, 108, { stroke: 'var(--line)', sw: 1.4 }) +
        T(30, 128, '低', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        T(360, 128, '高', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        T(195, 146, '價位', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        mark(120, 'var(--flip)', 76, 'β=0（＝Gamma Flip）') +
        mark(196, 'var(--flip2)', 52, 'β=1') +
        mark(272, 'var(--flip2)', 28, 'β=2') +
        T(0, 168, '跑很少 → 這個結構由 gamma 主導，看 GEX 就夠。', { s: 10.5, fill: 'var(--ink3)' }) +
        T(0, 184, '跑很遠 → 波動率才是主角，要更看重 VEX 那一側。', { s: 10.5, fill: 'var(--ink3)' }),
      cap: 'β 是<b>假設不是市場報價</b>。看到一個 GEX+ Flip 數字，先看它旁邊寫的 β 是多少。把它當敏感度分析用，不要當成要調到「正確值」。',
    };
  };

  /* 總 vega 曝險 vs VEX */
  F['c-vega'] = () => ({
    h: 168,
    body:
      T(0, 15, '波動率升 1 點，兩件不同的事', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      R(0, 26, 184, 108, { r: 8, stroke: 'var(--neg)' }) +
      T(92, 46, '總 VEX（vanna）', { a: 'middle', s: 11.5, b: 1, fill: 'var(--neg)' }) +
      T(92, 70, '要去市場上買賣多少標的', { a: 'middle', s: 10.5, fill: 'var(--ink2)' }) +
      P('M52 84 L132 84', { stroke: 'var(--neg)', arrow: 1, sw: 2 }) +
      T(92, 106, '會產生實際的單', { a: 'middle', s: 10.5, b: 1, fill: 'var(--neg)' }) +
      T(92, 122, '→ 會推動價格', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
      R(196, 26, 184, 108, { r: 8 }) +
      T(288, 46, '總 vega 曝險', { a: 'middle', s: 11.5, b: 1, fill: 'var(--ink2)' }) +
      T(288, 70, '部位帳面賺賠多少', { a: 'middle', s: 10.5, fill: 'var(--ink2)' }) +
      L(248, 84, 328, 84, { stroke: 'var(--ink3)', dash: '4 3' }) +
      T(288, 106, '只是帳上的數字', { a: 'middle', s: 10.5, b: 1, fill: 'var(--ink3)' }) +
      T(288, 122, '→ 不產生任何單', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
      T(190, 158, 'vega 拿來當規模參考，不要當訊號', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
    cap: '這是本站把 VEX 定義成 <b>vanna</b> 而不是 vega 的原因：只有 vanna 對應到<b>被迫的買賣</b>，vega 不會推動價格。',
  });


  /* 正 / 負 GEX 集中：真牆 vs 影子 */
  F['c-conc'] = () => {
    const v = [-.5, -.9, -2.1, -1.2, -.4, 2.0, .5, .4, 1.98, .3];
    const b = bars(30, 34, 320, 80, v);
    return {
      h: 234,
      body:
        T(0, 15, '兩根一樣高的柱子，來歷完全不同', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        b.s +
        L(b.cx(5), 28, b.cx(5), 122, { stroke: 'var(--spot)', sw: 1.4 }) +
        T(b.cx(5), 24, '現貨', { a: 'middle', s: 10.5, fill: 'var(--spot)' }) +
        ring(b.cx(5) - 11, 34, 22, 40, null, { c: 'var(--ink)' }) +
        ring(b.cx(8) - 11, 34, 22, 40, null, { c: 'var(--ink)' }) +
        T(0, 146, '貼著現價那根', { s: 11.5, b: 1, fill: 'var(--ink)' }) +
        T(0, 164, '未平倉只有 180 口', { s: 10.5, fill: 'var(--ink3)' }) +
        T(0, 180, '靠「價平每口 gamma 最大」', { s: 10.5, fill: 'var(--ink3)' }) +
        T(0, 200, '＝現價的影子，明天換位置', { s: 10.5, b: 1, fill: 'var(--neg)' }) +
        T(380, 146, '右邊那根', { a: 'end', s: 11.5, b: 1, fill: 'var(--ink)' }) +
        T(380, 164, '未平倉 2,340 口', { a: 'end', s: 10.5, fill: 'var(--ink3)' }) +
        T(380, 180, '實打實堆出來的', { a: 'end', s: 10.5, fill: 'var(--ink3)' }) +
        T(380, 200, '＝真的牆，走到哪它都在', { a: 'end', s: 10.5, b: 1, fill: 'var(--pos)' }) +
        T(190, 226, '上方＝牆，下方＝坑；看距現貨幾 % 比看絕對價位有用', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
      cap: '要分辨，把<b>「資料表（逐履約價）」</b>打開，比對那個履約價的 Call / Put 未平倉口數。口數少的就是影子，別拿它當支撐壓力。示意數字。',
    };
  };

  /* 負 VEX 集中：同一批部位的兩張臉 */
  F['c-vconc'] = () => {
    const g = [.2, .4, 1.6, 1.9, 1.7, .5, .3];
    const w = [-.2, -.3, -1.5, -1.8, -1.6, -.4, -.2];
    const a = bars(60, 34, 260, 52, g, { baseline: 'bottom' });
    const c = bars(60, 116, 260, 52, w, { baseline: 'top' });
    let box = '';
    [2, 3, 4].forEach(i => { box += R(a.cx(i) - 15, 30, 30, 142, { fill: 'var(--flip)', stroke: 'none', r: 4, op: .12 }); });
    return {
      h: 224,
      body:
        T(0, 15, '同一批履約價同時上兩張榜＝同一批部位的兩張臉', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        box + a.s + c.s +
        T(0, 60, '正 GEX', { s: 10.5, b: 1, fill: 'var(--pos)' }) +
        T(0, 74, '集中', { s: 10.5, b: 1, fill: 'var(--pos)' }) +
        T(0, 142, '負 VEX', { s: 10.5, b: 1, fill: 'var(--neg)' }) +
        T(0, 156, '集中', { s: 10.5, b: 1, fill: 'var(--neg)' }) +
        T(a.cx(3), 190, '重疊的這幾根', { a: 'middle', s: 11.5, b: 1, fill: 'var(--flip)' }) +
        T(190, 208, '平常提供正 gamma 幫忙磨　／　波動率一跳 vanna 翻臉', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        T(190, 222, '＝平常幫忙壓波動的那幾堵牆，就是最先鬆手的那幾堵', { a: 'middle', s: 10.5, b: 1, fill: 'var(--ink2)' }),
      cap: '<b>兩張榜的重疊程度，就是這張地圖有多脆的量尺。</b>重疊多＝這個看起來很穩的盤，其實靠同一批部位撐著。',
    };
  };

  /* 未平倉牆 vs GEX 集中 */
  F['c-wall'] = () => {
    const oi = [3.1, 1.2, .8, .9, 1.1, .7, .6];
    const gx = [.3, .5, .9, 2.6, 2.2, .8, .4];
    const a = bars(60, 32, 280, 46, oi, { baseline: 'bottom', color: () => 'var(--ink2)', op: () => .7 });
    const c = bars(60, 108, 280, 46, gx, { baseline: 'bottom', color: () => 'var(--pos)' });
    return {
      h: 208,
      body:
        T(0, 15, '口數最多的地方，不一定是曝險最大的地方', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        a.s + T(0, 58, '未平倉', { s: 10.5, b: 1, fill: 'var(--ink2)' }) + T(0, 72, '口數', { s: 10.5, fill: 'var(--ink2)' }) +
        c.s + T(0, 134, 'GEX', { s: 10.5, b: 1, fill: 'var(--pos)' }) +
        L(a.cx(0), 84, a.cx(0), 100, { stroke: 'var(--ink3)', dash: '3 3' }) +
        L(c.cx(3), 84, c.cx(3), 100, { stroke: 'var(--pos)', dash: '3 3' }) +
        T(a.cx(0), 96, '這裡口數最多', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        T(c.cx(3), 96, '這裡曝險最大', { a: 'middle', s: 10.5, fill: 'var(--pos)' }) +
        T(0, 178, '遠月履約價可以堆很多口，但每口 gamma 很小，在 GEX 上幾乎不佔份量。', { s: 10.5, fill: 'var(--ink3)' }) +
        T(0, 198, '兩者指到不同價位時，以 GEX 為準。', { s: 11.5, b: 1, fill: 'var(--flip)' }),
      cap: '把<b>未平倉牆當成「大家在哪裡下注」</b>，把 <b>GEX 集中區當成「哪裡真的會產生買賣單」</b>。兩者重疊的位置最值得注意。示意數字。',
    };
  };

  /* 資料產出範圍外 */
  F['c-outside'] = () => ({
    h: 176,
    body:
      T(0, 15, '畫面上看不到的那些，已經算進總量了', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      R(0, 34, 380, 40, { r: 6, fill: 'none', dash: '4 3' }) +
      T(190, 28, '資料檔保留的逐履約價明細（台指 ±25%、美股 ±50%）', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
      R(96, 40, 188, 28, { r: 4, fill: 'var(--surface2)' }) +
      T(190, 58, '顯示區間 ±10%（畫面上看到的）', { a: 'middle', s: 10.5, fill: 'var(--ink2)' }) +
      R(4, 40, 88, 28, { r: 4, fill: 'var(--neg)', stroke: 'none', op: .18 }) +
      R(288, 40, 88, 28, { r: 4, fill: 'var(--neg)', stroke: 'none', op: .18 }) +
      T(48, 58, '看不到', { a: 'middle', s: 10.5, fill: 'var(--neg)' }) +
      T(332, 58, '看不到', { a: 'middle', s: 10.5, fill: 'var(--neg)' }) +
      L(48, 76, 48, 92, { stroke: 'var(--neg)' }) + L(332, 76, 332, 92, { stroke: 'var(--neg)' }) +
      T(190, 106, '但總 GEX、總 VEX、兩條 Flip 都是用「全部履約價」算的', { a: 'middle', s: 12.5, b: 1, fill: 'var(--ink)' }) +
      T(190, 130, '改「顯示區間」只改中間那一格，不會改變摘要卡最後那行的任何數字',
        { a: 'middle', s: 10.5, fill: 'var(--flip)' }) +
      T(0, 162, '那行顯示「佔總 GEX 0.05%」→ 遠端沒份量，你看到的圖就是全貌。', { s: 10.5, fill: 'var(--ink3)' }),
    cap: '注意這個百分比的分母是總 GEX。<b>總 GEX 本身接近零的日子（兩邊幾乎抵銷），這個比例會被放大得很難看</b>——回頭看絕對值。',
  });


  /* GEX 各履約價：四種形狀 */
  F['g-gex'] = () => {
    const sets = [
      { t: '上有蓋、下有洞', d: '向上磨、向下滑（最常見）', v: [-.6, -1.4, -2.2, -1.0, 1.6, 2.2, 1.8, 1.2] },
      { t: '綠色集中在很窄幾根', d: '結構脆，一結算整張圖就變', v: [-.3, -.4, -.5, -.3, .4, 3.0, 2.6, .3] },
      { t: '綠色平均散開', d: '厚實，不會因單一到期日消失', v: [-.5, -.6, -.7, -.5, 1.2, 1.3, 1.2, 1.1] },
      { t: '現貨卡在一根大綠柱上', d: '被釘住，容易整天不動', v: [-.4, -.5, -.6, 2.8, .6, .5, .4, .3], sp: 3 },
    ];
    let body = T(0, 15, '不要一根一根看，先看形狀', { s: 12.5, b: 1, fill: 'var(--ink)' });
    sets.forEach((sv, i) => {
      const x = (i % 2) * 196, y = 26 + Math.floor(i / 2) * 104;
      const b = bars(x + 6, y + 18, 172, 44, sv.v);
      const spotX = b.cx(sv.sp == null ? 3.5 : sv.sp);
      body += R(x, y, 184, 92, { r: 7 }) + b.s +
        L(spotX, y + 14, spotX, y + 66, { stroke: 'var(--spot)', sw: 1.2, op: .8 }) +
        T(x + 92, y + 76, sv.t, { a: 'middle', s: 10.5, b: 1, fill: 'var(--ink)' }) +
        T(x + 92, y + 88, sv.d, { a: 'middle', s: 10.5, fill: 'var(--ink3)' });
    });
    body += T(190, 244, '白線＝現貨。柱子的高度是金額，不是口數。', { a: 'middle', s: 10.5, fill: 'var(--ink3)' });
    return { h: 252, body,
      cap: '滑鼠移上去（手機按住）會顯示那個履約價的 Call / Put 未平倉、GEX、VEX。<b>把榜上前幾名都掃一遍，就知道哪幾根是真牆。</b>' };
  };

  /* VEX 各履約價 */
  F['g-vex'] = () => {
    const v = [-1.5, -1.9, -1.2, -.5, -.15, -.5, -1.3, -1.8, -1.4];
    const b = bars(40, 40, 300, 60, v, { baseline: 'top',
      color: (x, i) => i < 4 ? 'var(--put)' : 'var(--call)' });
    return {
      h: 190,
      body:
        T(0, 15, '中間那個凹陷是必然的，不是資料怪', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        b.s +
        L(b.cx(4), 34, b.cx(4), 118, { stroke: 'var(--spot)', sw: 1.4 }) +
        T(b.cx(4), 30, '現貨', { a: 'middle', s: 10.5, fill: 'var(--spot)' }) +
        T(b.cx(4), 134, 'vanna 在價平兩側變號，', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        T(b.cx(4), 148, '跟 Call OI − Put OI 的變號互相配合', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        T(b.cx(1), 126, '賣權主導', { a: 'middle', s: 10.5, b: 1, fill: 'var(--put)' }) +
        T(b.cx(7), 126, '買權主導', { a: 'middle', s: 10.5, b: 1, fill: 'var(--call)' }) +
        T(0, 176, '要看兩件事：重心偏在現貨哪一邊、以及跟 GEX 圖的形狀有沒有重疊。', { s: 10.5, fill: 'var(--ink3)' }),
      cap: '顏色分的是<b>買權主導還是賣權主導</b>，不是正負。負 VEX 集中在下方 → 跌的時候被迫賣出的壓力集中在下方，容易加速。',
    };
  };

  /* 情境曲線：陡 vs 平 */
  F['g-curve'] = () => {
    const pnl = (x, title, d, note, col) =>
      R(x, 26, 184, 116, { r: 7 }) +
      T(x + 92, 44, title, { a: 'middle', s: 11.5, b: 1, fill: col }) +
      L(x + 16, 100, x + 168, 100, { stroke: '#3a4a5e', sw: 1.2 }) +
      P(d, { stroke: col, sw: 2.2 }) +
      L(x + 92, 54, x + 92, 130, { stroke: 'var(--flip)', dash: '3 3' }) +
      T(x + 92, 158, note, { a: 'middle', s: 10.5, fill: 'var(--ink3)' });
    return {
      h: 200,
      body:
        T(0, 15, '摘要卡給你「點」，這張圖給你「斜率」', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        pnl(0, '穿得很陡', 'M16 128 L70 120 L92 100 L114 80 L168 70'.replace(/(\d+) (\d+)/g, (m, a, b) => `${+a} ${+b}`),
            '跨過門檻後性質變很快', 'var(--neg)') +
        pnl(196, '穿得很平', 'M212 116 L266 108 L288 100 L310 92 L364 84', '跨過去也還在模糊地帶', 'var(--pos)') +
        T(190, 182, '只看現貨附近 ±3% 那一段，其他當參考——', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        T(190, 196, '這是「瞬間平移」的假設，離現貨越遠可信度越低', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
      cap: '橘色虛線是零軸交叉（Flip）。<b>陡＝一旦破就破得乾脆；平＝跨過去也不會立刻惡化。</b>兩條線（GEX 與 GEX+）的間距＝波動率效應吃掉多少緩衝。',
    };
  };

  /* 到期日結構拆解 */
  F['g-exp'] = () => {
    const gx = [4.2, .6, .9, 1.1, 1.6, .5, .4, .3];
    const oi = [.9, .5, .7, .8, 2.4, .6, .5, .4];
    const b = bars(34, 34, 316, 72, gx, { baseline: 'bottom' });
    const oiY = v => 106 - v / 2.4 * 62;
    const line = oi.map((v, i) => (i ? 'L' : 'M') + b.cx(i).toFixed(0) + ' ' + oiY(v).toFixed(0)).join(' ');
    return {
      h: 208,
      body:
        T(0, 15, '現在這些厚度是誰撐的？', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        b.s + P(line, { stroke: 'var(--ink3)', dash: '3 3', sw: 1.6 }) +
        oi.map((v, i) => `<circle cx="${b.cx(i).toFixed(0)}" cy="${oiY(v).toFixed(0)}" r="2.6" fill="var(--ink3)"/>`).join('') +
        ['08/28', '09/02', '09/04', '09/09', '09/16', '09/23', '09/30', '10/17'].map((d, i) =>
          T(b.cx(i), 122, d, { a: 'middle', s: 10.5, fill: 'var(--ink3)' })).join('') +
        L(b.cx(0), 128, b.cx(0), 142, { stroke: 'var(--pos)' }) +
        T(b.cx(0) + 4, 156, '這一格撐起整張圖的大半', { s: 10.5, b: 1, fill: 'var(--pos)' }) +
        T(b.cx(0) + 4, 170, '它結算完，扶著的手就鬆了', { s: 10.5, fill: 'var(--ink3)' }) +
        L(b.cx(4), 44, b.cx(4), 30, { stroke: 'var(--flip)' }) +
        T(b.cx(4), 24, '未平倉全場最多，GEX 只有第二', { a: 'middle', s: 10.5, b: 1, fill: 'var(--flip)' }) +
        T(0, 196, '▮ 各到期日 GEX　　◦┈ 各到期日未平倉', { s: 10.5, fill: 'var(--ink3)' }),
      cap: '越接近到期，每一口的 gamma 越大——<b>近月常常用比較少的口數撐出更大的曝險</b>。柱子跟點線指到不同格，就是這個現象。示意數字。',
    };
  };


  /* 手機上控制項在哪 */
  F['k-where'] = () => {
    const row = (y, k, v) => T(14, y, k, { s: 10.5, fill: 'var(--ink2)' }) +
      R(76, y - 13, 96, 19, { r: 5 }) + T(124, y, v, { a: 'middle', s: 10.5, fill: 'var(--ink)' });
    return {
      h: 222,
      body:
        T(0, 15, '手機上，常用的在外面、進階的收起來', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        R(0, 24, 186, 172, { r: 9, fill: 'var(--surface)' }) +
        row(48, '資料日期', '2026/08/26') + row(76, '到期別', '合併') +
        row(104, '顯示區間', '±10%') + row(132, '履約價分桶', '每 100 點') +
        R(14, 152, 76, 22, { r: 5 }) + T(52, 167, '更多設定 ▾', { a: 'middle', s: 10.5, fill: 'var(--ink2)' }) +
        ring(14, 152, 76, 22, null, { c: 'var(--flip)' }) +
        P('M96 163 L124 163', { stroke: 'var(--flip)', arrow: 1 }) +
        R(196, 24, 184, 172, { r: 9, fill: 'var(--surface)' }) +
        T(288, 44, '點開之後', { a: 'middle', s: 10.5, b: 1, fill: 'var(--flip)' }) +
        ['造市商假設', 'β 滑桿', '字級', '色盲友善'].map((t, i) =>
          R(212, 58 + i * 32, 152, 24, { r: 5 }) +
          T(288, 74 + i * 32, t, { a: 'middle', s: 10.5, fill: 'var(--ink)' })).join('') +
        T(190, 216, '標的說明那一塊也是先摺起來的，點一下看完整內容', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
      cap: '這兩件事都是為了<b>讓圖早一點出現在畫面上</b>——改版前手機要滑過快一個螢幕才看得到第一張圖。桌機不會收，全部攤開。',
    };
  };

  /* 資料日期：往回切幾天記四個數字 */
  F['k-date'] = () => {
    const cols = ['08/22', '08/23', '08/24', '08/25', '08/26'];
    const rows = [
      { k: '現貨', v: ['45,900', '46,100', '45,950', '46,050', '46,000'], c: 'var(--spot)', flat: 1 },
      { k: '總 GEX', v: ['+28', '+25', '+22', '+20', '+18'], c: 'var(--pos)' },
      { k: '總 VEX', v: ['−3.1', '−4.0', '−5.0', '−6.0', '−6.8'], c: 'var(--neg)' },
      { k: 'Gamma Flip', v: ['45,900', '45,500', '45,000', '44,600', '44,300'], c: 'var(--flip)' },
    ];
    let body = T(0, 15, '每天只要記這四個數字', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      cols.map((d, i) => T(84 + i * 52, 32, d, { a: 'middle', s: 10.5, fill: 'var(--ink3)' })).join('');
    rows.forEach((r, ri) => {
      const y = 52 + ri * 30;
      body += T(0, y, r.k, { s: 10.5, fill: 'var(--ink2)' });
      r.v.forEach((v, i) => { body += T(84 + i * 52, y, v, { a: 'middle', s: 10.5, fill: r.c, mono: 1 }); });
      body += T(380, y, r.flat ? '幾乎沒動' : '一路走', { a: 'end', s: 10.5, fill: r.flat ? 'var(--ink3)' : r.c });
    });
    body += R(60, 38, 276, 126, { fill: 'none', stroke: 'var(--flip)', dash: '4 3', r: 6 }) +
      T(0, 190, '現貨沒動、Flip 自己退了 1,600 點 → 是結構真的多讓出一層（B 類）',
        { s: 11.5, b: 1, fill: 'var(--flip)' }) +
      T(0, 210, '同時三個總量一起變薄 → 這面牆正在被拆', { s: 10.5, fill: 'var(--ink3)' });
    return { h: 220, body,
      cap: '這是整個網站<b>最重要的一個控制項</b>——單日數字沒有意義，斜率才有。能往回切幾天看各標的累積了多久。示意數字。' };
  };

  /* 到期別 */
  F['k-exp'] = () => {
    const mini = (x, title, v, note, col) => {
      const b = bars(x + 8, 44, 106, 46, v);
      return R(x, 26, 122, 110, { r: 7 }) +
        T(x + 61, 40, title, { a: 'middle', s: 10.5, b: 1, fill: col || 'var(--ink)' }) + b.s +
        T(x + 61, 110, note, { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        T(x + 61, 126, note === '' ? '' : '', { a: 'middle', s: 10.5 });
    };
    return {
      h: 204,
      body:
        T(0, 15, '結算日前一天做這個對照', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        mini(0, '合併', [-.5, -.9, -1.4, 1.8, 2.0, 1.1], '整體環境') +
        mini(129, '當週', [-.3, -.5, -1.0, 2.4, 2.6, .8], '今明兩天真正在起作用', 'var(--pos)') +
        mini(258, '下一期', [-.4, -.5, -.6, .5, .6, .5], '結算完接手的地形', 'var(--flip)') +
        T(190, 158, '當週跟下一期差很多 → 結算後會換一張地圖', { a: 'middle', s: 11.5, b: 1, fill: 'var(--flip)' }) +
        T(190, 178, '選了單一到期別之後，最下面那張「到期日結構拆解」', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        T(190, 194, '會把那一格框起來、其餘淡化', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
      cap: '結算週的時候，近月的 gamma 佔比會非常高，<b>合併看反而被遠月稀釋掉</b>。示意數字。',
    };
  };

  /* 顯示區間 */
  F['k-band'] = () => {
    const wide = [0, 0, .02, .05, -.4, -1.2, -2.0, 1.8, 2.2, 1.4, .3, .06, .02, 0, 0];
    const narrow = [-.4, -1.2, -2.0, 1.8, 2.2, 1.4, .3];
    const a = bars(20, 40, 340, 50, wide);
    const c = bars(20, 132, 340, 50, narrow);
    return {
      h: 216,
      body:
        T(0, 15, '±20% 常常把八九成的曝險擠在畫面中間三分之一', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        a.s + T(0, 32, '±20%', { s: 10.5, b: 1, fill: 'var(--ink3)' }) +
        R(20, 36, 100, 58, { fill: 'var(--neg)', stroke: 'none', r: 4, op: .1 }) +
        R(260, 36, 100, 58, { fill: 'var(--neg)', stroke: 'none', r: 4, op: .1 }) +
        T(70, 108, '幾乎全是零', { a: 'middle', s: 10.5, fill: 'var(--neg)' }) +
        T(310, 108, '幾乎全是零', { a: 'middle', s: 10.5, fill: 'var(--neg)' }) +
        c.s + T(0, 124, '±10%', { s: 10.5, b: 1, fill: 'var(--pos)' }) +
        T(190, 200, '所以開站時會自動挑「能涵蓋八成 |GEX| 的最窄選項」', { a: 'middle', s: 11.5, b: 1, fill: 'var(--pos)' }) +
        T(190, 214, '一般日子會落在 ±10%，曝險真的很分散的日子它會自己放寬', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
      cap: '這個選項<b>只改畫面，完全不影響任何總量</b>。日內交易切 ±5% 看價平細節，±20% 用來檢查遠端有沒有藏大部位。',
    };
  };

  /* 履約價分桶 */
  F['k-bucket'] = () => {
    const raw = [.3, 1.2, .2, 1.4, .25, 1.1, .3, 1.6, .2, 1.3, .35, .9];
    const buck = [1.5, 1.6, 1.35, 1.9, 1.5, 1.25];
    const a = bars(20, 38, 340, 46, raw, { baseline: 'bottom' });
    const c = bars(20, 118, 340, 46, buck, { baseline: 'bottom' });
    return {
      h: 222,
      body:
        T(0, 15, '台指同一天的簿子裡，50 點與 100 點的履約價是混著的', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        T(0, 32, '原始履約價', { s: 10.5, fill: 'var(--ink2)' }) + a.s +
        T(190, 100, '看起來鋸齒狀，很難判斷形狀', { a: 'middle', s: 10.5, fill: 'var(--neg)' }) +
        T(0, 112, '每 100 點', { s: 10.5, fill: 'var(--ink2)' }) + c.s +
        T(190, 180, '形狀出來了', { a: 'middle', s: 10.5, b: 1, fill: 'var(--pos)' }) +
        T(190, 196, '檔位隨標的不同：台指 100 / 200 / 500 點；', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        T(190, 212, 'SPX、ES $10 / $20 / $50；SPY、QQQ $2 / $4 / $10', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
      cap: '分桶只改畫法，不改總量。但它會改變「哪一根最高」——<b>粗分桶時，摘要卡的集中區榜單（用原始履約價算）可能跟圖上的最高柱對不起來</b>。',
    };
  };

  /* 造市商假設：當壓力測試用 */
  F['k-sign'] = () => ({
    h: 176,
    body:
      T(0, 15, '把它當壓力測試：切過去看結論會不會反過來', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      seg(0, 28, ['買權多・賣權空', '兩邊皆空'], 0, { w: 104, h: 24, s: 10.5 }) +
      tile(0, 66, 120, 56, '總 GEX', '+18.2', '正 — 壓抑波動', 'var(--pos)') +
      tile(128, 66, 120, 56, 'Gamma Flip', '45,106', '距現貨 −1.6%', 'var(--flip)') +
      P('M256 94 L286 94', { stroke: 'var(--ink3)', arrow: 1 }) +
      T(300, 80, '切到', { s: 10.5, fill: 'var(--ink3)' }) +
      T(300, 94, '兩邊皆空', { s: 10.5, b: 1, fill: 'var(--ink2)' }) +
      tile(0, 132, 120, 44, '總 GEX', '−57.8', null, 'var(--neg)') +
      tile(128, 132, 120, 44, 'Gamma Flip', '—', null, 'var(--ink3)') +
      T(258, 152, '整條曲線都在零軸下方，', { s: 10.5, fill: 'var(--ink3)' }) +
      T(258, 166, '沒有交叉點', { s: 10.5, fill: 'var(--ink3)' }),
      cap: '「—」不是算不出來，是<b>這個假設下根本沒有門檻可言</b>，全區都是放大波動的環境。如果你的結論在兩個假設下會反過來，那個結論的可信度要打折。',
  });

  /* β 滑桿 */
  F['k-beta'] = () => ({
    h: 168,
    body:
      T(0, 15, '三個位置各代表什麼', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      L(58, 44, 322, 44, { stroke: 'var(--line)', sw: 3 }) +
      [[58, '0', '完全不看波動率', 'GEX+ ＝ GEX', 'var(--ink3)'],
       [190, '1', '溫和假設（預設）', '一般日子用這個', 'var(--curve2)'],
       [322, '2', '波動率很敏感', '高波動或事件前', 'var(--flip2)']].map(([x, v, t1, t2, col]) =>
        `<circle cx="${x}" cy="44" r="7" fill="${col}"/>` +
        T(x, 30, 'β=' + v, { a: 'middle', s: 11.5, b: 1, fill: col }) +
        T(x, 70, t1, { a: 'middle', s: 10.5, fill: 'var(--ink2)' }) +
        T(x, 86, t2, { a: 'middle', s: 10.5, fill: 'var(--ink3)' })).join('') +
      T(190, 122, '從 0 拉到 2，看 GEX+ Flip 跑多遠', { a: 'middle', s: 12.5, b: 1, fill: 'var(--ink)' }) +
      T(190, 144, '跑很少 → gamma 主導，看 GEX 就夠', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
      T(190, 160, '跑很遠 → 波動率是主角，對 GEX+ Flip 的位置本身要保守', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
    cap: 'β 的意思是「標的每移動 1%，隱含波動率反向變動幾個波動點」。<b>當敏感度分析用，不要想調到「正確值」。</b>',
  });

  /* 網址 */
  F['k-url'] = () => ({
    h: 168,
    body:
      T(0, 15, '網址就是分享用的連結', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      R(0, 28, 380, 34, { r: 8 }) +
      T(14, 50, '…/twgex/', { s: 12, fill: 'var(--ink3)', mono: 1 }) +
      T(78, 50, '#QQQ', { s: 12, b: 1, fill: 'var(--pos)', mono: 1 }) +
      T(124, 50, '@20260821', { s: 12, b: 1, fill: 'var(--flip)', mono: 1 }) +
      L(98, 66, 98, 84, { stroke: 'var(--pos)' }) + T(98, 98, '標的', { a: 'middle', s: 10.5, b: 1, fill: 'var(--pos)' }) +
      L(178, 66, 178, 84, { stroke: 'var(--flip)' }) +
      T(178, 98, '資料日期（不寫就是最新）', { a: 'middle', s: 10.5, b: 1, fill: 'var(--flip)' }) +
      T(0, 130, '切標的、切日期都會自動寫進去，直接複製網址列傳給別人就好。', { s: 10.5, fill: 'var(--ink3)' }) +
      T(0, 150, '自己重新整理會停在原地；沒帶網址時，回到你上次看的標的。', { s: 10.5, fill: 'var(--ink3)' }),
    cap: '在網址列直接改也會即時生效，不用重新整理。',
  });


  /* 逐履約價資料表：驗證真牆還是影子 */
  F['t-strike'] = () => {
    const head = ['履約價', 'GEX', 'Call OI', 'Put OI', 'ΔCall', 'ΔPut'];
    const rows = [
      ['46,000', '+1.99', '180', '96', '+12', '+4', 1],
      ['46,500', '+1.96', '1,204', '388', '+0', '−22', 0],
      ['48,000', '+1.99', '2,339', '410', '+18', '+6', 2],
      ['50,000', '+1.60', '1,880', '260', '+0', '+0', 0],
    ];
    const cx = [8, 78, 148, 218, 288, 344];
    let body = T(0, 15, '把摘要卡上的履約價抄下來，到表裡查它的口數', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      R(0, 24, 380, 128, { r: 7, fill: 'var(--surface)' }) +
      head.map((h, i) => T(cx[i], 42, h, { s: 10.5, fill: 'var(--ink3)' })).join('') +
      L(0, 50, 380, 50, { stroke: 'var(--line)' });
    rows.forEach((r, ri) => {
      const y = 70 + ri * 22;
      body += r.slice(0, 6).map((v, i) =>
        T(cx[i], y, v, { s: 10.5, mono: 1, fill: i === 0 ? 'var(--ink)' : 'var(--ink2)' })).join('');
      if (ri < 3) body += L(0, y + 7, 380, y + 7, { stroke: 'var(--line)', op: .5 });
    });
    body += ring(0, 56, 380, 20, null, { c: 'var(--neg)' }) +
      ring(0, 100, 380, 20, null, { c: 'var(--pos)' }) +
      T(0, 176, 'GEX 一樣大，但 46,000 只有 180 口 → 影子牆，明天現價換位置它就換', { s: 10.5, b: 1, fill: 'var(--neg)' }) +
      T(0, 196, '48,000 有 2,339 口 → 真的牆，價格走到哪它都在原地', { s: 10.5, b: 1, fill: 'var(--pos)' });
    return { h: 206, body,
      cap: 'ΔCall / ΔPut 是跟<b>前一個有資料的交易日</b>比的增減。整排 <code>+0</code> 很正常（只是換手），某個履約價突然多出幾萬口才是有人在下注。示意數字。' };
  };

  /* 到期別明細：算集中度 */
  F['t-exp'] = () => {
    const rows = [['08-28', '週五選', '3', '21,642', '+6.98'],
                  ['09-02', '週三選', '5', '9,880', '+1.42'],
                  ['09-04', '週五選', '7', '8,120', '+1.05'],
                  ['09-16', '月選', '15', '24,900', '+1.30']];
    const cx = [8, 84, 168, 250, 344];
    let body = T(0, 15, '一個除法就看得出這張地圖的有效期限', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      R(0, 24, 380, 128, { r: 7, fill: 'var(--surface)' }) +
      ['到期別', '類型', '剩餘交易日', '未平倉', 'GEX'].map((h, i) =>
        T(cx[i], 42, h, { s: 10.5, fill: 'var(--ink3)' })).join('') +
      L(0, 50, 380, 50, { stroke: 'var(--line)' });
    rows.forEach((r, ri) => {
      const y = 70 + ri * 22;
      body += r.map((v, i) => T(cx[i], y, v, { s: 10.5, mono: 1,
        fill: i === 0 ? 'var(--ink)' : (i === 4 ? 'var(--pos)' : 'var(--ink2)') })).join('');
      if (ri < 3) body += L(0, y + 7, 380, y + 7, { stroke: 'var(--line)', op: .5 });
    });
    body += ring(0, 56, 380, 20, null, { c: 'var(--flip)' }) +
      T(0, 176, '6.98 ÷（6.98＋1.42＋1.05＋1.30）＝ 65%', { s: 11.5, b: 1, fill: 'var(--flip)', mono: 1 }) +
      T(0, 196, '超過一半 → 這張地圖在 08/28 結算之後就失效大半', { s: 10.5, fill: 'var(--ink3)' });
    return { h: 206, body,
      cap: '注意 09-16 那一列：<b>未平倉 24,900 口是全場最多，GEX 卻只有 1.30</b>——遠月每口 gamma 小，堆再多口數也撐不出厚度。示意數字。' };
  };

  /* 單位速查 */
  F['u-1'] = () => ({
    h: 176,
    body:
      T(0, 15, '「億元 / 1%」到底是什麼意思', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      R(0, 28, 380, 60, { r: 8 }) +
      T(14, 52, '總 GEX', { s: 11.5, fill: 'var(--ink2)' }) +
      T(80, 54, '+18.16', { s: 20, b: 1, fill: 'var(--pos)', mono: 1 }) +
      T(160, 52, '億元 / 1%', { s: 11.5, fill: 'var(--ink2)' }) +
      T(14, 76, '台指指數每漲跌 1%，造市商要調整 18.16 億元的部位', { s: 10.5, fill: 'var(--ink3)' }) +
      P('M60 104 L60 122', { stroke: 'var(--ink3)', arrow: 1 }) +
      T(74, 118, '漲 1%（45,833 → 46,291）→ 這群人要賣出約 18 億', { s: 10.5, fill: 'var(--ink2)' }) +
      P('M60 132 L60 150', { stroke: 'var(--ink3)', arrow: 1 }) +
      T(74, 146, '漲 2% → 約 36 億（近似值，實際會隨 gamma 變化）', { s: 10.5, fill: 'var(--ink2)' }) +
      T(0, 172, '美股同理，單位換成百萬美元。不同標的的數字不能互比。', { s: 10.5, fill: 'var(--flip)' }),
    cap: '<b>同一檔跟自己的歷史比，才有意義。</b>台指的 18 億跟 SPX 的 15,000 百萬不是同一個尺度，市值規模也差很多。',
  });

  /* 資料時點 */
  F['u-2'] = () => {
    const stop = (x, y, lbl, sub, col) =>
      `<circle cx="${x}" cy="${y}" r="6" fill="${col}"/>` +
      T(x, y - 14, lbl, { a: 'middle', s: 10.5, b: 1, fill: col }) +
      T(x, y + 22, sub, { a: 'middle', s: 10.5, fill: 'var(--ink3)' });
    return {
      h: 190,
      body:
        T(0, 15, '美股為什麼一定會慢一天', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        L(30, 60, 350, 60, { stroke: 'var(--line)', sw: 2 }) +
        stop(50, 60, '美東 16:00', '週一收盤', 'var(--ink2)') +
        stop(160, 60, '隔天 10:00~10:30', 'OCC 才發布', 'var(--flip)') +
        stop(300, 60, '台北 23:00', '本站產出', 'var(--pos)') +
        T(190, 108, '週一的價格 ＋ 週一的未平倉，一起在週二晚上出現',
          { a: 'middle', s: 12.5, b: 1, fill: 'var(--ink)' }) +
        R(0, 124, 380, 40, { r: 7, stroke: 'var(--neg)' }) +
        T(190, 142, '如果改用「即時價格 ＋ 昨天未平倉」', { a: 'middle', s: 10.5, fill: 'var(--neg)' }) +
        T(190, 157, '就會得到一張兩個時點混在一起的圖，Flip 位置會錯', { a: 'middle', s: 10.5, fill: 'var(--neg)' }) +
        T(190, 186, '台指沒有這個問題：期交所盤後一次公布，當天傍晚就完整。',
          { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
      cap: '全部都是<b>收盤快照</b>。盤中沒有任何一家（含付費服務）拿得到即時未平倉，因為交易所根本不即時公布。',
    };
  };

  /* 四種失效情況 */
  F['l-1'] = () => ({
    h: 190,
    body:
      T(0, 15, '事件的振幅大過整張地圖的寬度時', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
      L(20, 96, 360, 96, { stroke: 'var(--line)' }) +
      R(120, 70, 40, 26, { fill: 'var(--pos)', stroke: 'none', r: 3, op: .55 }) +
      R(228, 96, 40, 26, { fill: 'var(--neg)', stroke: 'none', r: 3, op: .55 }) +
      T(140, 62, '牆', { a: 'middle', s: 10.5, fill: 'var(--pos)' }) +
      T(248, 136, '坑', { a: 'middle', s: 10.5, fill: 'var(--neg)' }) +
      L(120, 58, 268, 58, { stroke: 'var(--ink3)', arrow: 2 }) +
      T(194, 52, '地圖的寬度', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
      L(40, 40, 348, 40, { stroke: 'var(--neg)', arrow: 2, sw: 1.6 }) +
      T(194, 34, '財報 / FOMC 的隱含振幅', { a: 'middle', s: 10.5, b: 1, fill: 'var(--neg)' }) +
      P('M60 96 L330 96', { stroke: 'var(--spot)', sw: 2, dash: '6 4', arrow: 1 }) +
      T(190, 164, '牆與坑不再是路障，只是里程碑——價格會直接穿過去',
        { a: 'middle', s: 11.5, b: 1, fill: 'var(--neg)' }) +
      T(190, 186, '另外三種：結算日當天與隔天、OI 覆蓋率偏低那天、盤中已經走了一大段',
        { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
    cap: '第四種最常被忽略：<b>快照停在昨天收盤，盤中走越遠越舊</b>。跌了 2% 之後，圖上寫的「距 Flip 還有 3%」實際上只剩 1%。',
  });

  /* 它唯一能做的事 */
  F['l-2'] = () => {
    const box = (x, y, w, h, t, sub, col, dashed) =>
      R(x, y, w, h, { r: 8, stroke: col, dash: dashed ? '4 3' : null,
                      fill: dashed ? 'none' : 'var(--surface2)' }) +
      T(x + w / 2, y + 24, t, { a: 'middle', s: 11.5, b: 1, fill: col }) +
      T(x + w / 2, y + 42, sub, { a: 'middle', s: 10.5, fill: 'var(--ink3)' });
    return {
      h: 190,
      body:
        T(0, 15, '方向從別的地方來，地圖只調整你怎麼下注', { s: 12.5, b: 1, fill: 'var(--ink)' }) +
        box(0, 28, 150, 58, '你的方向判斷', '技術面 / 基本面 / 消息', 'var(--ink2)', 1) +
        P('M154 57 L192 57', { stroke: 'var(--ink3)', arrow: 1 }) +
        box(196, 28, 184, 58, '曝險地圖', '這條路上路面長怎樣', 'var(--pos)') +
        P('M288 90 L288 108', { stroke: 'var(--pos)', arrow: 1 }) +
        R(96, 112, 188, 44, { r: 8, stroke: 'var(--flip)' }) +
        T(190, 132, '部位大小　與　停損寬度', { a: 'middle', s: 12, b: 1, fill: 'var(--flip)' }) +
        T(190, 148, '就這樣，沒有別的', { a: 'middle', s: 10.5, fill: 'var(--ink3)' }) +
        T(190, 178, '正 GEX 環境下的突破要打折　／　負 GEX 環境下的回檔要留餘裕',
          { a: 'middle', s: 10.5, fill: 'var(--ink3)' }),
      cap: '<b>它不產生方向，也不產生進出場點。</b>把 GEX 當進出場訊號用，等於把地形圖當導航。',
    };
  };

  /* ---------- 註冊 ------------------------------------------------------- */
  window.GUIDE_FIGS = F;
  window.GUIDE_FIG_UTILS = { W, svg, T, R, L, P, ring, bars, tile, seg, panel };
})();
