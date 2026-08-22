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
}


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


def parse_chain(payload: dict, trade_day: Optional[str] = None) -> Tuple[Dict[str, dict], dict]:
    """回傳 (chain, meta)。chain 的結構跟 taifex.parse_options 的單日區塊一致，
    可以直接餵給 engine.build_legs。

    chain = {exp_code: {"ltd": date, "kind": str, "strikes": {K: {"C"/"P": {...}}}}}
    美股選擇權的到期日就是最後交易日（SPY/QQQ 為 PM 結算，當天收盤結算）。
    """
    d = payload.get("data") or {}
    # 盤前抓取時 current_price 可能是盤前指示價，官方收盤價才是我們要的
    spot = d.get("close") or d.get("current_price") or d.get("prev_day_close")
    day = trade_day or (d.get("last_trade_time") or "")[:10].replace("-", "")

    chain: Dict[str, dict] = {}
    n_all = n_used = 0
    for o in d.get("options") or []:
        code = o.get("option") or ""
        if len(code) < 16:
            continue
        exp, cp, K = parse_osi(code)
        oi = int(o.get("open_interest") or 0)
        n_all += 1
        if oi <= 0:
            continue
        px = _mid(o.get("bid"), o.get("ask"), o.get("last_trade_price"))
        if px is None or px <= 0:
            continue
        y, m, dd = int(exp[:4]), int(exp[4:6]), int(exp[6:8])
        blk = chain.setdefault(exp, {"ltd": dt.date(y, m, dd),
                                     "kind": expiry_kind(dt.date(y, m, dd)),
                                     "strikes": {}})
        blk["strikes"].setdefault(K, {})[cp] = {
            "settle": px, "close": o.get("last_trade_price"),
            "oi": oi, "vol": int(o.get("volume") or 0)}
        n_used += 1

    meta = {"symbol": d.get("symbol"), "spot": spot, "trade_day": day,
            "quote_time": d.get("last_trade_time"), "snapshot": payload.get("timestamp"),
            "iv30": d.get("iv30"), "n_contracts_all": n_all, "n_contracts_used": n_used}
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
