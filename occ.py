#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCC 逐履約價未平倉量（美股三檔的未平倉來源）。

為什麼要有這一支
----------------
同一批未平倉量，**OCC 在交易日當天傍晚（美東約 20:00）就發布**，
CBOE 的 delayed_quotes 檔要**隔天早上（美東 10:00~10:30）**才吃進去。
平日差十幾個小時，跨週末差 2.5 天——2026/08/29(六) 實測：OCC 已經是 08/28，
CBOE 那份還停在 08/27。

改用 OCC 當未平倉來源之後：
  未平倉 ← OCC（當天傍晚就有）
  價格   ← CBOE 每一檔的 prev_day_close（場次一結束就滾成當天收盤）
兩邊在「美東當天 20:30 之後」同時都是同一個交易日，圖可以提前十幾個小時上線，
而且不需要瀏覽器——GitHub Actions 直接連得到 OCC（實測 200 / 1.8~2.6 秒）。

端點與欄位
----------
`series-search?symbolType=U&symbol=SPY`：Tab 分隔的純文字，一列一個履約價。
  0 根碼  1 空  2 年  3 月  4 日  5 履約價整數  6 履約價小數(千分位)
  7 C/P   8 買權未平倉  9 賣權未平倉  10 部位限額
**根碼後面有兩個 tab**，欄位很容易整排錯開一格（踩過一次：讀成 7/8 欄，
SPY 的數字從 311,301 變成 204）。下面用「第 7 欄必須長得像 C/P 旗標」再確認一次。

限制
----
- 沒有日期參數，只拿得到「當下」那一份，補不了歷史。
- 只有未平倉、沒有價格，價格仍要取 CBOE。
- 只結算股票／指數選擇權，**不含期貨選擇權**，救不了 ES（CME 自己結算）。
"""
from __future__ import annotations

import datetime as dt
import urllib.error
import urllib.request
from typing import Dict, Optional, Tuple

SERIES = "https://marketdata.theocc.com/series-search?symbolType=U&symbol={sym}"
DAILY = ("https://marketdata.theocc.com/daily-open-interest"
         "?reportDate={mdy}&action=download&format=csv")
UA = "Mozilla/5.0 (compatible; twgex/1.0)"

# 每個標的要留哪些根碼。開頭是數字的（2SPX、4QQQ…）是公司行為調整過的序列，
# 履約價與乘數都跟正常序列不一樣，本來就不進圖。
ROOTS = {"SPX": ("SPX", "SPXW"), "SPY": ("SPY",), "QQQ": ("QQQ",)}

# key = (根碼, 到期YYYYMMDD, 'C'/'P', 履約價×1000 的整數)
# 履約價用整數千分位當 key，不用 float：533.33 這種值在
# 533330/1000.0 與 533+330/1000.0 兩種算法下不保證是同一個 float。
Key = Tuple[str, str, str, int]


def _get(url: str, timeout: int = 120) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_series(sym: str, timeout: int = 120) -> str:
    return _get(SERIES.format(sym=sym), timeout=timeout)


def parse_series(text: str, keep: Tuple[str, ...] = ()) -> Dict[Key, int]:
    """把 series-search 的純文字解析成 {(根碼, 到期, C/P, 履約價×1000): 未平倉}。

    keep 給空的就全留（含公司行為調整過的根碼）。
    """
    out: Dict[Key, int] = {}
    for ln in text.split("\n"):
        c = ln.rstrip("\r\n").split("\t")
        if len(c) < 10:
            continue
        root = c[0].strip()
        if keep and root not in keep:
            continue
        y, m, d = c[2].strip(), c[3].strip(), c[4].strip()
        whole, dec = c[5].strip(), c[6].strip()
        flag = c[7].strip().upper()
        # 欄位錯位的防呆：第 7 欄一定是 C/P 旗標，日期與履約價一定是數字
        if not (y.isdigit() and m.isdigit() and d.isdigit() and whole.isdigit()):
            continue
        if flag not in ("C", "P", "B", ""):
            continue
        exp = f"{y}{m.zfill(2)}{d.zfill(2)}"
        k_milli = int(whole) * 1000 + (int(dec) if dec.isdigit() else 0)
        for cp, col in (("C", 8), ("P", 9)):
            v = c[col].strip()
            if v.isdigit():
                out[(root, exp, cp, k_milli)] = int(v)
    return out


def fetch_oi(sym: str, timeout: int = 120) -> Dict[Key, int]:
    """抓一個標的的逐序列未平倉；根碼依 ROOTS 過濾。"""
    return parse_series(fetch_series(sym, timeout=timeout), ROOTS.get(sym, (sym,)))


def published_for(day: str, timeout: int = 60) -> Optional[bool]:
    """OCC 有沒有已經發布 `day`（YYYYMMDD）的未平倉？

    用 daily-open-interest 那支（只有全市場總量、22 列，很輕）當日期探針。
    回 True / False；連不到或格式看不懂就回 None（呼叫端改用別的判斷）。
    """
    try:
        y, m, d = int(day[:4]), int(day[4:6]), int(day[6:8])
        mdy = f"{m:02d}/{d:02d}/{y:04d}"
    except (ValueError, IndexError, TypeError):
        return None
    try:
        txt = _get(DAILY.format(mdy=mdy), timeout=timeout)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return None
    body = txt.strip()
    if not body:
        return False
    # 有資料時是一份 CSV，列數不多但一定有數字；沒發布時 OCC 回的是空的或只有表頭
    rows = [ln for ln in body.split("\n") if ln.strip()]
    if len(rows) < 2:
        return False
    digits = sum(ch.isdigit() for ln in rows[1:] for ch in ln)
    return digits > 0


def same_numbers(occ: Dict[Key, int], cbo: Dict[Key, int]) -> bool:
    """OCC 與 CBOE 的未平倉在重疊的合約上完全一樣嗎？

    一樣 → OCC 還沒往前走，它跟 CBOE 是同一個交易日的（**危險**：
    代表現在落在「美東當天收盤後、OCC 還沒發布」那 4 小時空窗裡）。
    不一樣 → OCC 比 CBOE 新一個發布週期。
    """
    both = [k for k in occ if k in cbo]
    if not both:
        return False
    return all(occ[k] == cbo[k] for k in both)


def cboe_oi_map(payload: dict) -> Dict[Key, int]:
    """把 CBOE 那份檔案的未平倉攤成跟 OCC 同樣的 key，方便逐檔比對。"""
    import cboe
    out: Dict[Key, int] = {}
    for o in (payload.get("data") or {}).get("options") or []:
        code = o.get("option") or ""
        if len(code) < 16:
            continue
        out[(cboe.osi_root(code), "20" + code[-15:-9], code[-9],
             int(code[-8:]))] = int(o.get("open_interest") or 0)
    return out


def next_trading_day(day: str, holidays) -> str:
    d = dt.date(int(day[:4]), int(day[4:6]), int(day[6:8])) + dt.timedelta(days=1)
    while d.weekday() >= 5 or d in holidays:
        d += dt.timedelta(days=1)
    return d.strftime("%Y%m%d")
