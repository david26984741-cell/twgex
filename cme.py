#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股期貨選擇權資料層 — 從 CME 公開的網站 API 取得 E-mini S&P 500（ES）整條選擇權鏈。

跟 CBOE 那一支最大的不同：CME 把同一個標的的選擇權切成很多個「商品」——
月選、EOM、以及週一到週五各自的週選（每個又分第 1~5 週），各有自己的 productId。
所以要先讀商品行事曆列出所有系列，再逐系列去要結算表。

端點（都不需要登入）：
  行事曆  /CmeWS/mvc/ProductCalendar/Options/{期貨productId}
  結算表  /CmeWS/mvc/Settlements/Options/Settlements/{選擇權productId}/OOF
          ?monthYear={系列代碼}&tradeDate=MM/DD/YYYY&strategy=DEFAULT
  成交量  /CmeWS/mvc/Volume/Options/Details
          ?productid={選擇權productId}&tradedate=YYYYMMDD&expirationcode={系列代碼}
          &reporttype=F（最終）或 P（初步）
  期貨    /CmeWS/mvc/Settlements/Futures/Settlements/{期貨productId}/FUT?tradeDate=...

**結算表的 openInterest 是前一個交易日的，不是當天的。** 當天的未平倉在成交量表的
atClose 欄位。逐檔驗證過：結算表OI + change = atClose，一口不差。價格只有結算表有，
未平倉只有成交量表是當天的，所以兩支都要打、再依 (買賣權, 履約價) 併起來。
日選差最多——2026/08/21 的 E4AQ26 結算表給 105,650，當日收盤實際是 192,119。

**同一天可能有兩個不同系列到期**：例如每月第三個星期五，月選（ES，美式）與
第三週的週五週選（EW3，歐式）會落在同一天。所以 chain 用「系列代碼」當 key，
不是用日期，否則會互相覆蓋。

**月選是美式選擇權**（optionType = AME），本專案一律用 Black-76（歐式）反解，
提前履約的價值沒有計入，深度價內會有偏差；週選 / 日選是歐式，不受影響。
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

BASE = "https://www.cmegroup.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9", "Referer": BASE + "/"}

# 期貨 productId（選擇權掛在它底下）
FUT_PRODUCT = {"ES": 133}


def _get(path: str, params: dict = None, timeout: int = 60, retries: int = 3):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:                      # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"CME 讀取失敗 {path}: {last}")


def _num(v) -> Optional[float]:
    """把結算表的字串轉成數字。'-' = 沒有；'CAB' = 最小跳動的 cabinet 價。"""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s or s == "-":
        return None
    if s.upper() == "CAB":
        return 0.05                                  # ES 選擇權的 cabinet 價
    s = s.rstrip("ABab")                              # 尾綴 B/A 是買賣價標記
    try:
        return float(s)
    except ValueError:
        return None


def _int(v) -> int:
    try:
        return int(str(v).replace(",", "").strip() or 0)
    except ValueError:
        return 0


def list_series(sym: str = "ES") -> List[dict]:
    """列出所有選擇權系列（月選 / EOM / 週一~週五週選）。"""
    cal = _get(f"/CmeWS/mvc/ProductCalendar/Options/{FUT_PRODUCT[sym]}")
    out = []
    for ty in cal:
        pids = ty.get("productIds") or ([ty["productId"]] if ty.get("productId") else [])
        for e in ty.get("calendarEntries", []):
            out.append({"code": e["productCode"], "last_trade": e["lastTrade"],
                        "option_type": ty.get("optionType"), "name": ty.get("name"),
                        "month": e.get("contractMonth", ""),
                        "american": ty.get("optionType") == "AME", "pids": list(pids)})
    return out


def _parse_last_trade(s: str) -> Optional[dt.date]:
    for f in ("%d %b %Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(s.strip(), f).date()
        except ValueError:
            pass
    return None


def kind_of(name: str, american: bool) -> str:
    if "EOM" in name:
        return "月底選"
    if "Monday" in name:    return "週一選"
    if "Tuesday" in name:   return "週二選"
    if "Wednesday" in name: return "週三選"
    if "Thursday" in name:  return "週四選"
    if "Friday" in name:    return "週五選"
    return "月選・美式" if american else "月選"


def fetch_chain(trade_day: str, sym: str = "ES", pause: float = 0.15, prev_td=None
                ) -> Tuple[Dict[str, dict], dict]:
    """trade_day: YYYYMMDD。回傳 (chain, meta)，chain 的結構與 taifex / cboe 一致。

    prev_td: 取前一個交易日的函式。季月選（optionType = AME）是在第三個星期五
    「開盤」以特別報價結算的，最後交易日實際上結束在那天早上，所以把 ltd 往前挪
    一個交易日，跟 SPX 的 AM 結算用同一套處理。
    """
    def _prev(d):
        if prev_td:
            return prev_td(d)
        x = d - dt.timedelta(days=1)
        while x.weekday() >= 5:
            x -= dt.timedelta(days=1)
        return x
    td = f"{trade_day[4:6]}/{trade_day[6:8]}/{trade_day[:4]}"
    chain: Dict[str, dict] = {}
    n_all = n_used = 0
    tried = 0
    n_merged = n_fellback = 0
    fb_oi = 0
    fb_codes = []
    rt_lock = ""
    for s in list_series(sym):
        ltd = _parse_last_trade(s["last_trade"])
        if ltd is None or ltd.strftime("%Y%m%d") <= trade_day:
            continue                                  # 已到期 / 當日到期一律排除
        rows = []
        used_pid = None
        for pid in s["pids"]:                         # 系列碼與 productId 的配對不固定，逐一試
            tried += 1
            try:
                j = _get(f"/CmeWS/mvc/Settlements/Options/Settlements/{pid}/OOF",
                         {"monthYear": s["code"], "tradeDate": td, "strategy": "DEFAULT"})
            except RuntimeError:
                continue
            r = [x for x in (j.get("settlements") or [])
                 if x.get("strike") and str(x["strike"]).lower() != "total"]
            if r:
                rows, used_pid = r, pid
                break
            time.sleep(pause)
        if not rows:
            continue
        vo = fetch_volume_oi(used_pid, s["code"], trade_day, s.get("month", ""), rt_lock)
        tried += 1
        if vo:
            vmap, rt_lock = vo[0], vo[1]
            n_merged += 1
        else:
            vmap = None
            n_fellback += 1
            fb_codes.append(s["code"])
        blk = chain.setdefault(s["code"], {
            "ltd": _prev(ltd) if s["american"] else ltd,
            "kind": kind_of(s["name"], s["american"]),
            "american": s["american"], "settle_date": ltd, "strikes": {}})
        for x in rows:
            n_all += 1
            oi = _int(x.get("openInterest"))
            K0 = _num(x.get("strike"))
            cp0 = "C" if str(x.get("type", "")).upper().startswith("C") else "P"
            if vmap is not None and K0 is not None:
                oi = vmap.get((cp0, K0), (oi, 0))[0]   # 併入當日收盤未平倉
            elif vmap is None and oi > 0:
                fb_oi += oi                            # 這一檔用的是前一日未平倉
            if oi <= 0:
                continue
            px = _num(x.get("settle"))
            if px is None or px <= 0:
                continue
            K = _num(x.get("strike"))
            cp = "C" if str(x.get("type", "")).upper().startswith("C") else "P"
            if K is None:
                continue
            blk["strikes"].setdefault(K, {})[cp] = {
                "settle": px, "close": _num(x.get("last")),
                "oi": oi, "vol": _int(x.get("volume"))}
            n_used += 1
        time.sleep(pause)

    chain = {k: v for k, v in chain.items() if v["strikes"]}
    fut = fetch_futures(trade_day, sym)
    meta = {"symbol": sym, "trade_day": trade_day, "futures": fut,
            "n_contracts_all": n_all, "n_contracts_used": n_used,
            "n_requests": tried, "spot": front_settle(fut),
            "oi_asof": "close" if n_merged else "prev",
            "oi_report": rt_lock, "oi_merged": n_merged, "oi_fellback": n_fellback,
            "oi_fellback_oi": fb_oi, "oi_fellback_codes": fb_codes}
    return chain, meta


def fetch_volume_oi(pid: int, code: str, trade_day: str, want_month: str = "",
                    report: str = "") -> Optional[Tuple[Dict[Tuple[str, float], Tuple[int, int]], str]]:
    """當日未平倉。回傳 ({(買賣權, 履約價): (atClose, change)}, 用到的報表版本)。

    report 空字串＝先試 F（最終）再試 P（初步）。月份對不上就回 None——成交量表是用
    (productId, 月份) 定位的，同一個 pid 餵不同系列碼會回到同一個月份，不擋會併錯。
    """
    for rt in ([report] if report else ["F", "P"]):
        try:
            j = _get("/CmeWS/mvc/Volume/Options/Details",
                     {"productid": pid, "tradedate": trade_day,
                      "expirationcode": code, "reporttype": rt})
        except RuntimeError:
            continue
        md = j.get("monthData") or []
        if not md:
            continue
        if want_month:
            got = " ".join(str(md[0].get("month", "")).split()).upper()
            if got and got != " ".join(want_month.split()).upper():
                return None
        out: Dict[Tuple[str, float], Tuple[int, int]] = {}
        for m in md:
            cp = "C" if "call" in str(m.get("monthID", "")).lower() else "P"
            for r in m.get("strikeData") or []:
                K = _num(r.get("strike"))
                if K is None:
                    continue
                out[(cp, K)] = (_int(r.get("atClose")), _int(r.get("change")))
        if out:
            return out, rt
    return None


def fetch_futures(trade_day: str, sym: str = "ES") -> List[dict]:
    td = f"{trade_day[4:6]}/{trade_day[6:8]}/{trade_day[:4]}"
    try:
        j = _get(f"/CmeWS/mvc/Settlements/Futures/Settlements/{FUT_PRODUCT[sym]}/FUT",
                 {"tradeDate": td, "strategy": "DEFAULT"})
    except RuntimeError:
        return []
    out = []
    for x in j.get("settlements") or []:
        m = str(x.get("month", "")).strip()
        if not m or m.lower() == "total":
            continue
        out.append({"month": m, "settle": _num(x.get("settle")),
                    "oi": _int(x.get("openInterest")), "vol": _int(x.get("volume"))})
    return out


def front_settle(fut: List[dict]) -> Optional[float]:
    """參考價用未平倉最大的那一口期貨的結算價（＝主力月）。"""
    live = [f for f in fut if f.get("settle") and f.get("oi")]
    if not live:
        live = [f for f in fut if f.get("settle")]
    if not live:
        return None
    return max(live, key=lambda f: f.get("oi") or 0)["settle"]


def live_expiries(chain: Dict[str, dict], trade_day: str):
    items = [(c, b["ltd"]) for c, b in chain.items()
             if b["ltd"].strftime("%Y%m%d") > trade_day]
    return [c for c, _ in sorted(items, key=lambda t: (t[1], t[0]))]


# --------------------------------------------------------------------------- 離線來源

def read_json_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def chain_from_dump(dump: dict, prev_td=None) -> Tuple[Dict[str, dict], dict]:
    """把離線抓好的原始結算表（瀏覽器端收集的）轉成 chain。

    dump = {"tradeDate": "MM/DD/YYYY", "oiAsOf": "close", "oiReport": "F"|"P",
            "futures": [[month, settle, oi], ...],
            "series": [{"code","name","type","lastTrade","pid","oiSrc",
                        "rows": [[strike, type, settle, oi, volume, oi_prev], ...]}]}

    rows 第 4 欄的 oi 已經是「當日收盤」的未平倉（抓的時候就從成交量表併好了）；
    第 6 欄 oi_prev 是結算表原本給的前一日值，只留著對帳用。舊格式（5 欄）也吃得下，
    那時 oi 就是前一日的，meta 的 oi_asof 會標成 prev。
    """
    def _prev(d):
        if prev_td:
            return prev_td(d)
        x = d - dt.timedelta(days=1)
        while x.weekday() >= 5:
            x -= dt.timedelta(days=1)
        return x

    td = dump.get("tradeDate") or ""
    m, d0, y = (td.split("/") + ["", "", ""])[:3]
    trade_day = f"{y}{m}{d0}" if y else ""
    chain: Dict[str, dict] = {}
    n_all = n_used = 0
    oi_tot = oi_prev_tot = 0
    fb_oi = 0
    fb_codes = []
    src = {}
    for s in dump.get("series", []):
        src[s.get("oiSrc", "settle")] = src.get(s.get("oiSrc", "settle"), 0) + 1
        ltd = _parse_last_trade(s.get("lastTrade", ""))
        if ltd is None or (trade_day and ltd.strftime("%Y%m%d") <= trade_day):
            continue
        fb = s.get("oiSrc", "settle") not in ("F", "P")
        if fb:
            fb_codes.append(s.get("code", "?"))
        american = s.get("type") == "AME"
        blk = chain.setdefault(s["code"], {
            "ltd": _prev(ltd) if american else ltd,
            "kind": kind_of(s.get("name", ""), american),
            "american": american, "settle_date": ltd, "strikes": {}})
        for r in s.get("rows", []):
            n_all += 1
            row = list(r) + [None] * 6
            K, typ, settle, oi, vol, oi_prev = row[:6]
            oi = _int(oi)
            oi_prev_tot += _int(oi_prev) if oi_prev is not None else oi
            oi_tot += oi
            if fb and oi > 0:
                fb_oi += oi
            if oi <= 0:
                continue
            px = _num(settle)
            Kf = _num(K)
            if px is None or px <= 0 or Kf is None:
                continue
            cp = "C" if str(typ).upper().startswith("C") else "P"
            blk["strikes"].setdefault(Kf, {})[cp] = {
                "settle": px, "close": None, "oi": oi, "vol": _int(vol)}
            n_used += 1
    chain = {k: v for k, v in chain.items() if v["strikes"]}
    fut = [{"month": f[0], "settle": _num(f[1]), "oi": _int(f[2])}
           for f in (dump.get("futures") or [])]
    merged = sum(n for k, n in src.items() if k in ("F", "P"))
    return chain, {"symbol": "ES", "trade_day": trade_day, "futures": fut,
                   "n_contracts_all": n_all, "n_contracts_used": n_used,
                   "spot": front_settle(fut),
                   "oi_asof": dump.get("oiAsOf") or ("close" if merged else "prev"),
                   "oi_report": dump.get("oiReport") or "",
                   "oi_merged": merged, "oi_fellback": src.get("settle", 0),
                   "oi_fellback_oi": fb_oi, "oi_fellback_codes": fb_codes,
                   "oi_total": oi_tot, "oi_prev_total": oi_prev_tot}
