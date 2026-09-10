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
# **版本號一定要寫成四段（140.0.0.0），不能寫成兩段（125.0）。**
# 2026/09/01 在紅線那台實測：同一個端點、同一組其他標頭、同一個 IP，
#   Chrome/140.0.0.0 → HTTP 200、29,065 bytes、JSON 正常
#   Chrome/125.0     → HTTP 403 Forbidden（第一個請求就被擋）
# 真實的 Chrome UA 版本號永遠是四段，Akamai 顯然拿這個當特徵之一。
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
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


def list_series(sym: str = "ES", attempts: int = 2) -> List[dict]:
    """列出所有選擇權系列（月選 / EOM / 週一~週五週選）。

    **要多問幾次取聯集，不能只問一次。**（2026/09/09~10 實測）
    CME 的邊緣節點限流時不是回錯誤碼，是回 HTTP 200 ＋ 內容殘缺。同一支行事曆
    在四分鐘之內回過 87 筆、也回過 82 筆。行事曆在一次執行裡不可能真的變動，
    少的那份就是殘的。取聯集只多花一個請求，卻讓「今天有幾個系列」這個分母
    穩定下來——後面所有比例都是拿它當基準。
    """
    out: Dict[Tuple[str, str], dict] = {}
    errs: List[str] = []
    for i in range(max(1, attempts)):
        if i:
            time.sleep(2.0)
        try:
            cal = _get(f"/CmeWS/mvc/ProductCalendar/Options/{FUT_PRODUCT[sym]}")
        except RuntimeError as e:
            errs.append(str(e))
            continue
        for ty in cal:
            pids = ty.get("productIds") or ([ty["productId"]] if ty.get("productId") else [])
            for e in ty.get("calendarEntries", []):
                key = (e["productCode"], ty.get("name") or "")
                rec = out.setdefault(key, {
                    "code": e["productCode"], "last_trade": e["lastTrade"],
                    "option_type": ty.get("optionType"), "name": ty.get("name"),
                    "month": e.get("contractMonth", ""),
                    "american": ty.get("optionType") == "AME", "pids": []})
                for p in pids:
                    if p not in rec["pids"]:
                        rec["pids"].append(p)
    if not out:
        raise RuntimeError("CME 商品行事曆一次都沒問到：" + "；".join(errs[:2]))
    return list(out.values())


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


# 補抓時每一輪之間等多久（秒）。限流退得慢，等太短沒有意義。
EMPTY_RETRY_WAITS = (20, 60, 150)
# 「昨天有、今天空手」的比例超過這個就不補抓：這種規模不是限流的樣子，
# 是這一場次的結算根本還沒發布。補抓只會白打幾百個請求，把限流養得更深。
EMPTY_RETRY_MAX_SHARE = 0.80


def fetch_chain(trade_day: str, sym: str = "ES", pause: float = 0.15, prev_td=None,
                known_live=None, retry_waits: Tuple[int, ...] = EMPTY_RETRY_WAITS
                ) -> Tuple[Dict[str, dict], dict]:
    """trade_day: YYYYMMDD。回傳 (chain, meta)，chain 的結構與 taifex / cboe 一致。

    prev_td: 取前一個交易日的函式。季月選（optionType = AME）是在第三個星期五
    「開盤」以特別報價結算的，最後交易日實際上結束在那天早上，所以把 ltd 往前挪
    一個交易日，跟 SPX 的 AM 結算用同一套處理。

    known_live: 上一個交易日那份圖裡、到今天還沒到期的系列代碼（build.py 給）。
    這些系列今天不可能真的沒有結算資料，第一遍空手而回的會被補抓，見下面的說明。
    沒有給就退回舊行為，只跑一遍。
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
    fb_codes: List[str] = []
    rt_lock = ""
    good_pid: Dict[str, int] = {}

    # 這一輪「該抓到」的系列。
    #
    # 【必須分成三種「沒拿到」，混在一起會誤判——2026/09/08 與 09/09 各踩過一次】
    #   1. 請求成功、回來沒有結算資料，而且**昨天也沒有** → 正常。CME 的產品行事曆
    #      會把還沒開始交易的系列先列出來（實測 87 個裡有 21 個是這種：2028 年的
    #      季月、2026/10~12 與 2027/10 的週選），每天都有兩成上下。
    #   2. 請求成功、回來沒有結算資料，但**昨天有** → 這是故障，而且看不出來。
    #      見下面「補抓」段落。
    #   3. 所有 pid 的請求都失敗（_get 自己重試三次仍拋出）→ 真的問不到。
    series = []
    for s in list_series(sym):
        ltd = _parse_last_trade(s["last_trade"])
        if ltd is None or ltd.strftime("%Y%m%d") <= trade_day:
            continue                                  # 已到期 / 當日到期一律排除
        series.append(dict(s, ltd=ltd))
    n_series = len(series)

    def _rows_of(s):
        """要一個系列的結算表，回傳 (結算列, 用到的 pid, 有沒有回話, 最後的錯誤)。

        **同一個 option type 底下的系列共用同一組 productIds**，所以上一個系列
        問成功的那個 pid，下一個多半也是它。把它排到最前面就不用每個系列都從頭
        試錯：2026/09/04 那一輪打了 301 個請求，可用系列只有 66 個，多出來的
        大半是試錯。請求打得越少，越不容易踩到 CME 的限流。
        """
        nonlocal tried
        rows: list = []
        used_pid = None
        got_reply = False
        last_err = None
        pids = list(s["pids"])
        g = good_pid.get(s.get("name") or "")
        if g is not None and g in pids:
            pids.remove(g)
            pids.insert(0, g)
        for pid in pids:
            tried += 1
            try:
                j = _get(f"/CmeWS/mvc/Settlements/Options/Settlements/{pid}/OOF",
                         {"monthYear": s["code"], "tradeDate": td, "strategy": "DEFAULT"})
                got_reply = True
            except RuntimeError as e:
                last_err = str(e)
                continue
            r = [x for x in (j.get("settlements") or [])
                 if x.get("strike") and str(x["strike"]).lower() != "total"]
            if r:
                rows, used_pid = r, pid
                good_pid[s.get("name") or ""] = pid
                break
            time.sleep(pause)
        return rows, used_pid, got_reply, last_err

    def _absorb(s, rows, used_pid) -> None:
        """把一個系列的結算列＋當日收盤未平倉併進 chain。"""
        nonlocal n_all, n_used, n_merged, n_fellback, fb_oi, rt_lock, tried
        vo = fetch_volume_oi(used_pid, s["code"], trade_day, s.get("month", ""), rt_lock)
        tried += 1
        if vo:
            vmap, rt_lock = vo[0], vo[1]
            n_merged += 1
        else:
            vmap = None
            n_fellback += 1
            fb_codes.append(s["code"])
        ltd = s["ltd"]
        blk = chain.setdefault(s["code"], {
            "ltd": _prev(ltd) if s["american"] else ltd,
            "kind": kind_of(s["name"], s["american"]),
            "american": s["american"], "settle_date": ltd, "strikes": {}})
        for x in rows:
            n_all += 1
            oi = _int(x.get("openInterest"))
            K = _num(x.get("strike"))
            cp = "C" if str(x.get("type", "")).upper().startswith("C") else "P"
            if vmap is not None and K is not None:
                oi = vmap.get((cp, K), (oi, 0))[0]     # 併入當日收盤未平倉
            elif vmap is None and oi > 0:
                fb_oi += oi                            # 這一檔用的是前一日未平倉
            if oi <= 0:
                continue
            px = _num(x.get("settle"))
            if px is None or px <= 0:
                continue
            if K is None:
                continue
            blk["strikes"].setdefault(K, {})[cp] = {
                "settle": px, "close": _num(x.get("last")),
                "oi": oi, "vol": _int(x.get("volume"))}
            n_used += 1

    # ── 第一遍 ──────────────────────────────────────────────────────────────
    empty_codes: List[str] = []       # 問到了、但沒有結算資料
    fail_codes: List[str] = []        # 問都問不到
    fail_errs: List[str] = []         # 失敗原因，之後查是逾時還是被擋
    pending: Dict[str, dict] = {}     # 第一遍沒拿到的系列
    for s in series:
        rows, used_pid, got_reply, last_err = _rows_of(s)
        if not rows:
            pending[s["code"]] = s
            if got_reply:
                empty_codes.append(s["code"])
            else:
                fail_codes.append(s["code"])
                if last_err and len(fail_errs) < 5:
                    fail_errs.append(f'{s["code"]}: {last_err[:160]}')
            continue
        _absorb(s, rows, used_pid)
        time.sleep(pause)

    # ── 補抓：昨天有資料、今天卻空手而回的系列 ──────────────────────────────
    # 【2026/09/09~10 的真實反例】同一個 trade_day、同一份程式碼，在紅線那台連跑
    # 六輪（兩次排程 × 三輪），「沒有結算資料」的系列數是
    #     50 → 55 → 62 → 76 → 55 → 80
    # 行事曆本身也在 87 與 82 之間跳。輸入一模一樣、結果每次都不同，就**不可能**
    # 是「CME 還沒發布」——發布是整場次一起發的，不會這一分鐘有、下一分鐘沒有。
    #
    # 這是 CME 的邊緣節點在限流：**不回錯誤碼，回 HTTP 200 ＋ 空的 settlements**，
    # 跟「這個系列還沒開始交易」在回應上長得一模一樣，靠單次回應分不出來。
    # 唯一分得出來的辦法是拿昨天那份檔當基準：昨天有部位、今天還沒到期的系列，
    # 今天不可能真的沒有結算。所以只補抓這些，其他的空就是真的空。
    #
    # 補抓要隔得夠開（20 / 60 / 150 秒）。限流退得慢，連續重打只會把它養得更深；
    # 舊版 workflow 那種「整批重跑、只隔 120 秒」正是把自己鎖死的原因。
    known = set(known_live or ())
    n_known_live = 0
    n_recovered = 0
    known_missing: List[str] = []
    if known:
        known &= {s["code"] for s in series}
        n_known_live = len(known)
        todo = [pending[c] for c in list(pending) if c in known]
        share = (len(todo) / n_known_live) if n_known_live else 0.0
        if todo and share <= EMPTY_RETRY_MAX_SHARE:
            for wait in retry_waits:
                if not todo:
                    break
                time.sleep(wait)
                still = []
                for s in todo:
                    rows, used_pid, got_reply, last_err = _rows_of(s)
                    if rows:
                        _absorb(s, rows, used_pid)
                        n_recovered += 1
                        code = s["code"]
                        if code in empty_codes:
                            empty_codes.remove(code)
                        if code in fail_codes:
                            fail_codes.remove(code)
                        pending.pop(code, None)
                    else:
                        still.append(s)
                    time.sleep(pause)
                todo = still
        known_missing = sorted(c for c in pending if c in known)

    chain = {k: v for k, v in chain.items() if v["strikes"]}
    fut = fetch_futures(trade_day, sym)
    # oi_total 一定要給。build.py 的 _cme_oi_guard 用它算「退回前一日的系列占多少」，
    # 沒有的話分母是 0、占比被當成 100%，整批就永遠被擋下來。
    # 2026/09/01 踩到：這條線路（不經 --json、直接連 CME）從來沒跑過，
    # 所以一直沒發現 chain_from_dump 有給、fetch_chain 沒給。
    oi_tot = sum(v.get("oi", 0) for b in chain.values()
                 for st in b["strikes"].values() for v in st.values())
    meta = {"symbol": sym, "trade_day": trade_day, "futures": fut,
            "n_contracts_all": n_all, "n_contracts_used": n_used,
            "n_requests": tried, "spot": front_settle(fut),
            "oi_asof": "close" if n_merged else "prev",
            "oi_report": rt_lock, "oi_merged": n_merged, "oi_fellback": n_fellback,
            "oi_fellback_oi": fb_oi, "oi_fellback_codes": fb_codes,
            "n_series": n_series, "n_series_ok": len(chain),
            "n_series_empty": len(empty_codes), "empty_codes": empty_codes[:40],
            "n_series_lost": len(fail_codes), "lost_codes": fail_codes[:40],
            "lost_errors": fail_errs,
            "n_known_live": n_known_live, "n_known_missing": len(known_missing),
            "known_missing_codes": known_missing[:40], "n_recovered": n_recovered,
            "oi_total": oi_tot}
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
