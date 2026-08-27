#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""不變量自我測試。純標準庫，不需要網路，也不需要任何資料檔。

  python selftest.py                 只跑數學層
  python selftest.py --csv raw/x.csv 連資料層一起跑（多幾項一致性檢查）

CI 會跑這支；改動 engine.py 之後請先跑過。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import random
import sys

import engine

FAILS = []



def _guard_ok(args, meta) -> bool:
    """把 build 的未平倉守門包成 True/False，方便測。"""
    import build
    try:
        build._cme_oi_guard(args, meta)
        return True
    except SystemExit:
        return False

def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(name)


def math_tests():
    print("數學層")
    rnd = random.Random(20260820)

    # 1. put-call parity
    worst = 0.0
    for _ in range(2000):
        F = rnd.uniform(25000, 60000); K = F * rnd.uniform(0.7, 1.4)
        T = rnd.uniform(0.004, 0.7); s = rnd.uniform(0.08, 0.9)
        d = abs((engine.bs76(F, K, T, s, "C") - engine.bs76(F, K, T, s, "P")) - (F - K))
        worst = max(worst, d / F)
    check("put-call parity", worst < 1e-12, f"最大相對誤差 {worst:.2e}")

    # 2. IV 反解往返（含深度價內——純割線法會在這裡爆掉）
    bad, worst = 0, 0.0
    for _ in range(4000):
        F = rnd.uniform(25000, 60000); K = F * rnd.uniform(0.6, 1.6)
        T = rnd.uniform(0.002, 0.8); s = rnd.uniform(0.05, 1.2); cp = rnd.choice("CP")
        iv = engine.implied_vol(engine.bs76(F, K, T, s, cp), F, K, T, cp)
        if iv is None:
            continue
        worst = max(worst, abs(iv - s))
        bad += abs(iv - s) > 1e-5
    check("IV 反解往返", bad == 0, f"4000 組，最大誤差 {worst:.2e}")

    # 3. 迴歸：實際踩過的坑（2026/08/20 的 43200 買權，割線法會解出 258%）
    iv = engine.implied_vol(1640.0, 44837.5, 43200, 0.00794, "C")
    check("深度價內不再解出假高波動", iv is not None and 0.10 < iv < 0.30,
          f"IV = {iv * 100:.2f}%" if iv else "None")

    # 4. Greeks vs 數值微分（雙精度可靠的區間）
    worst = {"gamma": 0.0, "vega": 0.0, "vanna": 0.0}
    for _ in range(1500):
        F = rnd.uniform(35000, 55000); K = F * rnd.uniform(0.92, 1.08)
        T = rnd.uniform(0.02, 0.5); s = rnd.uniform(0.12, 0.5); cp = rnd.choice("CP")
        g = engine.greeks76(F, K, T, s)
        hF, hs = F * 1e-4, s * 1e-4
        px = engine.bs76(F, K, T, s, cp)
        ng = (engine.bs76(F + hF, K, T, s, cp) - 2 * px + engine.bs76(F - hF, K, T, s, cp)) / hF ** 2
        nv = (engine.bs76(F, K, T, s + hs, cp) - engine.bs76(F, K, T, s - hs, cp)) / (2 * hs)
        nw = ((engine.bs76(F + hF, K, T, s + hs, cp) - engine.bs76(F - hF, K, T, s + hs, cp))
              - (engine.bs76(F + hF, K, T, s - hs, cp) - engine.bs76(F - hF, K, T, s - hs, cp))) / (4 * hF * hs)
        for k, a, b in (("gamma", g["gamma"], ng), ("vega", g["vega"], nv), ("vanna", g["vanna"], nw)):
            worst[k] = max(worst[k], abs(a - b) / abs(b))
    for k, v in worst.items():
        check(f"{k} 對數值微分", v < 2e-3, f"最大相對誤差 {v:.2e}")

    # 5. 交易日計數
    hol = engine.load_holidays("calendar_tw.txt")
    n = engine.trading_days_between(dt.date(2026, 8, 20), dt.date(2026, 8, 26), hol)
    check("交易日計數（8/20→8/26 應為 4）", n == 4, f"得到 {n}")


def data_tests(csv_path, date=None):
    import taifex
    print("資料層")
    days = taifex.parse_options(taifex.read_csv_file(csv_path))
    day = date or taifex.latest_day(days)
    blk = days[day]
    live = taifex.live_expiries(blk, day)
    check("當日到期的契約已被排除", all(blk[e]["ltd"].strftime("%Y%m%d") > day for e in live))

    td = dt.date(int(day[:4]), int(day[4:6]), int(day[6:8]))
    legs, diag = engine.build_legs({e: blk[e] for e in live}, td, engine.load_holidays("calendar_tw.txt"))
    check("有解出部位", len(legs) > 0, f"{len(legs)} 條腿")

    dropped = sum(d.get("oi_dropped", 0) for d in diag.values())
    used = sum(d.get("oi_used", 0) for d in diag.values())
    check("反解失敗的未平倉佔比 < 1%", dropped <= used * 0.01, f"丟棄 {dropped} / 使用 {used}")

    # 遠期價的持有成本結構：只在「到期相隔夠遠」的配對上檢查。
    # 相鄰兩個近月（例如週三選與週五選只差 2 個交易日）真實價差只有幾點，
    # 會被 parity 反解的雜訊（±30~40 點）蓋過去，比較它們沒有意義。
    fw = {e: diag[e]["F"] for e in live if diag[e].get("F")}
    seq = [(diag[e]["trading_days"], fw[e], e) for e in live if e in fw]
    bad = [(a, b) for i, a in enumerate(seq) for b in seq[i + 1:]
           if b[0] - a[0] >= 10 and b[1] < a[1] - 30]
    check("遠期價隨到期遞增（相隔 >=10 交易日的配對）", not bad,
          " → ".join(f"{v:.0f}" for _, v, _ in seq) if not bad
          else "逆序: " + "; ".join(f"{a[2]}({a[1]:.0f}) > {b[2]}({b[1]:.0f})" for a, b in bad))

    atm = []
    for e in live:
        if e not in fw:
            continue
        near = sorted([l for l in legs if l.exp == e], key=lambda l: abs(l.K / fw[e] - 1))[:6]
        if near:
            atm.append(sum(l.iv for l in near) / len(near))
    check("ATM 隱含波動率期限結構單調",
          all(b >= a - 0.01 for a, b in zip(atm, atm[1:])),
          " → ".join(f"{v * 100:.1f}%" for v in atm))

    same = [(l.gamma, l.vega) for l in legs]
    byk = {}
    for l in legs:
        byk.setdefault((l.exp, l.K), {})[l.cp] = (l.gamma, l.vega)
    pairs = [v for v in byk.values() if len(v) == 2]
    check("同履約價買賣權共用 greeks", all(v["C"] == v["P"] for v in pairs), f"{len(pairs)} 組")

    slopes = {e: engine.skew_slope(legs, e, fw[e]) for e in fw}
    check("偏斜斜率為負（股價指數的正常型態）",
          all(s <= 0.02 for s in slopes.values()),
          " ".join(f"{v:.2f}" for v in slopes.values()))

    S0 = fw[live[0]]
    rows = engine.exposure_by_strike(legs, S0, "long_call_short_put")
    barg = sum(r["gex"] for r in rows)
    barv = sum(r["vex"] for r in rows)
    xs, g, v, gp = engine.profile_curve(legs, S0, fw, "long_call_short_put", 1.0, -0.001, 0.001, 3)
    check("情境曲線在 S_ref 等於長條圖總和（GEX）",
          abs(g[1] - barg) < max(abs(barg), 1) * 1e-9, f"差 {abs(g[1] - barg):.3e} 元")
    check("情境曲線在 S_ref 等於長條圖總和（VEX）",
          abs(v[1] - barv) < max(abs(barv), 1) * 1e-9, f"差 {abs(v[1] - barv):.3e} 元")

    xs, g, v, gp0 = engine.profile_curve(legs, S0, fw, "long_call_short_put", 0.0, -0.08, 0.08, 81)
    check("β=0 時 GEX+ 等於 GEX", all(abs(a - b) < 1e-6 for a, b in zip(g, gp0)))
    xs, g, v, gp1 = engine.profile_curve(legs, S0, fw, "long_call_short_put", 1.0, -0.08, 0.08, 81)
    check("GEX+ = GEX + β×VEX",
          all(abs(a + b - c) < 1e-6 for a, b, c in zip(g, v, gp1)))

    # VEX 用 vanna: 價平兩側應該同號、價平附近趨近於零（vega 版做不到這件事）
    near = [r for r in rows if abs(r["K"] / S0 - 1) < 0.10]
    lo_side = [r["vex"] for r in near if r["K"] < S0 * 0.97]
    hi_side = [r["vex"] for r in near if r["K"] > S0 * 1.03]
    same = (sum(1 for x in lo_side if x < 0) / max(len(lo_side), 1) > 0.8 and
            sum(1 for x in hi_side if x < 0) / max(len(hi_side), 1) > 0.8)
    check("VEX 在價平兩側同號（vanna 的特徵）", same,
          f"下方 {sum(1 for x in lo_side if x<0)}/{len(lo_side)} 負、"
          f"上方 {sum(1 for x in hi_side if x<0)}/{len(hi_side)} 負")


def chain_tests():
    """指數選擇權的 AM / PM 結算分流（SPX 有 SPX 與 SPXW 兩種根碼）。"""
    import cboe
    hol = engine.load_holidays(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calendar_us.txt"))
    prev = lambda d: engine.prev_trading_day(d, hol)
    o = lambda code, oi: {"option": code, "bid": 1.0, "ask": 1.2,
                          "last_trade_price": 1.1, "open_interest": oi, "volume": 10}
    payload = {"data": {"symbol": "^SPX", "close": 7674.37,
                        "last_trade_time": "2026-08-21T16:15:00",
                        "options": [
                            o("SPX260918C07600000", 1111),      # AM 結算
                            o("SPXW260918C07600000", 2222),     # 同一天的 PM 結算
                            o("SPX   260918P07600000", 3333),   # 補空白的根碼也要認得
                            o("SPXW260918P07600000", 4444),
                            o("SPXW260824C07700000", 555),
                            o("SPXW260824P07700000", 666)]}}
    chain, _ = cboe.parse_chain(payload, "20260821", am_roots=("SPX",), prev_td=prev)
    check("AM / PM 結算分成不同到期別 key", set(chain) == {"20260918A", "20260918", "20260824"},
          str(sorted(chain)))
    check("AM 結算的最後交易日往前挪一個交易日",
          chain.get("20260918A", {}).get("ltd") == dt.date(2026, 9, 17)
          and chain.get("20260918", {}).get("ltd") == dt.date(2026, 9, 18),
          "AM 2026-09-17 / PM 2026-09-18")
    tot = sum(r["oi"] for b in chain.values() for st in b["strikes"].values() for r in st.values())
    check("同一到期日的 AM / PM 履約價不互相覆蓋", tot == 1111 + 2222 + 3333 + 4444 + 555 + 666,
          f"未平倉總量 {tot}")
    plain, _ = cboe.parse_chain(payload, "20260821")
    # --- 價格改用前一交易日收盤（美股的預設做法）---
    pay2 = {"timestamp": "2026-08-26 14:34:16", "data": {
        "symbol": "SPY", "close": 765.07, "current_price": 765.07,
        "prev_day_close": 765.91, "last_trade_time": "2026-08-26T10:30:15",
        "options": [
            # 有 prev_day_close：要用它，不能用買賣中價
            {"option": "SPY   260828C00760000", "bid": 9.0, "ask": 9.2,
             "prev_day_close": 8.40, "open_interest": 100, "volume": 3},
            {"option": "SPY   260828P00760000", "bid": 3.0, "ask": 3.2,
             "prev_day_close": 3.55, "open_interest": 200, "volume": 4},
            # 有未平倉但沒有前一日收盤：要被跳過並計數，不可以偷偷改用中價
            {"option": "SPY   260828C00990000", "bid": 0.01, "ask": 0.02,
             "prev_day_close": None, "open_interest": 50, "volume": 0},
        ]}}
    c2, m2 = cboe.parse_chain(pay2, "20260825", prev_td=prev, use_prev_close=True)
    st = c2["20260828"]["strikes"][760.0]
    check("美股價格取每一檔的前一交易日收盤",
          st["C"]["settle"] == 8.40 and st["P"]["settle"] == 3.55,
          f"買權 {st['C']['settle']} / 賣權 {st['P']['settle']}（中價會是 9.1 / 3.1）")
    check("標的價取前一交易日收盤", m2["spot"] == 765.91, str(m2["spot"]))
    check("沒有前一日收盤的合約被跳過並計數",
          990.0 not in c2["20260828"]["strikes"] and m2["n_no_price"] == 1,
          f"跳過 {m2['n_no_price']} 筆")
    check("記錄了抓檔當下的場次日", m2["session_day"] == "20260826", m2["session_day"])
    check("價格基準有標記", m2["price_basis"] == "prev_close", m2["price_basis"])
    c3, m3 = cboe.parse_chain(pay2, "20260826", prev_td=prev, use_prev_close=False)
    st3 = c3["20260828"]["strikes"][760.0]
    check("關掉之後仍是原本的買賣中價",
          abs(st3["C"]["settle"] - 9.1) < 1e-9 and m3["spot"] == 765.07,
          f"買權 {st3['C']['settle']} / 標的 {m3['spot']}")

    # --- 未平倉日期的反推要看假日表 ---
    pay3 = {"data": {"options": [
        {"option": "SPY   260826C00760000", "open_interest": 1000},
        {"option": "SPY   260825C00760000", "open_interest": 0}]}}
    check("未平倉日期反推：用假日表往前一個交易日",
          cboe.oi_as_of(pay3, "20260826", prev_td=prev) == "20260825",
          str(cboe.oi_as_of(pay3, "20260826", prev_td=prev)))

    check("沒給 am_roots 時維持 SPY / QQQ 的原本行為",
          set(plain) == {"20260918", "20260824"}, str(sorted(plain)))


def cme_tests():
    """CME 結算表的解析：價格字串、季月選（美式）的最後交易日往前挪、同日不同系列不互蓋。"""
    import cme
    hol = engine.load_holidays(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calendar_us.txt"))
    prev = lambda d: engine.prev_trading_day(d, hol)
    check("結算價字串解析", [cme._num(x) for x in ["7591.25", "1,234.50", "CAB", "-", "", "123.00B", None]]
          == [7591.25, 1234.50, 0.05, None, None, 123.00, None], "含千分位 / CAB / 買賣價尾綴")
    dump = {"tradeDate": "08/21/2026", "futures": [["SEP 26", "7691.25", "2,019,214"]],
            "series": [
                # 第三個星期五：季月選（美式）與第三週的週五週選同一天到期
                {"code": "ESU26", "name": "E-mini S&P 500 Options", "type": "AME",
                 "lastTrade": "18 Sep 2026",
                 "rows": [["7600.00", "Call", "250.00", "1,111", "10"],
                          ["7600.00", "Put", "180.00", "2,222", "5"]]},
                {"code": "EW3U26", "name": "E-mini S&P 500 Friday Weekly Options", "type": "E21",
                 "lastTrade": "18 Sep 2026",
                 "rows": [["7600.00", "Call", "249.00", "3,333", "8"],
                          ["7600.00", "Put", "179.00", "4,444", "3"]]},
                # 已到期的要被丟掉
                {"code": "EW3Q26", "name": "E-mini S&P 500 Friday Weekly Options", "type": "E21",
                 "lastTrade": "21 Aug 2026",
                 "rows": [["7600.00", "Call", "1.00", "9,999", "0"]]}]}
    chain, meta = cme.chain_from_dump(dump, prev_td=prev)
    check("同一天到期的不同系列各自成一格", set(chain) == {"ESU26", "EW3U26"}, str(sorted(chain)))
    check("季月選（美式）最後交易日往前挪一個交易日",
          chain.get("ESU26", {}).get("ltd") == dt.date(2026, 9, 17)
          and chain.get("EW3U26", {}).get("ltd") == dt.date(2026, 9, 18),
          "ESU26 2026-09-17 / EW3U26 2026-09-18")
    tot = sum(r["oi"] for b in chain.values() for st in b["strikes"].values() for r in st.values())
    check("履約價不互相覆蓋、已到期系列被排除", tot == 1111 + 2222 + 3333 + 4444, f"未平倉 {tot}")
    check("參考價取未平倉最大的期貨結算價", meta["spot"] == 7691.25, str(meta["spot"]))
    check("舊格式（5 欄）仍讀得動，未平倉標成前一日", meta["oi_asof"] == "prev", meta["oi_asof"])

    # --- 當日未平倉：6 欄格式 ---
    dump2 = {"tradeDate": "08/21/2026", "oiAsOf": "close", "oiReport": "P",
             "futures": [["SEP 26", "7691.25", "2,019,214"]],
             "series": [
                 {"code": "E4AQ26", "name": "E-mini S&P 500 Monday Weekly Options",
                  "type": "MW1", "lastTrade": "24 Aug 2026", "oiSrc": "P",
                  "rows": [["7600.00", "Call", "20.00", "1,500", "10", "1,000"],
                           ["7600.00", "Put", "18.00", "2,500", "5", "2,000"],
                           # 成交量表沒列到、結算表未平倉 0 的檔位要被丟掉
                           ["1000.00", "Put", "0.05", "0", "0", "0"]]}]}
    c2, m2 = cme.chain_from_dump(dump2, prev_td=prev)
    tot2 = sum(r["oi"] for b in c2.values() for st in b["strikes"].values() for r in st.values())
    check("6 欄格式取當日未平倉", tot2 == 4000, f"未平倉 {tot2}（前一日是 3000）")
    check("未平倉標記為當日收盤",
          m2["oi_asof"] == "close" and m2["oi_report"] == "P" and m2["oi_merged"] == 1,
          f"{m2['oi_asof']} / {m2['oi_report']} / 合併 {m2['oi_merged']}")
    check("前一日未平倉合計仍留著可對帳",
          m2["oi_total"] == 4000 and m2["oi_prev_total"] == 3000,
          f"當日 {m2['oi_total']} / 前一日 {m2['oi_prev_total']}")
    check("未平倉 0 的檔位不進圖", 7600.0 in c2["E4AQ26"]["strikes"] and 1000.0 not in c2["E4AQ26"]["strikes"],
          str(sorted(c2["E4AQ26"]["strikes"])))

    # --- CBOE：prev_day_close 與 last_trade_time 換日時點不同 ---
    import cboe as _cboe
    snap = lambda ts, lt: _cboe.snapshot_state({"timestamp": ts, "data": {"last_trade_time": lt}})
    a = snap("2026-08-26 20:10:00", "2026-08-26T16:00:00")
    check("收盤後當天抓：沒有換日問題",
          a["sess"] == "20260826" and a["us_date"] == "20260826" and not a["rolled"], str(a))
    b = snap("2026-08-27 05:45:07", "2026-08-26T16:00:00")
    check("隔天開盤前抓：認得出 prev_day_close 已經滾到新的一天",
          b["sess"] == "20260826" and b["us_date"] == "20260827" and b["rolled"],
          "這就是 2026-08-27 07:55 那次把 08/26 的價格標成 08/25 的成因")
    c = snap("2026-08-27 15:05:00", "2026-08-27T11:05:00")
    check("開盤後抓（設計的時點）：一切對齊", not c["rolled"], str(c))
    d = snap("", "")
    check("欄位缺漏時不會炸、也不會誤判成換日", d["rolled"] is False, str(d))

    # --- 抓太早：成交量表還沒發布 ---
    class _A:
        allow_stale_oi = False

    dump3 = {"tradeDate": "08/21/2026", "oiAsOf": "close", "oiReport": "P",
             "futures": [["SEP 26", "7691.25", "2,019,214"]],
             "series": [
                 {"code": "E4AQ26", "name": "E-mini S&P 500 Monday Weekly Options",
                  "type": "MW1", "lastTrade": "24 Aug 2026", "oiSrc": "P",
                  "rows": [["7600.00", "Call", "20.00", "99,000", "10", "98,000"]]},
                 {"code": "EW3U26", "name": "E-mini S&P 500 Weekly Options",
                  "type": "EOW", "lastTrade": "18 Sep 2026", "oiSrc": "settle",
                  "rows": [["7600.00", "Put", "18.00", "500", "5", "500"]]}]}
    c3, m3 = cme.chain_from_dump(dump3, prev_td=prev)
    check("退回前一日的系列有被記下來",
          m3["oi_fellback_codes"] == ["EW3U26"] and m3["oi_fellback_oi"] == 500,
          f"{m3['oi_fellback_codes']} / {m3['oi_fellback_oi']} 口")
    check("退回的量很小時照樣產出",
          _guard_ok(_A(), m3), "500 / 99500 = 0.50%")

    m4 = dict(m3, oi_fellback_oi=50000)
    check("退回的量占比過大時擋下來", not _guard_ok(_A(), m4), "50000 / 99500 = 50%")
    m5 = dict(m3, oi_asof="prev")
    check("整批退回一定擋下來", not _guard_ok(_A(), m5), "oi_asof=prev")

    class _B:
        allow_stale_oi = True
    check("加了 --allow-stale-oi 可以放行部分退回", _guard_ok(_B(), m4))

    # --- 成交量表的月份守門 ---
    class FakeGet:
        def __init__(self, month): self.month = month
        def __call__(self, path, params=None, **kw):
            return {"monthData": [{"month": self.month, "monthID": "AUG-2026-Calls",
                                   "strikeData": [{"strike": "7600", "atClose": "5", "change": "1"}]}]}
    real = cme._get
    try:
        cme._get = FakeGet("AUG 2026")
        ok1 = cme.fetch_volume_oi(5222, "EW4Q26", "20260821", "Aug 2026")
        cme._get = FakeGet("SEP 2026")
        ok2 = cme.fetch_volume_oi(5222, "EW4Q26", "20260821", "Aug 2026")
    finally:
        cme._get = real
    check("成交量表月份對得上才合併",
          ok1 is not None and ok1[0][("C", 7600.0)] == (5, 1) and ok2 is None,
          "月份不符時回 None，避免併到別的系列")


def oi_delta_tests():
    """未平倉增減：前一日的來源有兩種鍵，配錯會讓 Δ 等於整個未平倉量。"""
    import build

    class Leg:
        def __init__(self, exp, K, cp, oi):
            self.exp, self.K, self.cp, self.oi = exp, K, cp, oi
            self.gamma = self.vanna = self.vega = self.iv = 0.0

    legs = [Leg("20260828", 100.0, "C", 500), Leg("20260904", 100.0, "C", 300),
            Leg("20260828", 100.0, "P", 200)]

    # (1) 逐到期別的前一日（期交所路徑）：逐口相減
    per_exp = {("20260828", 100.0, "C"): 400, ("20260904", 100.0, "C"): 250,
               ("20260828", 100.0, "P"): 200}
    r = build.strike_components(legs, 100.0, per_exp, 1.0)[0]
    check("逐到期別的前一日：Δ 是逐口相減",
          r["dc"] == 150 and r["dp"] == 0, f'dc={r["dc"]} dp={r["dp"]}')

    # (2) 只有逐履約價合計的前一日（美股 / CME 從自家 JSON 讀回）
    by_k = {("*", 100.0, "C"): 700, ("*", 100.0, "P"): 260}
    r = build.strike_components(legs, 100.0, by_k, 1.0)[0]
    check("只有履約價合計時：加總後再相減，不是每一口都減 0",
          r["oc"] == 800 and r["dc"] == 100 and r["dp"] == -60, f'dc={r["dc"]} dp={r["dp"]}')

    # (3) 這正是修掉的 bug：以前 Δ 會等於整個未平倉量
    check("不會再出現「Δ 等於未平倉量」",
          r["dc"] != r["oc"] and r["dp"] != r["op"])

    # (4) 逐到期別的視圖在只有合計的情況下算不出來，要標成 None 而不是硬算
    r = build.strike_components([l for l in legs if l.exp == "20260828"],
                                100.0, by_k, 1.0, per_expiry=True)[0]
    check("逐到期別視圖在資料不足時標成 None",
          r["dc"] is None and r["dp"] is None, f'dc={r["dc"]}')

    # (5) 前一日整個缺（第一天）
    r = build.strike_components(legs, 100.0, {}, 1.0)[0]
    check("完全沒有前一日時，Δ 等於未平倉量（第一天的正常結果）",
          r["dc"] == r["oc"] and r["dp"] == r["op"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--date")
    a = ap.parse_args()
    math_tests()
    print()
    chain_tests()
    print()
    cme_tests()
    print()
    oi_delta_tests()
    if a.csv:
        print()
        data_tests(a.csv, a.date)
    print()
    if FAILS:
        print(f"✗ {len(FAILS)} 項失敗: {', '.join(FAILS)}")
        return 1
    print("✓ 全部通過")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
