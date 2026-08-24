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
  期貨    /CmeWS/mvc/Settlements/Futures/Settlements/{期貨productId}/FUT?tradeDate=...

結算表一次就給 strike / type / settle / openInterest / volume，不必再另外要未平倉。

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
    for s in list_series(sym):
        ltd = _parse_last_trade(s["last_trade"])
        if ltd is None or ltd.strftime("%Y%m%d") <= trade_day:
            continue                                  # 已到期 / 當日到期一律排除
        rows = []
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
                rows = r
                break
            time.sleep(pause)
        if not rows:
            continue
        blk = chain.setdefault(s["code"], {
            "ltd": _prev(ltd) if s["american"] else ltd,
            "kind": kind_of(s["name"], s["american"]),
            "american": s["american"], "settle_date": ltd, "strikes": {}})
        for x in rows:
            n_all += 1
            oi = _int(x.get("openInterest"))
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
            "n_requests": tried, "spot": front_settle(fut)}
    return chain, meta


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

    dump = {"tradeDate": "MM/DD/YYYY", "futures": [[month, settle, oi], ...],
            "series": [{"code","name","type","lastTrade","pid",
                        "rows": [[strike, type, settle, openInterest, volume], ...]}]}
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
    for s in dump.get("series", []):
        ltd = _parse_last_trade(s.get("lastTrade", ""))
        if ltd is None or (trade_day and ltd.strftime("%Y%m%d") <= trade_day):
            continue
        american = s.get("type") == "AME"
        blk = chain.setdefault(s["code"], {
            "ltd": _prev(ltd) if american else ltd,
            "kind": kind_of(s.get("name", ""), american),
            "american": american, "settle_date": ltd, "strikes": {}})
        for r in s.get("rows", []):
            n_all += 1
            K, typ, settle, oi, vol = (list(r) + [None] * 5)[:5]
            oi = _int(oi)
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
    return chain, {"symbol": "ES", "trade_day": trade_day, "futures": fut,
                   "n_contracts_all": n_all, "n_contracts_used": n_used,
                   "spot": front_settle(fut)}
