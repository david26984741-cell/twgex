#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股資料層 — 從 CBOE 公開延遲報價端點取得 SPY / QQQ 的完整選擇權鏈。

端點: https://cdn.cboe.com/api/global/delayed_quotes/options/{SYMBOL}.json
這是 CBOE 官網自己在用的免費延遲報價來源，一次回傳整條鏈（SPY 約 1.4 萬檔），
每檔含 bid / ask / last / open_interest / volume，以及 CBOE 自己算的 greeks。

**CBOE 的 iv 與 greeks 欄位不可信**（大量標記為 0），本專案一律自己反解、自己算。
價格用 **買賣中價**，不用最後成交價——大量履約價當天沒成交，last 是舊的。

契約代號是 OSI 格式: SPY260821C00360000
  = 標的(補空格至6碼) + 到期 YYMMDD + C/P + 履約價×1000(補零至8碼)

未平倉量的時間差: OCC 每個交易日盤後結算、隔天早上才發布，所以盤後立刻抓到的
OI 通常還是「前一個交易日」的。排程放在美東早上抓，拿到的才是最新收盤的 OI。
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.request
from typing import Dict, Optional, Tuple

URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
UA = "Mozilla/5.0 (compatible; gexmap/1.0)"

SYMBOLS = {
    "SPY": {"name": "SPY", "desc": "SPDR S&P 500 ETF", "multiplier": 100.0,
            "currency": "USD", "unit": "百萬美元", "unit_div": 1e6},
    "QQQ": {"name": "QQQ", "desc": "Invesco QQQ Trust", "multiplier": 100.0,
            "currency": "USD", "unit": "百萬美元", "unit_div": 1e6},
    "_SPX": {"name": "SPX", "desc": "S&P 500 指數選擇權", "multiplier": 100.0,
             "currency": "USD", "unit": "百萬美元", "unit_div": 1e6},
}


def osi_root(code: str) -> str:
    """OSI 代號的標的根碼（後 15 碼固定是 到期6 + C/P + 履約價8）。

    指數選擇權同一個到期日可能同時有兩種根碼，settlement 完全不同：
      SPX  = AM 結算（每月第三個星期五「開盤」結算，最後交易日是前一天）
      SPXW = PM 結算（週選 / 日選 / 月底選，當天收盤結算）
    兩者在第三個星期五會撞在同一個到期日、而且履約價大量重疊，
    不分開處理的話後讀到的那一批會把前一批整個蓋掉。
    """
    return code[:-15].strip()


def fetch_json(symbol: str, timeout: int = 120) -> dict:
    req = urllib.request.Request(URL.format(sym=symbol), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def read_json_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_osi(code: str) -> Tuple[str, str, float]:
    """SPY260821C00360000 -> ('20260821', 'C', 360.0)"""
    strike = int(code[-8:]) / 1000.0
    cp = code[-9]
    ymd = code[-15:-9]
    return "20" + ymd, cp, strike


def _mid(bid, ask, last) -> Optional[float]:
    """買賣中價；報價不合理時退回最後成交價。

    只要 ask > 0 且 ask >= bid 就用中價。bid = 0 是價外深處的正常狀態
    （買方沒掛單），此時中價 = ask/2，仍然是比 last 合理的估計。
    """
    b = bid if isinstance(bid, (int, float)) else 0.0
    a = ask if isinstance(ask, (int, float)) else 0.0
    if a > 0 and a >= b >= 0:
        return (a + b) / 2.0
    if isinstance(last, (int, float)) and last > 0:
        return float(last)
    return None


PRICE_FIELDS = ("prev_close", "mid")
# 遠期與現貨的容忍值。實測正常日 |F/S-1| 落在 0.20% 以內（QQQ 2026/08/27 是 −0.20%），
# 報價沒換日那天是 0.53%（SPY 2026/09/02）。兩者會擦邊，所以判斷**不是**單看門檻，
# 而是「兩個欄位都算一次、挑貼現貨的那個」，門檻只當最後的安全網。
FWD_TOL = 0.0035


def _px_of(o: dict, field: str) -> Optional[float]:
    """從一檔報價裡取價：field='prev_close' 用 prev_day_close，'mid' 用買賣中價。"""
    if field == "prev_close":
        v = o.get("prev_day_close")
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None
    return _mid(o.get("bid"), o.get("ask"), o.get("last_trade_price"))


def parity_forward(payload: dict, field: str, spot: float,
                   after: Optional[str] = None, n_exp: int = 3,
                   band: float = 0.02) -> Tuple[Optional[float], int]:
    """用 put-call parity 反解遠期價：F ≈ C − P + K，取價平附近履約價的中位數。

    這是一個**只由選擇權報價決定**的量，跟標的報價完全獨立，所以拿它跟現貨對照，
    就能查出「這批報價是不是跟現貨同一個場次」。折現因子在近月可忽略
    （一天期 4% 利率只有 0.01%），我們要抓的是 0.2% 以上的差距。

    after: 只看到期日「嚴格大於」這個日期的序列。已到期的序列不再更新，
      它的 prev_day_close 會永遠停在舊值，一定要排除。
    回傳 (遠期價, 用到的履約價對數)。對數太少就不可信。
    """
    if not spot or spot <= 0:
        return None, 0
    pairs: Dict[Tuple[str, str], Dict[str, Dict[str, float]]] = {}
    for o in (payload.get("data") or {}).get("options") or []:
        code = o.get("option") or ""
        if len(code) < 16:
            continue
        exp, cp, K = parse_osi(code)
        if after and exp <= after:
            continue
        if abs(K / spot - 1.0) > band:
            continue
        px = _px_of(o, field)
        if px is None:
            continue
        # 根碼一起當 key：SPX 與 SPXW 同一天到期但是兩批不同的序列，不能混著配對
        pairs.setdefault((osi_root(code), exp), {}).setdefault(str(K), {})[cp] = px
    fwds = []
    for (_root, _exp) in sorted(pairs, key=lambda t: t[1])[:n_exp]:
        for ks, cpx in pairs[(_root, _exp)].items():
            if "C" in cpx and "P" in cpx:
                fwds.append(cpx["C"] - cpx["P"] + float(ks))
    if not fwds:
        return None, 0
    fwds.sort()
    return fwds[len(fwds) // 2], len(fwds)


def pick_price_field(payload: dict, spot: float,
                     after: Optional[str] = None) -> dict:
    """決定這份檔案該用哪個價格欄位，並回報兩個欄位各自的 parity 遠期。

    **為什麼需要這一步（2026/09/02 踩到的坑）。** CBOE 這份檔案裡，
    `data.prev_day_close`（標的）在場次一結束就滾成當天收盤，
    但**每一檔選擇權自己的** `prev_day_close` 要等美東隔天早上才滾，
    而且各標的、各序列滾的時間還不一樣（2026/09/04 07:10 實測：
    SPX 與 QQQ 已經滾了、SPY 還沒）。
    於是在「美東傍晚～半夜」這段（正是台北早上九點那班）抓到的會是
    今天的現貨 ＋ 今天的未平倉 ＋ **昨天的選擇權報價**。
    原本的對齊檢查看的是標的，標的確實滾了，所以整個檢查形同虛設。

    同一份檔案裡的**買賣中價就是剛收完那個場次的收盤報價**（實測 2026/09/03 與 09/04
    連續兩天，SPY / QQQ / SPX 都成立），所以正解不是換排程，而是：
    兩個欄位都用 parity 算一次遠期，挑貼現貨的那個。這個判準在任何時點都成立——
    盤中的中價是即時價，反而會偏離「前一收盤」的現貨，那時自然就選回 prev_close。
    """
    out = {"spot": spot, "candidates": {}, "field": None, "fwd": None,
           "rel": None, "n_pairs": 0}
    best = None
    for f in PRICE_FIELDS:
        fwd, n = parity_forward(payload, f, spot, after=after)
        rel = None if (fwd is None or not spot) else fwd / spot - 1.0
        out["candidates"][f] = {"fwd": fwd, "rel": rel, "n_pairs": n}
        # 樣本太少不採信（正常一個到期別價平 ±2% 就有數十對）
        if fwd is None or n < 5:
            continue
        if best is None or abs(rel) < abs(best[2]):
            best = (f, fwd, rel, n)
    if best:
        out["field"], out["fwd"], out["rel"], out["n_pairs"] = best
    return out


def oi_as_of(payload: dict, today: str, prev_td=None) -> Optional[str]:
    """從資料本身推斷「這批未平倉量是哪一天收盤的」。

    做法: 找出已經到期、但序列上還掛著未平倉的最晚到期日 E。
    未平倉量如果已經反映 E 當天的到期處理，E 的未平倉會歸零；
    既然還在，代表這批 OI 是 E 到期之前的，也就是 E 的前一個交易日收盤。

    OCC 每個營業日早上才發布前一個營業日的未平倉量，所以盤後立刻抓會慢一天，
    這個函式就是用來把那一天標對，不要拿舊 OI 冒充今天。
    """
    d = payload.get("data") or {}
    expired = {}
    for o in d.get("options") or []:
        code = o.get("option") or ""
        if len(code) < 16:
            continue
        exp = "20" + code[-15:-9]
        if exp <= today and (o.get("open_interest") or 0) > 0:
            expired[exp] = expired.get(exp, 0) + int(o["open_interest"])
    if not expired:
        return None
    latest = max(expired)
    y, m, dd = int(latest[:4]), int(latest[4:6]), int(latest[6:8])
    e = dt.date(y, m, dd)
    if prev_td:
        return prev_td(e).strftime("%Y%m%d")
    d0 = e - dt.timedelta(days=1)
    while d0.weekday() >= 5:
        d0 -= dt.timedelta(days=1)
    return d0.strftime("%Y%m%d")


def snapshot_state(payload: dict) -> dict:
    """判斷這份檔案是「盤中／盤後抓的」還是「隔天開盤前抓的」。

    為什麼要分：檔案裡的 `prev_day_close` 是相對於**當下那一天**的前一個收盤，
    但 `last_trade_time` 要等新場次真的開始才會跳。兩者換日的時點不一樣，
    所以在「新的一天、還沒開盤」這個空窗裡：

        last_trade_time = D 16:00      → 程式會以為價格是 prev(D)
        prev_day_close  = 已經是 D 收盤 → 實際上價格是 D

    差一天。踩到的話會產出「D 的價格 ＋ D-1 的未平倉」而且標成 D-1，
    連對齊檢查都騙過去（兩個日期都是從 last_trade_time 推的，當然一致）。

    回傳 sess（last_trade_time 那天）、us_date（抓檔當下的美東日期）、
    opened（抓檔時那個場次是否已經開盤）、rolled（是否落在上述空窗）。
    """
    d = payload.get("data") or {}
    sess = (d.get("last_trade_time") or "")[:10].replace("-", "")
    stamp = payload.get("timestamp") or ""          # 'YYYY-MM-DD HH:MM:SS'，UTC
    us_date = ""
    try:
        t = dt.datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S") - dt.timedelta(hours=5)
        us_date = t.strftime("%Y%m%d")
    except (ValueError, TypeError):
        pass
    lt = (d.get("last_trade_time") or "")[11:16]     # 'HH:MM'
    opened = bool(lt) and lt >= "09:30"

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    cur = _f(d.get("current_price"))
    close = _f(d.get("close"))
    pv = _f(d.get("prev_day_close"))

    # 日曆換日：抓檔當下已經是下一個美東日期。只當輔助訊號，不單獨用來判定
    # （它會有偽陽性：跨過午夜但 prev_day_close 還沒滾的話會誤判）。
    rolled_cal = bool(sess and us_date and us_date > sess)

    # 第一關：last_trade_time 那個場次到底收了沒。
    # 盤中的 prev_day_close 本來就是前一場次的，不該被判成「已經滾過」。
    # 半日交易（早收 13:00）那幾天 lt 不會到 15:59，要靠 rolled_cal 補；
    # 台北早上那班遇到半日會跳過不產出，下午那班會補起來。
    session_over = bool(lt) and (lt >= "15:59" or rolled_cal)

    # 第二關：prev_day_close 是不是已經滾成「剛收完那個場次」的收盤。
    # **要比的是 close（官方收盤價），不是 current_price。**
    # 2026/09/01 踩到：QQQ 的 close 與 prev_day_close 都是 716.76（已經滾了），
    # 但 current_price 是 716.70——差六分錢，用 current_price 比就判成「還沒滾」，
    # 於是價格被算成前一天，跟 OCC 的未平倉對不起來，整批美股當天不產出。
    # current_price 留著當備援（有些檔案 close 可能沒填）。
    def _eq(x):
        return x is not None and pv is not None and abs(x - pv) < 1e-9
    rolled_px = session_over and (_eq(close) or _eq(cur))

    return {"sess": sess, "us_date": us_date, "last_trade_hhmm": lt,
            "opened": opened, "session_over": session_over,
            "current_price": cur, "close": close, "prev_day_close": pv,
            "rolled_px": rolled_px, "rolled_cal": rolled_cal,
            "rolled": rolled_px}


def parse_chain(payload: dict, trade_day: Optional[str] = None,
                am_roots: tuple = (), prev_td=None,
                use_prev_close: bool = False,
                price_field: Optional[str] = None,
                oi_override: Optional[dict] = None) -> Tuple[Dict[str, dict], dict]:
    """回傳 (chain, meta)。chain 的結構跟 taifex.parse_options 的單日區塊一致，
    可以直接餵給 engine.build_legs。

    chain = {exp_code: {"ltd": date, "kind": str, "strikes": {K: {"C"/"P": {...}}}}}
    SPY / QQQ 是 PM 結算，到期日就是最後交易日。

    am_roots: 哪些根碼屬於 AM 結算（例如 SPX 的 "SPX"）。這些序列會：
      1. 用 <到期日>A 當 key，跟同一天的 PM 序列分開，避免履約價互相覆蓋
      2. 最後交易日往前挪一個交易日（結算價是隔天開盤決定的）
    prev_td: 取前一個交易日的函式，沒給就退回「前一天、跳過週末」。

    use_prev_close: 用每一檔的 `prev_day_close`（前一交易日收盤價）而不是「現在的買賣中價」，
      標的價也改用 `data.prev_day_close`。

      **為什麼需要這個模式。** CBOE 這份檔案裡，價格是即時的、未平倉量卻是 OCC 隔天早上才更新的，
      兩者永遠差一個交易日：開盤前抓 → 價格對（前一日收盤）但未平倉舊一天；
      等未平倉更新（美東 10:00~10:30）→ 未平倉對了但價格已經變成當日盤中。
      **沒有任何一個時點兩者同時正確。** 改用 prev_day_close 之後，
      在「未平倉更新後、當日收盤前」這段長達五小時的窗口裡抓一次，
      價格與未平倉就都是同一個交易日的收盤，而且完全不怕排程延遲。
      實測 SPY 2026/08/26：9,913 檔有未平倉的合約全部都有 prev_day_close，一檔不漏；
      用它反解的 parity 遠期與標的前一日收盤只差 0.03~0.06%。

    oi_override: 給 {(根碼, 到期, C/P, 履約價×1000): 未平倉} 就改用它，不看檔案裡的
      open_interest。用途是把未平倉來源換成 OCC——OCC 在交易日**當天傍晚**就發布，
      CBOE 這份檔案要**隔天早上**才吃進去，平日差十幾個小時、跨週末差 2.5 天。
      查不到的合約一律當 0（等於不進圖）。價格仍然全部取自這份 CBOE 檔案，
      所以 OCC 有、CBOE 沒列的序列本來就沒有報價，算不出 IV 與 gamma，進不了圖。
    """
    def _prev(d):
        if prev_td:
            return prev_td(d)
        x = d - dt.timedelta(days=1)
        while x.weekday() >= 5:
            x -= dt.timedelta(days=1)
        return x
    d = payload.get("data") or {}
    # 兩件事要分開：
    #   use_prev_close 決定**標的價**取哪一個（收盤模式 vs 盤中即時模式）；
    #   price_field   決定**選擇權報價**取哪一個欄位（由 pick_price_field 用 parity 挑）。
    # 以前這兩件事綁在同一個布林上，正是 2026/09/02 那張拼裝圖的成因：
    # 標的滾到當天收盤了，選擇權的 prev_day_close 還停在前一天。
    field = price_field or ("prev_close" if use_prev_close else "mid")
    if use_prev_close:
        spot = d.get("prev_day_close")
    else:
        # 盤前抓取時 current_price 可能是盤前指示價，官方收盤價才是我們要的
        spot = d.get("close") or d.get("current_price") or d.get("prev_day_close")
    day = trade_day or (d.get("last_trade_time") or "")[:10].replace("-", "")

    chain: Dict[str, dict] = {}
    n_all = n_used = n_noprice = n_oi_lost = 0
    for o in d.get("options") or []:
        code = o.get("option") or ""
        if len(code) < 16:
            continue
        exp, cp, K = parse_osi(code)
        root = osi_root(code)
        if oi_override is None:
            oi = int(o.get("open_interest") or 0)
        else:
            oi = int(oi_override.get((root, exp, cp, int(code[-8:])), 0))
            if oi <= 0 and int(o.get("open_interest") or 0) > 0:
                n_oi_lost += 1
        n_all += 1
        if oi <= 0:
            continue
        px = _px_of(o, field)
        if px is None or px <= 0:
            n_noprice += 1
            continue
        y, m, dd = int(exp[:4]), int(exp[4:6]), int(exp[6:8])
        exp_date = dt.date(y, m, dd)
        am = root in am_roots
        key = exp + "A" if am else exp
        blk = chain.setdefault(key, {"ltd": _prev(exp_date) if am else exp_date,
                                     "kind": expiry_kind(exp_date) + ("・AM 結算" if am else ""),
                                     "settle_date": exp_date, "am": am,
                                     "strikes": {}})
        blk["strikes"].setdefault(K, {})[cp] = {
            "settle": px, "close": o.get("last_trade_price"),
            "oi": oi, "vol": int(o.get("volume") or 0)}
        n_used += 1

    session_day = (d.get("last_trade_time") or "")[:10].replace("-", "")
    meta = {"symbol": d.get("symbol"), "spot": spot, "trade_day": day,
            "session_day": session_day,
            "price_day": session_day,          # use_prev_close 時由呼叫端改成前一個交易日
            "price_basis": field,
            "quote_time": d.get("last_trade_time"), "snapshot": payload.get("timestamp"),
            "iv30": d.get("iv30"), "n_contracts_all": n_all, "n_contracts_used": n_used,
            "n_no_price": n_noprice,
            "oi_source": "CBOE" if oi_override is None else "OCC",
            # CBOE 檔案裡有部位、OCC 卻查不到的合約數。理應是 0
            # （2026/08/28 逐檔實測 SPX/SPY/QQQ 都是 0），不是 0 就要看一眼。
            "n_oi_lost": n_oi_lost}
    return chain, meta


def expiry_kind(d: dt.date) -> str:
    """月選 = 該月第三個星期五；其餘標成週選 / 月底選。"""
    if d.weekday() == 4:
        third_fri = [x for x in range(15, 22)
                     if dt.date(d.year, d.month, x).weekday() == 4][0]
        if d.day == third_fri:
            return "月選"
    nxt = d + dt.timedelta(days=1)
    if nxt.month != d.month:
        return "月底選"
    return "週選"


def latest_day(chain: Dict[str, dict], meta: dict) -> str:
    return meta.get("trade_day") or ""


def live_expiries(chain: Dict[str, dict], trade_day: str):
    """排除當日（含）以前到期的契約，依到期日排序。"""
    items = [(e, b["ltd"]) for e, b in chain.items()
             if b["ltd"].strftime("%Y%m%d") > trade_day]
    return [e for e, _ in sorted(items, key=lambda t: t[1])]
