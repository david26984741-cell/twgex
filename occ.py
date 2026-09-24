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
from typing import Callable, Dict, List, Optional, Tuple

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

    **欄位位置用推的，不要寫死。** 這份檔案在根碼後面塞了不只一個 tab，
    寫死成「第 2 欄是年」的話只要 OCC 改了 tab 數量就整份解析成 0 筆——
    2026/08/30 就這樣踩了一次（我另外還寫死了「第 7 欄一定是 C/P」，
    結果真實檔案的旗標不是我猜的那幾個字，整份被濾光）。
    現在改成：跳過根碼後面所有的空欄，找到第一個非空欄當「年」，其餘依序往後數：
        年 月 日 履約價整數 履約價小數(千分位) 旗標 買權未平倉 賣權未平倉
    再用「年月日與履約價必須是數字、兩個未平倉必須是數字」把整列驗一次。
    這樣不管根碼後面是一個還是兩個 tab 都讀得對，欄位真的變了也會整列跳過而不是讀錯格。

    keep 給空的就全留（含公司行為調整過的根碼）。
    """
    out: Dict[Key, int] = {}
    for ln in text.split("\n"):
        c = ln.rstrip("\r\n").split("\t")
        if len(c) < 10:
            continue
        root = c[0].strip()
        if not root or (keep and root not in keep):
            continue
        i = 1
        while i < len(c) and not c[i].strip():
            i += 1
        if i + 7 >= len(c) + 1 or i + 7 > len(c) - 1:
            continue
        y, m, d = c[i].strip(), c[i + 1].strip(), c[i + 2].strip()
        whole, dec = c[i + 3].strip(), c[i + 4].strip()
        oi_c, oi_p = c[i + 6].strip(), c[i + 7].strip()
        if not (y.isdigit() and m.isdigit() and d.isdigit() and whole.isdigit()):
            continue
        if not (oi_c.isdigit() and oi_p.isdigit()):
            continue
        if not (1900 < int(y) < 2200 and 1 <= int(m) <= 12 and 1 <= int(d) <= 31):
            continue
        exp = f"{int(y):04d}{int(m):02d}{int(d):02d}"
        k_milli = int(whole) * 1000 + (int(dec) if dec.isdigit() else 0)
        out[(root, exp, "C", k_milli)] = int(oi_c)
        out[(root, exp, "P", k_milli)] = int(oi_p)
    return out


def fetch_oi(sym: str, timeout: int = 120) -> Dict[Key, int]:
    """抓一個標的的逐序列未平倉；根碼依 ROOTS 過濾。"""
    return parse_series(fetch_series(sym, timeout=timeout), ROOTS.get(sym, (sym,)))


def fetch_daily(mdy: str, timeout: int = 60) -> str:
    """抓 daily-open-interest 的月報原文（mdy＝MM/DD/YYYY，只有月份有作用）。例外照拋。"""
    return _get(DAILY.format(mdy=mdy), timeout=timeout)


def _valid_ymd(s) -> bool:
    if not (isinstance(s, str) and len(s) == 8 and s.isdigit()):
        return False
    try:
        dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return False
    return True


def report_dates(text: str) -> Optional[List[str]]:
    """daily-open-interest 月報裡 OCC 已經發布的交易日（YYYYMMDD，由新到舊）。

    端點實況（2026/09/24 實測，研究區 QUESTIONS Q-050）：`reportDate` 只決定**月份**
    ——09/22、09/07、09/30 三個日期回傳逐位元相同的檔。內容是該月月報：
        Daily Open Interest - September 2026
        Date,Equity,,,Index/Other,,,Debt,,,Futures,OCC Total
        ,Calls,Puts,Total,Calls,Puts,Total,Calls,Puts,Total,Total,
        09/23/2026,"339,544,371",…,"631,340,212",
        09/22/2026,…
    每個已發布的交易日一列、新的在前；假日與還沒發布的日子沒有列；CRLF、行尾多一個逗號。
    所以日期欄的最大值就是 OCC 最新發布的交易日。

    第一欄＝第一個逗號前的字串（千分位的引號欄位都在它後面，不影響）。
    日期列＝第一欄是合法的 MM/DD/YYYY，而且後面至少有一個非 0 的數字。
    回傳：看得懂（有日期列、或有 Date 表頭、或有月報標題）→ list（可能是空的＝該月還沒發布任何一天）；
    看不懂（含空字串、錯誤頁）→ None。
    """
    dates = set()
    known = False
    for ln in (text or "").split("\n"):
        ln = ln.lstrip(chr(0xFEFF)).rstrip("\r").strip()
        if not ln:
            continue
        first, sep, rest = ln.partition(",")
        first = first.strip()
        if len(first) >= 2 and first[0] == '"' and first[-1] == '"':
            first = first[1:-1].strip()
        low = first.lower()
        if low == "date" or low.startswith("daily open interest"):
            known = True
            continue
        if not (len(first) == 10 and first[2] == "/" and first[5] == "/"
                and (first[:2] + first[3:5] + first[6:]).isdigit()):
            continue
        ymd = first[6:] + first[:2] + first[3:5]
        if not _valid_ymd(ymd) or not any(ch in "123456789" for ch in rest):
            continue
        dates.add(ymd)
        known = True
    if not known:
        return None
    return sorted(dates, reverse=True)


def latest_published(price_day: str, until: str,
                     fetch: Optional[Callable[[str], str]] = None) -> Tuple[Optional[str], str]:
    """OCC 最新已發布的交易日：回 (日期, 狀態)，狀態是 ok／not_yet／unknown。

    price_day ＝ 這一班價格的日期；until ＝ 美東今天（build._et_today），OCC 不會發布更晚的日子。
    先抓上界那個月的月報；那個月看得懂但一天都還沒有（月初、OCC 還沒發布本月第一天）
    才改抓上個月。抓不到或看不懂一律回 unknown、不退回上個月——那不等於「本月沒資料」，
    退回去可能把比較舊的日子當成最新。每次至多抓 2 次；不讀假日檔，日曆錯也量得對。
      最新日 > 上界        → (None, "unknown")   月報比美東今天還新＝時鐘或報表異常
      最新日 < price_day   → (最新日, "not_yet") OCC 還沒發布這一班價格那天
      其餘                → (最新日, "ok")      比 price_day 新的由呼叫端的對齊檢查擋下
    fetch 只給測試注入用（參數是 MM/01/YYYY，回傳月報文字）。
    """
    if fetch is None:
        fetch = fetch_daily
    if not (_valid_ymd(price_day) and _valid_ymd(until)):
        return None, "unknown"
    hi = max(price_day, until)

    def _month(y: int, m: int) -> Optional[List[str]]:
        try:
            txt = fetch(f"{m:02d}/01/{y:04d}")
        except Exception:                                   # noqa: BLE001
            return None
        if not isinstance(txt, str):
            return None
        return report_dates(txt)

    y, m = int(hi[:4]), int(hi[4:6])
    dates = _month(y, m)
    if dates is None:
        return None, "unknown"
    if not dates:
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        dates = _month(y, m)
        if not dates:
            return None, "unknown"
    last = max(dates)
    if last > hi:
        return None, "unknown"
    if last < price_day:
        return last, "not_yet"
    return last, "ok"


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


def format_sample(text: str, n: int = 3) -> str:
    """把回傳內容的前幾列攤開來看，tab 用 <TAB> 標出來。

    OCC 這份檔案沒有欄位標頭，欄位位置全靠觀察，出錯時第一件事就是看原始長相。
    """
    lines = [ln for ln in text.split("\n") if ln.strip()][:n]
    out = [f"回傳長度 {len(text):,} 字元、非空白列 {len([1 for ln in text.split(chr(10)) if ln.strip()]):,}"]
    for i, ln in enumerate(lines):
        cols = ln.rstrip("\r\n").split("\t")
        out.append(f"  第 {i+1} 列（{len(cols)} 欄）：" + ln.rstrip("\r\n").replace("\t", "<TAB>")[:300])
        out.append("      " + " | ".join(f"[{j}]{v.strip()!r}" for j, v in enumerate(cols[:12])))
    if not lines:
        out.append("  （沒有任何非空白列，前 300 字元：" + repr(text[:300]) + "）")
    return "\n".join(out)
