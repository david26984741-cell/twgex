/* 白話版的圖：字要大、東西要少，一張圖只講一件事。
   數字有標「示意」的是舉例用，其餘取自 2026/08/26 台指實際盤後資料。 */
(function () {
  'use strict';
  const W = 420;
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const at = o => Object.entries(o).filter(([, v]) => v !== null && v !== undefined && v !== false)
    .map(([k, v]) => `${k}="${v}"`).join(' ');

  let uid = 0;
  const svg = (h, body) => {
    const n = ++uid;
    return `<svg viewBox="0 0 ${W} ${h}" role="img" preserveAspectRatio="xMidYMid meet">
      <defs><marker id="ea" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5.5" markerHeight="5.5"
        orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8 z" fill="context-stroke"/></marker></defs>
      ${body}</svg>`.split('#ea)').join(`#ea${n})`).split('id="ea"').join(`id="ea${n}"`);
  };

  const T = (x, y, s, o = {}) => `<text ${at({
    x, y, 'text-anchor': o.a || 'start', fill: o.fill || 'var(--ink2)',
    'font-size': o.s || 13, 'font-weight': o.b ? 600 : null,
  })}>${esc(s)}</text>`;
  const R = (x, y, w, h, o = {}) => `<rect ${at({
    x, y, width: Math.max(0, w), height: Math.max(0, h), rx: o.r == null ? 8 : o.r,
    fill: o.fill || 'var(--surface)', stroke: o.stroke || 'var(--line)',
    'stroke-width': o.sw || 1, 'stroke-dasharray': o.dash || null, opacity: o.op || null })}/>`;
  const L = (x1, y1, x2, y2, o = {}) => `<line ${at({
    x1, y1, x2, y2, stroke: o.stroke || 'var(--grid)', 'stroke-width': o.sw || 1.5,
    'stroke-dasharray': o.dash || null, opacity: o.op || null,
    'marker-end': o.arrow ? 'url(#ea)' : null, 'marker-start': o.arrow === 2 ? 'url(#ea)' : null })}/>`;
  const P = (d, o = {}) => `<path ${at({
    d, fill: o.fill || 'none', stroke: o.stroke || null, 'stroke-width': o.sw || 2,
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-dasharray': o.dash || null,
    opacity: o.op || null, 'marker-end': o.arrow ? 'url(#ea)' : null })}/>`;
  const C = (x, y, r, fill) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${fill}"/>`;

  const F = {};
  F.__svg = svg;

  /* 1　你買保險 → 他去避險 → 市場出現真的單子 */
  F.f1 = () => ({
    h: 168,
    body:
      [['你買一張選擇權', '＝ 跟人買保險', 'var(--ink)'],
       ['賣你的人不想賭', '＝ 馬上去避險', 'var(--curve2)'],
       ['盤面出現買賣單', '＝ 真的會推動價格', 'var(--pos)']].map(([a, b, col], i) => {
        const x = i * 146;
        return R(x, 30, 128, 74, { stroke: col }) +
          T(x + 64, 60, a, { a: 'middle', s: 13.5, b: 1, fill: col }) +
          T(x + 64, 84, b, { a: 'middle', s: 12, fill: 'var(--ink3)' }) +
          (i < 2 ? L(x + 132, 67, x + 142, 67, { stroke: 'var(--ink3)', arrow: 1 }) : '');
      }).join('') +
      T(210, 138, '指數每動 1%，這群人被迫要買賣多少錢', { a: 'middle', s: 14, b: 1, fill: 'var(--ink)' }) +
      T(210, 160, '整張圖算的就是這個數字', { a: 'middle', s: 12.5, fill: 'var(--ink3)' }),
    cap: '這些不是猜測——是<b>真的會出現在盤面上的單子</b>。所以它才會影響價格怎麼走。',
  });

  /* 2　有護欄的路 vs 結冰的下坡 */
  F.f2 = () => {
    const car = (x, y, col) => R(x - 9, y - 6, 18, 12, { fill: col, stroke: 'none', r: 3 });
    return {
      h: 232,
      body:
        R(0, 24, 204, 150, { stroke: 'var(--pos)' }) +
        T(102, 46, '有護欄的路', { a: 'middle', s: 14.5, b: 1, fill: 'var(--pos)' }) +
        L(20, 66, 184, 66, { stroke: 'var(--pos)', sw: 4 }) +
        L(20, 142, 184, 142, { stroke: 'var(--pos)', sw: 4 }) +
        P('M26 104 C56 78 74 130 104 104 C134 78 152 130 178 104',
          { stroke: 'var(--spot)', sw: 2.2, dash: '5 4' }) +
        car(178, 104, 'var(--spot)') +
        T(102, 164, '晃來晃去，但出不去', { a: 'middle', s: 12.5, fill: 'var(--ink3)' }) +
        R(216, 24, 204, 150, { stroke: 'var(--neg)' }) +
        T(318, 46, '結冰的下坡', { a: 'middle', s: 14.5, b: 1, fill: 'var(--neg)' }) +
        P('M236 72 L400 150', { stroke: 'var(--neg)', sw: 4 }) +
        P('M244 82 C268 94 288 112 312 128 C330 140 348 146 372 150',
          { stroke: 'var(--spot)', sw: 2.2, dash: '5 4' }) +
        car(374, 151, 'var(--spot)') +
        T(268, 122, '❄', { a: 'middle', s: 20, fill: 'var(--neg)', op: .6 }) +
        T(318, 164, '一滑就停不下來', { a: 'middle', s: 12.5, fill: 'var(--ink3)' }) +
        R(0, 186, 204, 40, { fill: 'var(--surface2)' }) +
        T(102, 212, '總 GEX 是「正」的', { a: 'middle', s: 13.5, b: 1, fill: 'var(--pos)' }) +
        R(216, 186, 204, 40, { fill: 'var(--surface2)' }) +
        T(318, 212, '總 GEX 是「負」的', { a: 'middle', s: 13.5, b: 1, fill: 'var(--neg)' }),
      cap: '同一個「美股大跌」的消息，<b>有護欄的日子台指可能跌 80 點就撐住；結冰的日子同一個消息可能跌 250 點還在跌</b>。差別不在消息，在路面。',
    };
  };

  /* 3　結冰線：價位帶 */
  F.f3 = () => {
    const yTop = 52, yLine = 138, yBot = 214;
    return {
      h: 252,
      body:
        R(20, yTop, 380, yLine - yTop, { fill: 'var(--pos)', stroke: 'none', r: 0, op: .08 }) +
        R(20, yLine, 380, yBot - yLine, { fill: 'var(--neg)', stroke: 'none', r: 0, op: .12 }) +
        T(30, yTop + 26, '線的上面：路是乾的', { s: 13, b: 1, fill: 'var(--pos)' }) +
        T(30, yTop + 46, '有人一路幫你踩煞車', { s: 12, fill: 'var(--ink3)' }) +
        L(20, yLine, 400, yLine, { stroke: 'var(--flip)', sw: 2.5, dash: '7 5' }) +
        T(30, yLine - 12, '結冰線　45,106　（網頁上寫 Gamma Flip）', { s: 13, b: 1, fill: 'var(--flip)' }) +
        T(30, yBot - 40, '線的下面：結冰', { s: 13, b: 1, fill: 'var(--neg)' }) +
        T(30, yBot - 20, '沒人踩煞車，還會加速', { s: 12, fill: 'var(--ink3)' }) +
        C(310, yTop + 24, 6, 'var(--spot)') +
        T(310, yTop + 8, '你現在在這　45,833', { a: 'middle', s: 13.5, b: 1, fill: 'var(--spot)' }) +
        L(310, yTop + 34, 310, yLine - 4, { stroke: 'var(--spot)', sw: 2, arrow: 1 }) +
        T(322, yTop + 62, '再跌 727 點', { s: 13, b: 1, fill: 'var(--ink)' }) +
        T(322, yTop + 80, '（−1.59%）', { s: 12, fill: 'var(--ink2)' }) +
        T(210, 240, '要看的不是那條線的數字，是「現在離它還有多遠」',
          { a: 'middle', s: 14, b: 1, fill: 'var(--ink)' }),
      cap: '2026/08/26 台指的實際數字。距離 3~4% 以上還有餘裕；<b>1~2% 以內，一根長黑就過去了</b>。',
    };
  };

  /* 4　水泥牆 vs 影子 */
  F.f4 = () => {
    const man = (x, y) => C(x, y - 16, 5.5, 'var(--ink2)') +
      P(`M${x} ${y - 10} L${x} ${y + 4} M${x - 6} ${y - 5} L${x + 6} ${y - 5} M${x} ${y + 4} L${x - 5} ${y + 14} M${x} ${y + 4} L${x + 5} ${y + 14}`,
        { stroke: 'var(--ink2)', sw: 1.8 });
    return {
      h: 248,
      body:
        R(0, 24, 196, 128, { stroke: 'var(--pos)' }) +
        T(98, 44, '水泥牆＝真的牆', { a: 'middle', s: 13.5, b: 1, fill: 'var(--pos)' }) +
        L(24, 124, 172, 124, { stroke: 'var(--line)' }) +
        R(140, 84, 24, 40, { fill: 'var(--pos)', stroke: 'none', r: 2, op: .75 }) +
        man(50, 110) + man(92, 110) +
        L(58, 98, 84, 98, { stroke: 'var(--ink3)', arrow: 1, dash: '3 3' }) +
        T(98, 144, '人走到哪，牆都在原地', { a: 'middle', s: 12, fill: 'var(--ink3)' }) +
        R(224, 24, 196, 128, { stroke: 'var(--neg)' }) +
        T(322, 44, '影子＝假的牆', { a: 'middle', s: 13.5, b: 1, fill: 'var(--neg)' }) +
        L(248, 124, 396, 124, { stroke: 'var(--line)' }) +
        man(274, 110) + R(288, 108, 22, 16, { fill: 'var(--neg)', stroke: 'none', r: 2, op: .5 }) +
        man(330, 110) + R(344, 108, 22, 16, { fill: 'var(--neg)', stroke: 'none', r: 2, op: .5 }) +
        L(282, 88, 322, 88, { stroke: 'var(--ink3)', arrow: 1, dash: '3 3' }) +
        T(322, 144, '人走到哪，它跟到哪', { a: 'middle', s: 12, fill: 'var(--ink3)' }) +
        T(210, 180, '怎麼分？看那個價位上壓了多少口單子', { a: 'middle', s: 14, b: 1, fill: 'var(--ink)' }) +
        R(0, 194, 196, 46, { fill: 'var(--surface2)' }) +
        T(98, 214, '2,339 口', { a: 'middle', s: 15, b: 1, fill: 'var(--pos)' }) +
        T(98, 232, '＝ 水泥牆', { a: 'middle', s: 12, fill: 'var(--ink3)' }) +
        R(224, 194, 196, 46, { fill: 'var(--surface2)' }) +
        T(322, 214, '180 口', { a: 'middle', s: 15, b: 1, fill: 'var(--neg)' }) +
        T(322, 232, '＝ 影子，明天就換位置', { a: 'middle', s: 12, fill: 'var(--ink3)' }),
      cap: '「貼著現價那一根」常常就是影子，它排名高只是因為離現價最近。<b>口數少的別當支撐壓力用。</b>示意口數。',
    };
  };

  /* 5　體重計 */
  F.f5 = () => {
    const days = ['8/20', '8/21', '8/24', '8/25', '8/26'];
    const kg = [75, 74, 72, 71, 70];
    const gx = [28, 25, 22, 20, 18];
    const row = (y, lbl, vals, unit, col) =>
      T(0, y, lbl, { s: 12.5, fill: 'var(--ink2)' }) +
      vals.map((v, i) => T(120 + i * 58, y, v + unit, { a: 'middle', s: 13.5, b: 1, fill: col })).join('');
    return {
      h: 190,
      body:
        T(0, 20, '只看今天：完全看不出東西', { s: 13.5, b: 1, fill: 'var(--ink)' }) +
        R(0, 30, 420, 44, { fill: 'var(--surface2)' }) +
        T(210, 58, '今天 70 公斤　／　今天總 GEX ＋18 億', { a: 'middle', s: 14, b: 1, fill: 'var(--ink3)' }) +
        T(0, 100, '看五天：話就講得出來了', { s: 13.5, b: 1, fill: 'var(--pos)' }) +
        days.map((d, i) => T(120 + i * 58, 118, d, { a: 'middle', s: 12, fill: 'var(--ink3)' })).join('') +
        row(140, '體重', kg, '', 'var(--ink2)') +
        row(164, '總 GEX', gx, '', 'var(--pos)') +
        L(112, 128, 400, 128, { stroke: 'var(--line)' }) +
        T(0, 186, '一路變薄 → 這面牆正在被拆', { s: 13.5, b: 1, fill: 'var(--flip)' }),
      cap: '網頁左上角的「資料日期」可以往回切。每天只要記四個數字：<b>現貨、總 GEX、總 VEX、Gamma Flip</b>。示意數字。',
    };
  };

  /* 6　河堤：距離一樣，來歷不同 */
  F.f6 = () => {
    const house = (x, y, col, op) =>
      P(`M${x - 13} ${y} l0 -20 l13 -11 l13 11 l0 20 z`, { stroke: col, sw: 2, op }) +
      T(x, y + 17, '你家', { a: 'middle', s: 12, fill: col, op });
    const levee = (x, y, col, op) =>
      P(`M${x - 13} ${y} l13 -26 l13 26 z`, { stroke: col, sw: 2, op }) +
      T(x, y + 17, '河堤', { a: 'middle', s: 12, fill: col, op });
    const row = (y, title, col, hOld, hNew, lOld, lNew, moveNote, moveX) =>
      R(0, y, 420, 106, { fill: 'var(--surface)' }) +
      T(14, y + 24, title, { s: 13.5, b: 1, fill: col }) +
      L(14, y + 74, 406, y + 74, { stroke: 'var(--line)', sw: 1.5 }) +
      (hOld !== hNew ? house(hOld, y + 74, 'var(--ink3)', .4) : '') +
      (lOld !== lNew ? levee(lOld, y + 74, 'var(--ink3)', .4) : '') +
      house(hNew, y + 74, 'var(--spot)') + levee(lNew, y + 74, 'var(--flip)') +
      L(lNew + 14, y + 52, hNew - 14, y + 52, { stroke: col, arrow: 2, sw: 1.5 }) +
      T((lNew + hNew) / 2, y + 46, '1,700 公尺', { a: 'middle', s: 12.5, b: 1, fill: col }) +
      (moveNote ? L(hOld === hNew ? lOld : hOld, y + 92, moveX, y + 92,
                    { stroke: 'var(--ink3)', arrow: 1, dash: '4 3' }) +
                  T((( hOld === hNew ? lOld : hOld) + moveX) / 2, y + 104, moveNote,
                    { a: 'middle', s: 11.5, fill: 'var(--ink3)' }) : '');
    return {
      h: 268,
      body:
        row(0, 'Ａ　河堤沒動，是你把房子往山上搬', 'var(--neg)', 210, 340, 100, 100, '房子搬過來', 330) +
        row(118, 'Ｂ　你沒搬家，是河堤自己往外推', 'var(--pos)', 340, 340, 210, 100, '河堤退過去', 110) +
        T(210, 258, '兩張圖的「今天」完全一樣：距離 1,700 公尺',
          { a: 'middle', s: 14, b: 1, fill: 'var(--ink)' }),
      cap: 'Ａ 的安全是<b>借來的</b>——你哪天搬回原地，河堤還在那裡等你。Ｂ 的安全是<b>真的</b>。網頁上今天只看得到「距離」這一格，兩者分不出來。',
    };
  };

  /* 7　用途 */
  F.f7 = () => ({
    h: 208,
    body:
      R(0, 24, 176, 62, { dash: '5 4', stroke: 'var(--ink3)' }) +
      T(88, 48, '你的方向判斷', { a: 'middle', s: 13.5, b: 1, fill: 'var(--ink2)' }) +
      T(88, 70, '技術面 / 基本面 / 消息', { a: 'middle', s: 11.5, fill: 'var(--ink3)' }) +
      L(182, 55, 210, 55, { stroke: 'var(--ink3)', arrow: 1 }) +
      R(216, 24, 204, 62, { stroke: 'var(--pos)' }) +
      T(318, 48, '曝險地圖', { a: 'middle', s: 13.5, b: 1, fill: 'var(--pos)' }) +
      T(318, 70, '這條路上路面長怎樣', { a: 'middle', s: 11.5, fill: 'var(--ink3)' }) +
      L(318, 92, 318, 116, { stroke: 'var(--pos)', arrow: 1 }) +
      R(112, 122, 296, 54, { stroke: 'var(--flip)' }) +
      T(260, 148, '今天下多大 ・ 停損放多寬', { a: 'middle', s: 16, b: 1, fill: 'var(--flip)' }) +
      T(260, 168, '就這樣，沒有別的用途', { a: 'middle', s: 11.5, fill: 'var(--ink3)' }) +
      T(0, 200, '它不產生方向，也不產生進出場點', { s: 13, b: 1, fill: 'var(--ink)' }),
    cap: '把 GEX 當進出場訊號用，等於<b>把路況圖當導航</b>——它從頭到尾就沒有要告訴你目的地。',
  });

  window.EASY_FIGS = F;
})();
