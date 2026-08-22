#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""期交所資料層 — 下載並解析 TXO 選擇權與 TX 台指期每日行情。

兩種來源，介面相同:
  fetch_csv(...)      直接連期交所（GitHub Actions runner / 你自己的電腦可用）
  read_csv_file(...)  讀已經存好的原始 CSV（離線、重跑歷史、或連不到期交所時用）

期交所 optDataDown 回傳 Big5 編碼的 CSV，欄位（0 起算）:
  0 交易日期  1 契約  2 到期月份(週別)  3 履約價  4 買賣權  5 開盤價  6 最高價
  7 最低價   8 收盤價 9 成交量        10 結算價  11 未沖銷契約數
  12 最後最佳買價 13 最後最佳賣價 14 歷史最高價 15 歷史最低價
  16 是否因訊息面暫停交易 17 交易時段 18 漲跌價 19 漲跌% 20 契約到期日

到期月份(週別) 的碼: 純六碼 = 月選；W 結尾 = 週三選；F 結尾 = 週五選。
"""
from __future__ import annotations

import datetime as dt
import urllib.parse
import urllib.request
from typing import Dict, Iterable, List, Optional, Tuple

OPT_URL = "https://www.taifex.com.tw/cht/3/optDataDown"
FUT_URL = "https://www.taifex.com.tw/cht/3/futDataDown"
UA = "Mozilla/5.0 (compatible; gexmap/1.0)"

SESSION_REGULAR = "一般"
CALL, PUT = "買權", "賣權"


# --------------------------------------------------------------------------- 取得原始 CSV

def fetch_csv(commodity_id: str, start: dt.date, end: dt.date, timeout: int = 90) -> str:
    url = OPT_URL if commodity_id == "TXO" else FUT_URL
    params = {"down_type": "1", "commodity_id": commodity_id,
              "queryStartDate": start.strftime("%Y/%m/%d"),
              "queryEndDate": end.strftime("%Y/%m/%d")}
    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(),
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("big5", errors="replace")


TWSE_INDEX = ("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
              "?date={ymd}&type=IND&response=json")


def fetch_taiex_close(day: str, timeout: int = 45) -> Optional[float]:
    """證交所發行量加權股價指數收盤（day = YYYYMMDD）。取不到就回 None。

    這是全站的參考標的價 S。選擇權的定價仍然用各到期別自己的 parity 遠期，
    現貨只負責當「情境曲線的橫軸」與 GEX 的 S^2 尺度，這樣 Gamma Flip
    講出來就直接是現貨價位，跟看盤軟體對得起來。
    """
    import json as _json
    req = urllib.request.Request(TWSE_INDEX.format(ymd=day),
                                 headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = _json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    tables = j.get("tables") or []
    rows = (tables[0].get("data") if tables else None) or j.get("data") or []
    for row in rows:
        if row and "發行量加權股價指數" in str(row[0]):
            try:
                return float(str(row[1]).replace(",", ""))
            except (ValueError, IndexError):
                return None
    return None


def read_csv_file(path: str) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("big5", errors="replace")


# --------------------------------------------------------------------------- 解析

def _num(s: str) -> Optional[float]:
    s = s.strip()
    if s in ("", "-"):
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _date(s: str) -> dt.date:
    s = s.strip().replace("-", "/")
    if "/" in s:
        y, m, d = (int(x) for x in s.split("/"))
    else:
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    return dt.date(y, m, d)


def expiry_kind(code: str) -> str:
    if code.endswith("W") or (len(code) > 6 and code[6] == "W"):
        return "週三選"
    if len(code) > 6 and code[6] == "F":
        return "週五選"
    if len(code) > 6 and code[6] == "W":
        return "週三選"
    return "月選" if code.isdigit() and len(code) == 6 else "週選"


def parse_options(csv_text: str, session: str = SESSION_REGULAR) -> Dict[str, dict]:
    """回傳 {交易日: {到期別: {"ltd": date, "kind": str, "strikes": {K: {"C"/"P": {...}}}}}}"""
    days: Dict[str, dict] = {}
    for line in csv_text.splitlines()[1:]:
        if not line.strip():
            continue
        c = [x.strip() for x in line.split(",")]
        if len(c) <= 20 or c[1] != "TXO" or c[17] != session:
            continue
        oi = _num(c[11])
        settle = _num(c[10])
        if oi is None:
            continue
        day = c[0].replace("/", "")
        exp = c[2]
        K = round(_num(c[3]) or 0.0, 4)
        cp = "C" if c[4] == CALL else ("P" if c[4] == PUT else None)
        if cp is None or K <= 0:
            continue
        blk = days.setdefault(day, {}).setdefault(
            exp, {"ltd": _date(c[20]), "kind": expiry_kind(exp), "strikes": {}})
        blk["strikes"].setdefault(K, {})[cp] = {
            "settle": settle, "close": _num(c[8]),
            "oi": int(oi), "vol": int(_num(c[9]) or 0)}
    return days


def parse_futures(csv_text: str, commodity: str = "TX",
                  session: str = SESSION_REGULAR) -> Dict[str, Dict[str, float]]:
    """回傳 {交易日: {到期月份: 收盤價}}，只取單式（六碼）月份、一般交易時段。"""
    lines = csv_text.splitlines()
    if not lines:
        return {}
    hdr = [h.strip() for h in lines[0].split(",")]
    try:
        iC, iS = hdr.index("收盤價"), hdr.index("交易時段")
    except ValueError:
        return {}
    out: Dict[str, Dict[str, float]] = {}
    for line in lines[1:]:
        c = [x.strip() for x in line.split(",")]
        if len(c) <= max(iC, iS) or c[1] != commodity:
            continue
        if not (c[2].isdigit() and len(c[2]) == 6):
            continue
        if c[iS] and c[iS] != session:
            continue
        v = _num(c[iC])
        if v is None:
            continue
        out.setdefault(c[0].replace("/", ""), {})[c[2]] = v
    return out


def latest_day(days: Dict[str, dict]) -> str:
    return max(days) if days else ""


def live_expiries(day_block: Dict[str, dict], trade_day: str) -> List[str]:
    """只留下最後交易日「嚴格晚於」當日的到期別，依到期日排序。

    當日到期的那個契約要排除: 收盤時它已經走完最後交易日，未平倉幾乎歸零，
    結算價也不再有時間價值，put-call parity 會解出離譜的遠期價
    （實測 2026/08/14 的 202608F2 解出 43,175，真實水準是 45,8xx）。
    """
    items = [(e, b["ltd"]) for e, b in day_block.items()
             if b["ltd"].strftime("%Y%m%d") > trade_day]
    return [e for e, _ in sorted(items, key=lambda t: t[1])]
