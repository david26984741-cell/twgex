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

    # 6. 休市日表對期交所 2026 年行事曆（2026/09/22 補齊漏列的 2/12、2/13、9/28、10/26、12/25）
    import re
    _here = os.path.dirname(os.path.abspath(__file__))
    hol = engine.load_holidays(os.path.join(_here, "calendar_tw.txt"))
    D = dt.date
    n = round(engine.time_to_expiry(D(2026, 9, 21), D(2026, 9, 29), hol) * 252)
    check("休市日表：202609F4 在 9/21 剩 5 個交易日", n == 5, f"得到 {n}（舊表漏 9/28 時是 6）")
    got = (engine.next_trading_day(D(2026, 9, 24), hol),
           engine.trading_days_between(D(2026, 10, 23), D(2026, 10, 27), hol),
           engine.trading_days_between(D(2026, 12, 24), D(2026, 12, 28), hol),
           engine.trading_days_between(D(2026, 2, 11), D(2026, 2, 23), hol))
    check("休市日表：跨 9/28、10/26、12/25、春節的交易日計數",
          got == (D(2026, 9, 29), 1, 1, 1), f"得到 {got}")
    # 前端 app.js 的 loadCal 只濾掉「以 # 開頭」的行、整行當日期；行內註解會讓那一天在網頁上靜默失效
    bad = []
    for cal in ("calendar_tw.txt", "calendar_us.txt"):
        path = os.path.join(_here, cal)
        front = set()
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if not re.fullmatch(r"\d{4}/\d{2}/\d{2}", s):
                    bad.append(f"{cal}:{i} {s!r}")
                    continue
                try:
                    front.add(D(*(int(x) for x in s.split("/"))))
                except ValueError:
                    bad.append(f"{cal}:{i} {s!r}")
        if front != engine.load_holidays(path):
            bad.append(f"{cal}：前端與 engine 讀出的日期不同")
    check("休市日表：每行只有日期或整行註解，前後端讀出來相同", not bad, "；".join(bad[:3]))
    official = {D(2026, m, d) for m, d in (
        (1, 1), (2, 12), (2, 13), (2, 16), (2, 17), (2, 18), (2, 19), (2, 20), (2, 27),
        (4, 3), (4, 6), (5, 1), (6, 19), (9, 25), (9, 28), (10, 9), (10, 26), (12, 25))}
    miss = sorted(official - hol)
    check("休市日表：期交所公告的 2026 年 18 個平日休市日都有列", not miss,
          "漏 " + "、".join(d.strftime("%m/%d") for d in miss) if miss else "")


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

    # --- 報價換日：用 put-call parity 反解遠期，挑貼現貨的那個欄位 ---
    # 2026/09/02 真實踩到的坑：標的的 prev_day_close 已經滾到當天收盤，
    # 但每一檔選擇權的 prev_day_close 還停在前一天，做出來是
    # 「今天的現貨 ＋ 今天的未平倉 ＋ 昨天的選擇權報價」。
    def _chain(spot_close, fwd_prev, fwd_mid, exp="260904", root="SPY   ",
               ks=range(756, 776)):
        """照著指定的遠期價造一條合成鏈：C − P + K 會等於那個遠期。"""
        opts = []
        for K in ks:
            for cp, f in (("C", 1.0), ("P", -1.0)):
                # 隨便給一個滿足 parity 的價：內含價的一半當時間價值，兩邊加一樣多
                tv = 2.0
                intr_prev = max(f * (fwd_prev - K), 0.0)
                intr_mid = max(f * (fwd_mid - K), 0.0)
                # 用 C−P = F−K 直接構造：買權 = tv + max(F−K,0)、賣權 = tv + max(K−F,0)
                pv = tv + (fwd_prev - K if cp == "C" else K - fwd_prev) / 2.0 + \
                     abs(fwd_prev - K) / 2.0
                md = tv + (fwd_mid - K if cp == "C" else K - fwd_mid) / 2.0 + \
                     abs(fwd_mid - K) / 2.0
                del intr_prev, intr_mid
                opts.append({"option": f"{root}{exp}{cp}{int(K*1000):08d}",
                             "prev_day_close": round(pv, 4),
                             "bid": round(md - 0.05, 4), "ask": round(md + 0.05, 4),
                             "last_trade_price": round(md, 4),
                             "open_interest": 100, "volume": 1})
        return {"timestamp": "2026-09-03 03:57:46",
                "data": {"symbol": "SPY", "close": spot_close,
                         "current_price": spot_close, "prev_day_close": spot_close,
                         "last_trade_time": "2026-09-02T15:59:59", "options": opts}}

    # 先確認合成鏈本身的 parity 是對的
    _p = _chain(765.16, 761.08, 765.40)
    f_prev, n_prev = cboe.parity_forward(_p, "prev_close", 765.16, after="20260902")
    f_mid, n_mid = cboe.parity_forward(_p, "mid", 765.16, after="20260902")
    check("parity 反解得出遠期（prev_day_close 欄）",
          f_prev is not None and abs(f_prev - 761.08) < 0.01 and n_prev >= 5,
          f"{f_prev}（{n_prev} 對）")
    check("parity 反解得出遠期（買賣中價欄）",
          f_mid is not None and abs(f_mid - 765.40) < 0.01 and n_mid >= 5,
          f"{f_mid}（{n_mid} 對）")

    # 情境一：2026/09/02 —— 選擇權的 prev_day_close 還沒換日，必須改用中價
    pk = cboe.pick_price_field(_p, 765.16, after="20260902")
    check("報價沒換日時改用買賣中價", pk["field"] == "mid",
          f"選到 {pk['field']}，prev 差 {pk['candidates']['prev_close']['rel']*100:+.2f}%、"
          f"中價差 {pk['candidates']['mid']['rel']*100:+.2f}%")

    # 情境二：隔天早上 CBOE 已經換日、中價是盤前的雜訊 → 要選回 prev_close
    _p2 = _chain(765.16, 765.12, 770.90)
    pk2 = cboe.pick_price_field(_p2, 765.16, after="20260902")
    check("報價已換日時選回 prev_day_close", pk2["field"] == "prev_close",
          f"選到 {pk2['field']}")

    # 情境三：兩邊都對不上 → 不給答案，交給呼叫端擋
    _p3 = _chain(765.16, 750.00, 780.00)
    pk3 = cboe.pick_price_field(_p3, 765.16, after="20260902")
    check("兩個欄位都偏離時超出容忍值",
          pk3["field"] is not None and abs(pk3["rel"]) > cboe.FWD_TOL,
          f"最接近的仍差 {pk3['rel']*100:+.2f}%（容忍 {cboe.FWD_TOL*100:.2f}%）")

    # 情境四：已到期的序列不可以拿來當判準（它的 prev_day_close 永遠停在舊值）
    _p4 = _chain(765.16, 700.00, 765.30, exp="260902")      # 已在 09/02 到期
    f4, n4 = cboe.parity_forward(_p4, "prev_close", 765.16, after="20260902")
    check("已到期的序列被排除在 parity 判準之外", f4 is None and n4 == 0,
          f"{f4}（{n4} 對）")

    # 情境五：SPX 的 AM / PM 兩批序列不可以互相配對
    _mix = _chain(7666.60, 7660.0, 7666.5, exp="260918", root="SPX   ",
                  ks=range(7600, 7620, 5))
    _mix2 = _chain(7666.60, 7666.5, 7666.5, exp="260918", root="SPXW",
                   ks=range(7600, 7620, 5))
    _mix["data"]["options"] += _mix2["data"]["options"]
    roots = set()
    for _o in _mix["data"]["options"]:
        roots.add(cboe.osi_root(_o["option"]))
    check("合成鏈確實含 SPX 與 SPXW 兩個根碼", roots == {"SPX", "SPXW"}, str(sorted(roots)))
    f5, n5 = cboe.parity_forward(_mix, "prev_close", 7666.60, after="20260902", n_exp=1)
    check("AM / PM 分開配對，不會混出中間值",
          f5 is not None and (abs(f5 - 7660.0) < 0.01 or abs(f5 - 7666.5) < 0.01),
          f"{f5}（{n5} 對；混在一起會落在 7660~7666.5 之間）")

    # --- 看門狗：兩個訊號各自擋得住什麼 ---------------------------------
    import importlib.util as _ilu, datetime as _dt2, os as _os
    import tempfile as _tf, json as _js, os as _os2, shutil as _sh
    _spec = _ilu.spec_from_file_location(
        "watchdog", _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  "tools", "watchdog.py"))
    _wd = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_wd)
    D = _dt2.date
    HOL_US = {D(2026, 9, 7)}          # 2026 勞動節（星期一）

    check("落後天數會跳過週末",
          _wd.trading_days_since(D(2026, 9, 4), D(2026, 9, 7), set()) == 1,
          "09/04(五) → 09/07(一)：只有 09/07 一天")
    check("落後天數會跳過休市日",
          _wd.trading_days_since(D(2026, 9, 4), D(2026, 9, 8), HOL_US) == 1,
          "09/07 是勞動節，只算 09/08")
    check("資料日就是今天時落後 0",
          _wd.trading_days_since(D(2026, 9, 9), D(2026, 9, 9), set()) == 0)

    # 【2026/09/10 早上 08:00 的真實數字——這一組就是「為什麼要兩個訊號」】
    # ES 已經兩個交易日沒更新（停在 09/04，該有 09/09），但因為 09/07 是勞動節，
    # 「落後」只算出 2，剛好卡在門檻上不會叫。那天早上單看資料日是安靜的。
    lag = _wd.trading_days_since(D(2026, 9, 4), D(2026, 9, 9), HOL_US)
    check("【真實反例】勞動節會把「停兩天」壓成落後 2（舊門檻 2 剛好放過）",
          lag == 2, f"09/07 是勞動節不算，所以只有 09/08、09/09")
    check("收緊到 >1 之後，09/10 這個時點也叫得出來",
          lag > _wd.LAG_MAX_DEFAULT,
          f"落後 {lag} > 門檻 {_wd.LAG_MAX_DEFAULT}；舊門檻 2 時它是安靜的")
    # 同一個時點，排程那個訊號本來就會叫（#23、#24 連續失敗）
    ok, desc = _wd.judge_runs([(24, "failure"), (23, "failure")])
    check("【真實反例】同一個時點，連續兩次排程沒成功會叫",
          ok is False and "沒成功" in desc, desc)

    ok, _ = _wd.judge_runs([(25, "success"), (24, "failure")])
    check("失敗一次之後自己救回來就不叫", ok is True, "最近一次成功＝它恢復了")
    ok, _ = _wd.judge_runs([(24, "failure"), (23, "success")])
    check("只有最近一次失敗不叫（單次抖動）", ok is True)
    ok, _ = _wd.judge_runs([(24, "timed_out"), (23, "failure")])
    check("逾時也算失敗", ok is False)
    # 【2026/09/21 的真實反例】第一版把 cancelled 從清單裡濾掉，所以沒叫。
    # 實際是 #38/#39/#40 cancelled、#41 failure；濾掉之後「最近兩次」變成
    # [#41 failure、#37 success]，只有一個壞的 → 判定過關。
    ok, desc = _wd.judge_runs([(41, "failure"), (40, "cancelled")])
    check("【真實反例】cancelled 要算成沒送到，不可以被濾掉",
          ok is False and "沒成功" in desc, desc)
    ok, _ = _wd.judge_runs([(40, "cancelled"), (39, "cancelled")])
    check("連兩次 cancelled 也要叫（排隊 24 小時沒人領，GitHub 砍的）", ok is False)

    # 排隊過久＝runner 沒在線上，這是最早的訊號
    _now = _dt2.datetime(2026, 9, 19, 12, 0, 0)
    def _fake_api(payload):
        def f(url, token):
            return payload
        return f
    _real_api = _wd._api
    try:
        _wd._api = _fake_api({"workflow_runs": [
            {"run_number": 38, "created_at": "2026-09-18T12:13:07Z"},   # 排了 23.8 小時
            {"run_number": 39, "created_at": "2026-09-19T11:30:00Z"}]}) # 排了 0.5 小時
        st = _wd.stuck_queued("r", "daily.yml", "t", _now)
        check("排隊超過三小時沒人領會被抓出來",
              [x[0] for x in st] == [38], f"{st}（剛進隊列的 #39 不算）")
        _wd._api = _fake_api({"workflow_runs": []})
        check("沒有卡住的就是空的", _wd.stuck_queued("r", "daily.yml", "t", _now) == [])
    finally:
        _wd._api = _real_api

    ok, d2 = _wd.judge_runs([(24, "failure")])
    check("紀錄不足兩次時不判斷（新 repo / 剛改完 workflow）", ok is True, d2)
    ok, _ = _wd.judge_runs([])
    check("完全沒有排程紀錄時不判斷", ok is True)

    # 【2026/09/21 改】門檻故意比網站嚴一格，不是不小心不一致
    check("看門狗的門檻比網站嚴一格（固定在 08:00 跑，該有的落後是定值）",
          _wd.LAG_MAX.get("TXO") == 1 and _wd.LAG_MAX_DEFAULT == 1,
          "兩邊都 >1；網站是 台指>1 / 美股>2，寬一點是不要對客戶誤報紅字")
    # 【2026/09/21 的真實反例】ES 停在 09/16、漏掉 09/17 與 09/18 兩個場次，
    # 但中間隔著週末，週一早上算出來的落後只有 2——舊門檻（>2）剛好放過去。
    lag2 = _wd.trading_days_since(D(2026, 9, 16), D(2026, 9, 20), set())
    check("【真實反例】週末會把「漏兩天」壓成落後 2，舊門檻剛好放過",
          lag2 == 2 and not (lag2 > 2), f"落後 {lag2}（09/19、09/20 是週末不算）")
    check("收緊後同一個數字就會叫", lag2 > _wd.LAG_MAX_DEFAULT,
          f"落後 {lag2} > 門檻 {_wd.LAG_MAX_DEFAULT}")
    # 正常的一天不可以因此誤報：週二~週五早上該有的落後是 1
    check("正常日（落後 1）收緊後仍不叫", not (1 > _wd.LAG_MAX_DEFAULT))
    check("四個標的都在看門狗的名單裡",
          {s[0] for s in _wd.SYMBOLS} == {"TXO", "SPX", "SPY", "QQQ"})
    check("台指看台北、美股看美東",
          dict((s[0], s[2]) for s in _wd.SYMBOLS)["TXO"] == 8
          and dict((s[0], s[2]) for s in _wd.SYMBOLS)["SPX"] == -5)

    # 資料檔壞掉 / 不見時要當成失敗，不可以安靜略過
    _t2 = _tf.mkdtemp()
    try:
        _os2.makedirs(_os2.path.join(_t2, "data", "TXO"))
        open(_os2.path.join(_t2, "calendar_tw.txt"), "w").write("")
        open(_os2.path.join(_t2, "calendar_us.txt"), "w").write("")
        r = dict((x[0], x) for x in _wd.check_data(_t2))
        check("latest.json 不見時判成失敗", r["SPX"][4] is False, r["SPX"][5])
        with open(_os2.path.join(_t2, "data", "TXO", "latest.json"), "w") as fh:
            fh.write("{ 壞掉的 json")
        r = dict((x[0], x) for x in _wd.check_data(_t2))
        check("latest.json 壞掉時判成失敗，不是當作沒事",
              r["TXO"][4] is False, r["TXO"][5][:40])
    finally:
        _sh.rmtree(_t2, ignore_errors=True)

    # --- SPX → ES 點位換算 ----------------------------------------------
    import es_view as _ev
    D3 = _dt2.date
    check("第三個星期五算得對（2026/12）", _ev.third_friday(2026, 12) == D3(2026, 12, 18))
    check("第三個星期五算得對（月初就是星期五的月份）",
          _ev.third_friday(2027, 1) == D3(2027, 1, 15))
    # 季月到期當天，front 就換下一口了（我們的鏈本來也會排除當日到期）
    check("季月到期當天就換到下一口",
          _ev.quarterly_ltd(D3(2026, 9, 18)) == D3(2026, 12, 18))
    check("到期前一天還是這一口", _ev.quarterly_ltd(D3(2026, 9, 17)) == D3(2026, 9, 18))
    check("跨年找得到", _ev.quarterly_ltd(D3(2026, 12, 18)) == D3(2027, 3, 19))

    # 找季月要用 code 不能用 ltd：SPX 的 AM 結算 ltd 已經往前挪了一個交易日
    _fake = {"expiries": [
        {"code": "20261218", "ltd": "2026-12-18", "F": 7712.40},
        {"code": "20261218A", "ltd": "2026-12-17", "F": 7711.65},
        {"code": "20261231", "ltd": "2026-12-31", "F": 7725.05}]}
    _e = _ev.find_quarter_expiry(_fake, D3(2026, 12, 18))
    check("季月優先取 AM 那一檔（ES 期貨也是用第三個星期五的 SOQ 結算）",
          _e["code"] == "20261218A", f"取到 {_e['code']}")
    check("用 ltd 找會找錯", _fake["expiries"][1]["ltd"] == "2026-12-17",
          "AM 那檔的 ltd 是 12/17，不是 12/18")

    # 真的拿一天的 SPX 來換算，檢查「只動價格、不動其他」
    _sp = _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)),
                         "data", "SPX", "latest.json")
    if _os2.path.exists(_sp):
        with open(_sp, encoding="utf-8") as fh:
            _p = _js.load(fh)
        _d = _ev.derive(_p)
        _a, _b = _p["views"]["ALL"], _d["views"]["ALL"]
        _r = _d["meta"]["es_ratio"]
        check("換算不動任何金額（GEX / VEX 總量完全一樣）", _a["totals"] == _b["totals"])
        check("換算不動未平倉", (_a["oi_c"], _a["oi_p"]) == (_b["oi_c"], _b["oi_p"]))
        check("換算不動情境曲線的 y 值", _a["curve"]["gc"] == _b["curve"]["gc"])
        check("履約價有被換算", _b["strikes"][0]["K"] != _a["strikes"][0]["K"])
        check("曲線 x 有被換算，長度不變",
              _b["curve"]["x"][0] != _a["curve"]["x"][0]
              and len(_b["curve"]["x"]) == len(_a["curve"]["x"]))
        # 這是整個換算成立的關鍵：K/F 不變 → IV、gamma、skew、flip 全部自動一致
        _F0, _F1 = _p["expiries"][0]["F"], _d["expiries"][0]["F"]
        _w = max(abs((y["K"] / _F1) / (x["K"] / _F0) - 1)
                 for x, y in zip(_a["strikes"], _b["strikes"]) if x["K"])
        check("價內外關係 K/F 完全保持不變（所以不必重算任何希臘字母）",
              _w < 1e-5, f"最大相對偏差 {_w:.1e}，純粹是四捨五入到小數兩位")
        check("換算後的 meta 有講清楚來源", _d["meta"].get("derived_from") == "SPX"
              and "不是 CME" in _d["meta"].get("source", ""))
        check("乘數沒有被改成 ES 的 50（金額還是 SPX 的）",
              _d["meta"]["multiplier"] == _p["meta"]["multiplier"])

        # 前端（app.js 的 deriveES）與這支 Python 必須逐值相同，不可以各走各的
        _aj = _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "app.js")
        _xj = _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)),
                             "tools", "xcheck_es.js")
        import subprocess as _sub, shutil as _sh2
        if _sh2.which("node") and _os2.path.exists(_xj):
            _r2 = _sub.run(["node", _xj, _aj, _sp], capture_output=True, text=True)
            if _r2.returncode == 0:
                _o = _js.loads(_r2.stdout)
                check("app.js 的 deriveES 與 es_view.py 逐值相同（兩份獨立實作）",
                      abs(_o["ratio"] - _r) < 1e-12
                      and _o["s_ref"] == _d["meta"]["s_ref"]
                      and _o["quarter"] == _d["meta"]["es_quarter"]
                      and _o["K"] == [x["K"] for x in _b["strikes"]]
                      and _o["x"] == _b["curve"]["x"],
                      f"ratio {_o['ratio']:.8f} / {_o['quarter']} / 基差 {_o['basis']:+.2f}")
            else:
                check("app.js 的 deriveES 與 es_view.py 逐值相同", False,
                      f"node 跑不起來：{_r2.stderr[:120]}")
        else:
            print("  註：沒有 node，跳過 app.js 與 es_view.py 的對照。", file=sys.stderr)

    # 【2026/08/21~09/16 拿真的 CME 結算價比對過的結論，寫死在這裡當紀錄】
    # 離季月 7 天以上的 11 天：平均差 −0.08 點、標準差 6.3、最大 12 點 → 方法沒有偏差。
    # 剩 4／3／2 天那三天：差 −10／−73／−88 點 → 不是算錯，是指到不同的契約
    #（我們算 9 月，市場的未平倉已經滾到 12 月）。所以換倉窗口要把兩口都算出來。
    _p2 = {"meta": {"trade_date": "2026/09/16", "s_ref": 7551.81},
           "expiries": [{"code": "20260918A", "ltd": "2026-09-17", "F": 7535.28},
                        {"code": "20261218A", "ltd": "2026-12-17", "F": 7601.97}]}
    _rt, _qe2, _q2, _roll = _ev.ratio_of(_p2)
    check("換倉窗口裡會把下一口季月也算出來",
          _roll is not None and _roll["next_quarter"] == "ESZ26",
          f"{_roll}")
    check("換倉提醒帶著還剩幾天", _roll["days_left"] == 2)
    _p3 = dict(_p2, meta={"trade_date": "2026/08/21", "s_ref": 7652.86})
    _rt3, _, _, _roll3 = _ev.ratio_of(_p3)
    check("離季月還久的時候不吵換倉", _roll3 is None, "8/21 距 9/18 還有 28 天")

    # --- 整批塌掉的守門（ES 2026/09/03 真的發生過）---
    import tempfile, shutil as _sh, json as _json, os as _os
    _b = __import__('build')
    class _A:
        allow_stale_oi = False
    def _mk(tmp, prev_meta, now_meta, day='20260903', prev='20260902'):
        with open(_os.path.join(tmp, prev + '.json'), 'w', encoding='utf-8') as fh:
            _json.dump({'meta': prev_meta}, fh)
        return dict(args=_A(), sym='ES', payload={'meta': now_meta},
                    hdir=tmp, before=[prev], day=day)
    NORMAL = {'oi_total': 4748217, 'n_expiries': 59, 'n_legs': 10741}
    tmp = tempfile.mkdtemp()
    try:
        # 真實案例：只剩 0.5% → 要擋
        kw = _mk(tmp, NORMAL, {'oi_total': 24530, 'n_expiries': 4, 'n_legs': 292})
        try:
            _b._collapse_guard(**kw); ok = False; why = '沒擋'
        except SystemExit as e:
            ok = '塌掉一半以上' in str(e) and '0.5%' in str(e); why = str(e)[:70]
        check('整批塌掉會被擋下來（ES 2026/09/03 的真實數字）', ok, why)

        # 正常的日間變動 → 要放行
        kw = _mk(tmp, NORMAL, {'oi_total': 4600000, 'n_expiries': 58, 'n_legs': 10500})
        try:
            _b._collapse_guard(**kw); ok = True
        except SystemExit as e:
            ok = False
        check('正常的日間變動照樣放行', ok, '未平倉 −3%、到期別 59→58')

        # 剛好在門檻邊上（50%）→ 不擋
        kw = _mk(tmp, NORMAL, {'oi_total': int(4748217*0.5)+1, 'n_expiries': 30, 'n_legs': 5400})
        try:
            _b._collapse_guard(**kw); ok = True
        except SystemExit:
            ok = False
        check('剛好落在 50% 門檻上不擋', ok, '門檻是「低於 50%」才擋')

        # 加了 --allow-stale-oi 可以放行
        class _A2(_A): allow_stale_oi = True
        kw = _mk(tmp, NORMAL, {'oi_total': 24530, 'n_expiries': 4, 'n_legs': 292})
        kw['args'] = _A2()
        try:
            _b._collapse_guard(**kw); ok = True
        except SystemExit:
            ok = False
        check('加了 --allow-stale-oi 可以強行放行', ok)

        # 第一天（沒有前一日）不擋
        kw = _mk(tmp, NORMAL, {'oi_total': 1, 'n_expiries': 1, 'n_legs': 1})
        kw['before'] = []
        try:
            _b._collapse_guard(**kw); ok = True
        except SystemExit:
            ok = False
        check('第一天沒有前一日可比，不擋', ok)

        # 重跑同一天不擋（day == prev）
        kw = _mk(tmp, NORMAL, {'oi_total': 24530, 'n_expiries': 4, 'n_legs': 292},
                 day='20260902', prev='20260902')
        try:
            _b._collapse_guard(**kw); ok = True
        except SystemExit:
            ok = False
        check('重跑同一天不比對（避免自己擋自己）', ok)
    finally:
        _sh.rmtree(tmp, ignore_errors=True)

    # --- 崩落防線：到期的那批先從前一日扣掉再比（2026/09/16 月選結算日被誤擋、缺了一天的圖）---
    # 包成內層函式：這裡的變數（prev、now…）不能蓋掉 chain_tests 後面還要用的同名變數。
    def _expiry_guard_tests():
        # 數字取自 data/TXO/history 的真實檔；20260916 那份是修好後用期交所 CSV 重建的。
        import io, contextlib
        def _pay(meta, exps):
            return {'meta': dict(zip(('oi_total', 'n_expiries', 'n_legs'), meta)),
                    'expiries': [{'code': c, 'ltd': l, 'oi': o} for c, l, o in exps]}
        def _guard(prev, now, day, prev_day, sym='TXO'):
            """回傳 (擋了沒, 擋下的訊息或放行時的 stderr)。"""
            tmp = tempfile.mkdtemp()
            try:
                with open(_os.path.join(tmp, prev_day + '.json'), 'w', encoding='utf-8') as fh:
                    _json.dump(prev, fh)
                err = io.StringIO()
                try:
                    with contextlib.redirect_stderr(err):
                        _b._collapse_guard(args=_A(), sym=sym, payload=now, hdir=tmp,
                                           before=[prev_day], day=day)
                    return False, err.getvalue()
                except SystemExit as e:
                    return True, str(e)
            finally:
                _sh.rmtree(tmp, ignore_errors=True)

        P0915 = _pay((176512, 8, 1856), [
            ('202609', '2026-09-16', 138991), ('202609F3', '2026-09-18', 8873),
            ('202609W4', '2026-09-23', 5209), ('202609F4', '2026-09-29', 778),
            ('202610', '2026-10-21', 13385), ('202611', '2026-11-18', 1191),
            ('202612', '2026-12-16', 6652), ('202703', '2027-03-17', 1433)])
        N0916 = _pay((68313, 8, 1464), [
            ('202609F3', '2026-09-18', 29681), ('202609W4', '2026-09-23', 10735),
            ('202609F4', '2026-09-29', 936), ('202609W5', '2026-09-30', 495),
            ('202610', '2026-10-21', 17052), ('202611', '2026-11-18', 1299),
            ('202612', '2026-12-16', 6678), ('202703', '2027-03-17', 1437)])
        blocked, out = _guard(P0915, N0916, '20260916', '20260915')
        gone = _b._expired_since(P0915, N0916, '20260916')
        check('崩落防線：9/15→9/16 月選結算日放行（未平倉只剩 38.7%，扣掉到期的 202609 再比）',
              not blocked and [g['code'] for g in gone] == ['202609'] and '138,991' in out,
              out.strip()[:90])

        P0818 = _pay((183156, 8, 1793), [
            ('202608', '2026-08-19', 141130), ('202608F3', '2026-08-21', 7756),
            ('202608W4', '2026-08-26', 4059), ('202608F4', '2026-08-28', 720),
            ('202609', '2026-09-16', 22778), ('202610', '2026-10-21', 1734),
            ('202612', '2026-12-16', 4107), ('202703', '2027-03-17', 872)])
        N0819 = _pay((62778, 8, 1521), [
            ('202608F3', '2026-08-21', 21261), ('202608W4', '2026-08-26', 6397),
            ('202608F4', '2026-08-28', 969), ('202609W1', '2026-09-02', 660),
            ('202609', '2026-09-16', 26468), ('202610', '2026-10-21', 1881),
            ('202612', '2026-12-16', 4244), ('202703', '2027-03-17', 898)])
        blocked, out = _guard(P0818, N0819, '20260819', '20260818')
        check('崩落防線：8/18→8/19 月選結算日放行（未平倉只剩 34.3%）', not blocked, out.strip()[:90])

        P0917 = _pay((134872, 9, 1584), [
            ('202609F3', '2026-09-18', 78028), ('202609W4', '2026-09-23', 15396),
            ('202609F4', '2026-09-29', 1241), ('202609W5', '2026-09-30', 1535),
            ('202610', '2026-10-21', 26071), ('202611', '2026-11-18', 1401),
            ('202612', '2026-12-16', 6728), ('202703', '2027-03-17', 4402),
            ('202706', '2027-06-16', 70)])
        N0918 = _pay((81816, 9, 1527), [
            ('202609W4', '2026-09-23', 33956), ('202609F4', '2026-09-29', 3801),
            ('202609W5', '2026-09-30', 1795), ('202610F1', '2026-10-02', 323),
            ('202610', '2026-10-21', 28890), ('202611', '2026-11-18', 1729),
            ('202612', '2026-12-16', 6687), ('202703', '2027-03-17', 4501),
            ('202706', '2027-06-16', 134)])
        blocked, out = _guard(P0917, N0918, '20260918', '20260917')
        gone = _b._expired_since(P0917, N0918, '20260918')
        check('崩落防線：9/17→9/18 週五選到期放行，只扣 202609F3',
              not blocked and [g['code'] for g in gone] == ['202609F3'], out.strip()[:90])

        # 還沒到期的 202610 也不見了：只扣 202609，分母 37,521、剩 20% → 要擋
        prev = _pay((176512, 3, 1000), [('202609', '2026-09-16', 138991),
                                        ('202610', '2026-10-21', 30000), ('202611', '2026-11-18', 7521)])
        now = _pay((7521, 1, 900), [('202611', '2026-11-18', 7521)])
        blocked, out = _guard(prev, now, '20260916', '20260915')
        ded = [l for l in out.splitlines() if '已到期而扣除' in l]
        check('崩落防線：還沒到期的到期別不見了照樣擋（只扣真的到期的那批）',
              blocked and '塌掉一半以上' in out and len(ded) == 1
              and '202609（' in ded[0] and '202610' not in ded[0], out.strip()[:90])

        # ES 2026/09/03：留下的四批全是遠月，消失的 55 批最後交易日都還在未來 → 一口都不扣
        es = [(f'ES{i:02d}', (dt.date(2026, 9, 4) + dt.timedelta(days=7 * i)).isoformat(), 80000)
              for i in range(59)]
        blocked, out = _guard(_pay((4748217, 59, 10741), es), _pay((24530, 4, 292), es[-4:]),
                              '20260903', '20260902', sym='ES')
        check('崩落防線：ES 2026/09/03 的真實崩落在帶到期別清單時仍然擋',
              blocked and '剩 0.5%' in out, out.strip()[:90])

        # 舊格式（只有 meta、沒有 expiries）完全照舊比：9/16 的數字照樣被擋
        blocked, out = _guard({'meta': P0915['meta']}, {'meta': N0916['meta']}, '20260916', '20260915')
        check('崩落防線：沒有到期別清單時照舊比（9/16 的數字仍會被擋）',
              blocked and '剩 38.7%' in out and '已到期而扣除' not in out, out.strip()[:90])

        # 同一天到期兩批、最後交易日三種寫法：兩批都扣、依日期排序、口數加總對
        prev = _pay((1000, 3, 300), [('A', '2026-09-16', 600), ('B', '2026/09/16', 300),
                                     ('C', '20261021', 100)])
        now = _pay((150, 1, 200), [('C', '20261021', 150)])
        gone = _b._expired_since(prev, now, '20260916')
        blocked, out = _guard(prev, now, '20260916', '20260915')
        check('崩落防線：同日到期的多批都扣，三種日期寫法都認得',
              not blocked and gone is not None and [g['code'] for g in gone] == ['A', 'B']
              and sum(g['oi'] for g in gone) == 900, f"{gone}")
    _expiry_guard_tests()

    # --- 未平倉日期的反推要看假日表 ---
    pay3 = {"data": {"options": [
        {"option": "SPY   260826C00760000", "open_interest": 1000},
        {"option": "SPY   260825C00760000", "open_interest": 0}]}}
    check("未平倉日期反推：用假日表往前一個交易日",
          cboe.oi_as_of(pay3, "20260826", prev_td=prev) == "20260825",
          str(cboe.oi_as_of(pay3, "20260826", prev_td=prev)))

    check("沒給 am_roots 時維持 SPY / QQQ 的原本行為",
          set(plain) == {"20260918", "20260824"}, str(sorted(plain)))


def cboe_snapshot_tests():
    """CBOE 的 prev_day_close 與 last_trade_time 換日時點不同——美股每日更新何時該滾前收的判準。

    原本放在已退役的直連路線測試函式裡，該函式刪除後這幾項逐字搬過來。
    """
    # --- CBOE：prev_day_close 與 last_trade_time 換日時點不同 ---
    import cboe as _cboe
    snap = lambda ts, lt, cur=None, pv=None, close=None: _cboe.snapshot_state(
        {"timestamp": ts, "data": {"last_trade_time": lt, "close": close,
                                   "current_price": cur, "prev_day_close": pv}})
    # 六個都是真實踩過或量過的情境
    a = snap("2026-08-27 14:33:16", "2026-08-27T10:33:00", 769.07, 766.08)
    check("盤中抓：prev_day_close 還是前一場次的", not a["rolled"],
          "場次還沒收，這一關就要擋掉")
    b = snap("2026-08-27 23:27:47", "2026-08-27T16:14:59", 771.10, 766.08)
    check("收盤後、還沒滾：仍然算前一場次", not b["rolled"], "這是昨晚建出正確 08/26 的那一輪")
    c = snap("2026-08-28 03:50:37", "2026-08-27T15:59:59", 771.10, 771.10)
    check("收盤後、已經滾了：收盤價＝前收就是滾過了",
          c["rolled"] and c["rolled_px"] and not c["rolled_cal"],
          "日曆判準抓不到這個（同一個美東日期），價格判準抓得到")
    d = snap("2026-08-27 05:45:07", "2026-08-26T16:00:00", 766.08, 766.08)
    check("跨到隔天、也已經滾了", d["rolled"] and d["rolled_px"] and d["rolled_cal"],
          "這是 08/27 07:55 那次把 08/26 的價格標成 08/25 的成因")
    # 2026/09/01 實測：QQQ 的 close 與 prev_day_close 都是 716.76（已經滾了），
    # 但 current_price 是 716.70。用 current_price 比會判成「還沒滾」，
    # 價格被算成前一天、跟 OCC 的未平倉對不起來，整批美股當天不產出。
    f = snap("2026-09-01 03:57:33", "2026-08-31T15:59:59", 716.70, 716.76, close=716.76)
    check("current_price 與收盤價差幾分錢時仍判得出已經滾了",
          f["rolled"], "要比 close，不是比 current_price——差六分錢就整批不產出")
    g = snap("2026-09-01 03:57:33", "2026-08-31T15:59:59", 716.70, 710.00, close=716.76)
    check("真的還沒滾（前收是更早那天）就不能誤判成滾了", not g["rolled"])
    h = snap("2026-09-01 18:20:00", "2026-09-01T13:45:00", 716.70, 716.70, close=716.70)
    check("盤中價格剛好等於前收也不算滾（場次還沒收）", not h["rolled"],
          "沒有 session_over 這一關的話，盤中完全沒動的標的會被誤判")
    e = snap("", "")
    check("欄位缺漏時不會炸、也不會誤判成滾過", e["rolled"] is False, str(e["rolled"]))


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

    # (2) 只有逐履約價合計的前一日（美股從自家 JSON 讀回）
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



def occ_tests():
    """OCC 當未平倉來源。

    OCC 在交易日**當天傍晚**（美東約 20:00）就發布逐序列未平倉，CBOE 那份檔案要
    **隔天早上**（美東 10:00~10:30）才吃進去。平日差十幾個小時、跨週末差 2.5 天。
    這裡守住三件事：欄位不會錯開、根碼不會互相覆蓋、以及最重要的——
    「OCC 還沒發布新的一天」時不能默默產出拼裝圖。
    """
    import occ

    def row(root, exp, whole, dec, c, p):
        # 真實檔案在根碼後面是**兩個** tab，欄位很容易整排錯開一格（踩過一次）
        return (f"{root}\t\t{exp[:4]}\t{int(exp[4:6])}\t{int(exp[6:8])}\t"
                f"{whole}\t{dec}\tC\t{c}\t{p}\t250000")

    txt = "\n".join([
        row("SPX", "20260918", 7000, 0, 111, 222),
        row("SPXW", "20260918", 7000, 0, 333, 444),      # 同到期同履約價，AM/PM 都在
        row("SPY", "20260918", 533, 330, 10, 20),        # 不在 0.5 格上的履約價
        row("2SPX", "20260918", 7000, 0, 9, 9),          # 公司行為調整過的根碼
    ])

    m = occ.parse_series(txt, occ.ROOTS["SPX"])
    check("OCC：AM 與 PM 不會互相覆蓋",
          m.get(("SPX", "20260918", "C", 7000000)) == 111
          and m.get(("SPXW", "20260918", "C", 7000000)) == 333,
          "第三個星期五 SPX 與 SPXW 撞在同一個到期日、履約價還大量重疊，"
          "key 少了根碼的話比對出來的『100% 相同』是假的")
    check("OCC：買權與賣權分別讀到 8 / 9 欄",
          m.get(("SPX", "20260918", "P", 7000000)) == 222)
    check("OCC：公司行為調整過的根碼被排除", ("2SPX", "20260918", "C", 7000000) not in m)

    ksp = occ.parse_series(txt, occ.ROOTS["SPY"])
    check("OCC：履約價用整數千分位，小數不會走位",
          ksp.get(("SPY", "20260918", "C", 533330)) == 10,
          "533.33 在 533330/1000.0 與 533+330/1000.0 兩種算法下不保證是同一個 float")

    one_tab = txt.replace("SPX\t\t", "SPX\t").replace("SPXW\t\t", "SPXW\t")
    check("OCC：根碼後面一個或兩個 tab 都讀得對",
          occ.parse_series(one_tab, occ.ROOTS["SPX"]).get(("SPX", "20260918", "C", 7000000)) == 111,
          "欄位位置用推的（跳過根碼後面的空欄），不寫死第幾欄；"
          "寫死過一次，OCC 的旗標跟我猜的不一樣，整份被濾成 0 筆")
    check("OCC：未平倉不是數字的列會整列跳過，不會讀到隔壁格",
          occ.parse_series("SPY\t\t2026\t9\t18\t533\t330\tC\tabc\t20\t250000",
                           occ.ROOTS["SPY"]) == {})
    check("OCC：欄位數不足的列跳過",
          occ.parse_series("SPY\t\t2026\t9\t18\t533\t330\tC\t10", occ.ROOTS["SPY"]) == {})
    check("OCC：年月日不合理的列跳過",
          occ.parse_series("SPY\t\t2026\t99\t18\t533\t330\tC\t10\t20\t250000",
                           occ.ROOTS["SPY"]) == {})

    a = {("SPY", "20260918", "C", 533000): 10, ("SPY", "20260918", "P", 533000): 20}
    check("OCC：逐檔一樣時 same_numbers 回 True", occ.same_numbers(a, dict(a)) is True,
          "一樣就代表 OCC 還沒往前走，這一輪沒有提前，日期要以 CBOE 的判斷為準")
    b = dict(a); b[("SPY", "20260918", "C", 533000)] = 11
    check("OCC：有一檔不同就回 False", occ.same_numbers(a, b) is False)
    check("OCC：完全沒有重疊時回 False（當成不可信）",
          occ.same_numbers(a, {("QQQ", "20260918", "C", 1): 1}) is False)

    hol = set()
    check("OCC：next_trading_day 會跳過週末",
          occ.next_trading_day("20260828", hol) == "20260831",
          "2026/08/28 是週五，下一個交易日是 08/31")


def us_stall_tests():
    """2026/09/23 Cboe CDN 停更暴露的漏洞：兩道新防線。

    一、Cboe 報價是不是過期了——照日曆判定（build.us_last_session、cboe.quote_stale）。
    二、OCC 未平倉是哪一天的——直接讀 OCC 月報的日期欄（occ.report_dates、occ.latest_published），
        不再用「CBOE 檔的未平倉日＋1」推。9/24 那幾班就是推錯，把 9/22 的報價配上 9/23 的未平倉標成 9/22。
    全部不連網：OCC 月報一律由注入的 fetch= 字典函式提供，並記下被呼叫的順序。
    """
    import build
    import cboe as _cboe
    import occ

    hol = engine.load_holidays(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calendar_us.txt"))
    U = dt.datetime

    # --- 日曆上最近一個已收盤的交易日（UTC−5 近似美東） ---
    for now, want, why in (
            (U(2026, 9, 24, 12, 43), "20260923", "本事件：9/24 那幾班應該要做 9/23"),
            (U(2026, 9, 23, 13, 32), "20260922", "9/23 晚上那次做 9/22 是對的"),
            (U(2026, 9, 28, 4, 30), "20260925", "週一台北中午＝美東週日晚上，最近一場是週五"),
            (U(2026, 9, 8, 4, 30), "20260904", "9/7 勞動節休市，要跳回 9/4"),
            (U(2026, 9, 24, 22, 30), "20260924", "美東 17:30 之後，當天就算已收盤"),
            (U(2026, 9, 26, 4, 30), "20260925", "週六台北中午＝美東週五晚上")):
        got = build.us_last_session(hol, now)
        check(f"美股最近已收盤交易日：{now:%m/%d %H:%M} UTC → {want}", got == want, f"{why}；得到 {got}")

    check("美東今天：09/25 04:30 UTC 還是 09/24", build._et_today(U(2026, 9, 25, 4, 30)) == "20260924")
    check("美東今天：09/25 05:00 UTC 換成 09/25", build._et_today(U(2026, 9, 25, 5, 0)) == "20260925")

    # --- Cboe 報價過期（照日曆） ---
    check("報價過期：檔案停在 9/22、日曆已是 9/23 → 過期", _cboe.quote_stale("20260922", "20260923") is True,
          "9/24 那四班就是這樣，要擋")
    check("報價過期：同一天 → 不算過期", _cboe.quote_stale("20260922", "20260922") is False,
          "9/23 晚上那次是對的，不能誤擋")
    check("報價過期：檔案比日曆新（盤中、盤前）→ 不算過期", _cboe.quote_stale("20260924", "20260923") is False)
    check("報價過期：沒有場次日期時不在這裡判", _cboe.quote_stale("", "20260923") is False,
          "交給既有的「找不到交易日」處理")

    # --- OCC 月報（合成；格式照 2026/09/24 的原文，數字自編） ---
    def M(label, dates):
        rows = [f"Daily Open Interest - {label}",
                "Date,Equity,,,Index/Other,,,Debt,,,Futures,OCC Total",
                ",Calls,Puts,Total,Calls,Puts,Total,Calls,Puts,Total,Total,"]
        for i, d in enumerate(dates):
            nums = ",".join(f'"{1000000 + 1234 * (i + 1) + 7 * j:,}"' for j in range(11))
            rows.append(f"{d},{nums},")
        return "\r\n".join(rows) + "\r\n"

    sep23 = ["09/23/2026", "09/22/2026", "09/21/2026", "09/18/2026", "09/17/2026", "09/16/2026",
             "09/15/2026", "09/14/2026", "09/11/2026", "09/10/2026", "09/09/2026", "09/08/2026",
             "09/04/2026", "09/03/2026", "09/02/2026", "09/01/2026"]      # 跟真實月報同一組日期：沒有 09/07
    SEP23 = M("September 2026", sep23)
    SEP30 = M("September 2026", ["09/30/2026", "09/29/2026", "09/28/2026", "09/25/2026", "09/24/2026"] + sep23)
    SEP04 = M("September 2026", ["09/04/2026", "09/03/2026", "09/02/2026", "09/01/2026"])
    SEP0 = M("September 2026", [])
    OCT0 = M("October 2026", [])
    JAN0 = M("January 2027", [])
    DEC31 = M("December 2026", ["12/31/2026", "12/30/2026", "12/29/2026", "12/28/2026", "12/24/2026"])
    HTML = "<html><body>Service Unavailable</body></html>"
    ymd = lambda s: s[6:] + s[:2] + s[3:5]
    want_sep23 = [ymd(s) for s in sep23]

    def F(table):
        """字典當月報來源：值是字串就回傳、是例外就丟；沒有這個鍵就丟 OSError。順便記下被叫的順序。"""
        calls = []

        def fetch(mdy):
            calls.append(mdy)
            if mdy not in table:
                raise OSError(f"沒有 {mdy}")
            v = table[mdy]
            if isinstance(v, BaseException):
                raise v
            return v
        return fetch, calls

    check("月報 r1：讀出 16 個日期、新的在前、沒有勞動節",
          occ.report_dates(SEP23) == want_sep23, str(occ.report_dates(SEP23)[:3]))
    lf_quoted = "\n".join((f'"{ln[:10]}"{ln[10:]}' if ln[:2].isdigit() else ln)
                          for ln in SEP23.replace("\r\n", "\n").split("\n"))
    check("月報 r2：只有 \\n 換行、日期加了引號也讀得對", occ.report_dates(lf_quoted) == want_sep23)
    check("月報 r3：本月一天都還沒發布 → 空清單（看得懂、只是還沒有）", occ.report_dates(OCT0) == [])
    check("月報 r4：空字串與錯誤頁都是「看不懂」→ None",
          occ.report_dates("") is None and occ.report_dates(HTML) is None)
    odd = SEP0 + "\r\n".join([
        "09/24/2026,,,,,,,,,,,",
        "09/25/2026," + ",".join(['"0"'] * 11) + ",",
        '13/45/2026,"1,234,567",',
        '09/23/2026,"1,234,567",']) + "\r\n"
    check("月報 r5：數字全空或全 0 的列、不合法的日期都不算", occ.report_dates(odd) == ["20260923"],
          str(occ.report_dates(odd)))

    D09, D10 = "09/01/2026", "10/01/2026"
    cases = (
        ("p1 本事件：價格 9/22、OCC 已到 9/23", "20260922", "20260924", {D09: SEP23},
         ("20260923", "ok"), [D09]),
        ("p2 正常早班", "20260923", "20260924", {D09: SEP23}, ("20260923", "ok"), [D09]),
        ("p3 美東晚間", "20260923", "20260923", {D09: SEP23}, ("20260923", "ok"), [D09]),
        ("p4 OCC 還沒發布價格那天", "20260924", "20260924", {D09: SEP23}, ("20260923", "not_yet"), [D09]),
        ("p5 本月一天都還沒有 → 改抓上個月", "20260930", "20261001", {D10: OCT0, D09: SEP30},
         ("20260930", "ok"), [D10, D09]),
        ("p6 端點回了別的月份的內容 → 照讀、不退回", "20260930", "20261001", {D10: SEP30},
         ("20260930", "ok"), [D10]),
        ("p7 跨年", "20261231", "20270104", {"01/01/2027": JAN0, "12/01/2026": DEC31},
         ("20261231", "ok"), ["01/01/2027", "12/01/2026"]),
        ("p8 兩個月都還沒有 → 無法確認", "20260930", "20261001", {D10: OCT0, D09: SEP0},
         (None, "unknown"), [D10, D09]),
        ("p9 上個月抓不到 → 無法確認", "20260930", "20261001", {D10: OCT0, D09: OSError()},
         (None, "unknown"), [D10, D09]),
        ("p10 第一次就抓不到 → 無法確認、不退回上個月", "20260930", "20261001", {D10: OSError(), D09: SEP30},
         (None, "unknown"), [D10]),
        ("p11 看不懂（錯誤頁）→ 無法確認、不退回上個月", "20260930", "20261001", {D10: HTML, D09: SEP30},
         (None, "unknown"), [D10]),
        ("p12 上界在未來", "20260923", "20260930", {D09: SEP23}, ("20260923", "ok"), [D09]),
        ("p13 上界是假日", "20260904", "20260907", {D09: SEP04}, ("20260904", "ok"), [D09]),
        ("p14 假日後 OCC 還沒發布", "20260908", "20260908", {D09: SEP04}, ("20260904", "not_yet"), [D09]),
        ("p15 月報比美東今天還新 → 無法確認", "20260922", "20260922", {D09: SEP23}, (None, "unknown"), [D09]),
        ("p16 上界早於價格日（時鐘誤差）→ 以價格日為上界", "20260923", "20260922", {D09: SEP23},
         ("20260923", "ok"), [D09]),
    )
    for name, pday, until, table, want, want_calls in cases:
        fetch, calls = F(table)
        got = occ.latest_published(pday, until, fetch=fetch)
        check(f"OCC 月報日期 {name}", got == want and calls == want_calls,
              f"得到 {got}、呼叫 {calls}")
    fetch, calls = F({D09: SEP23})
    bad = [occ.latest_published(p, u, fetch=fetch)
           for p, u in (("", "20260924"), ("20260923", "2026092"), ("20260231", "20260924"))]
    check("OCC 月報日期 p17 輸入不合法 → 無法確認、完全不抓",
          bad == [(None, "unknown")] * 3 and calls == [], f"得到 {bad}、呼叫 {calls}")

    # --- OCC 逐序列跟月報的說法矛盾 ---
    check("矛盾：逐檔跟 CBOE 一樣、月報卻說已經是下一天 → 擋",
          build._occ_contradiction(True, "20260922", "20260923") is True)
    check("矛盾：逐檔一樣、日期也一樣（CBOE 已經跟上）→ 不擋",
          build._occ_contradiction(True, "20260923", "20260923") is False)
    check("矛盾：量不到 CBOE 的日期（SPX）→ 不擋",
          build._occ_contradiction(True, None, "20260923") is False)
    check("矛盾：逐檔本來就不一樣 → 不擋",
          build._occ_contradiction(False, "20260921", "20260923") is False)

    check("結束碼 3＝來源停更（daily.yml 遇到它不重試）", build.EXIT_STALE == 3)


def quote_page_tests():
    """CDN 檔停更時的備援：Cboe 報價頁內嵌的 CTX.contextOptionsData。

    頁面的 timestamp 只有時分秒（UTC），要補上日期才能交給 snapshot_state 判斷換日；
    資料用 raw_decode 從標記後第一個「{」解一個物件就停。全部用假 HTML，不連網。
    """
    import json
    import cboe as _cboe
    U = dt.datetime

    check("報價頁時間：補上抓檔當天的日期",
          _cboe.complete_timestamp("15:19:21", U(2026, 9, 24, 15, 19, 44)) == "2026-09-24 15:19:21",
          "2026/09/24 實際存檔的那一份")
    check("報價頁時間：比抓檔時刻還晚＝跨過 UTC 午夜前的那份，日期往前一天",
          _cboe.complete_timestamp("23:59:50", U(2026, 9, 25, 0, 0, 5)) == "2026-09-24 23:59:50")
    check("報價頁時間：剛過午夜的那份維持當天",
          _cboe.complete_timestamp("00:00:03", U(2026, 9, 25, 0, 0, 5)) == "2026-09-25 00:00:03")
    check("報價頁時間：已經是完整格式就原樣",
          _cboe.complete_timestamp("2026-09-23 03:56:05", U(2026, 9, 25, 0, 0, 5)) == "2026-09-23 03:56:05")
    check("報價頁時間：空字串回空字串", _cboe.complete_timestamp("", U(2026, 9, 25, 0, 0, 5)) == "")

    data = {"timestamp": "15:19:21", "symbol": "^SPX",
            "data": {"symbol": "^SPX", "last_trade_time": "2026-09-24T11:04:19", "prev_day_close": 7706.0298,
                     "options": [{"option": "SPXW260925C07700000", "bid": 30.1, "ask": 30.4},
                                 {"option": "SPXW260925P07700000", "bid": 24.2, "ask": 24.5},
                                 {"option": "SPXW260925C07710000", "bid": 25.0, "ask": 25.3}]}}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = ("<html><head><script>\n"
            "        CTX.symbolBook = [{\"name\":\"A\",\"company_name\":\"x {y}\"}];\n"
            f"        CTX.contextOptionsData = {blob};\n"
            "        CTX.optionsOnFuturesSymbols = {\"ES\": 1};\n"
            "</script></head><body>…</body></html>")
    got = _cboe.page_payload(html, U(2026, 9, 24, 15, 19, 44))
    check("報價頁：取出內嵌資料、選擇權筆數正確",
          len(got.get("data", {}).get("options", [])) == 3 and got["data"]["prev_day_close"] == 7706.0298)
    check("報價頁：timestamp 已補成完整日期",
          got.get("timestamp") == "2026-09-24 15:19:21", str(got.get("timestamp")))
    check("報價頁：標記後面接著別的 script 也照樣只解一個物件",
          got.get("symbol") == "^SPX" and "optionsOnFuturesSymbols" not in got)
    try:
        _cboe.page_payload("<html><body>Service Unavailable</body></html>", U(2026, 9, 24, 15, 19, 44))
        no_mark = False
    except ValueError:
        no_mark = True
    check("報價頁：找不到 CTX.contextOptionsData → ValueError（頁面改版，結束碼 3）", no_mark)


def session_field_tests():
    """價格日不是買賣中價所屬的場次時，只准用 prev_close（build._session_price_field）。

    2026/09/24 Run #88 在美股盤中（美東 13:58）執行，SPX 剛好接近前一日收盤，
    「兩個都算、挑近的」選了盤中即時中價，做出「9/24 盤中報價＋9/23 未平倉」標成 9/23 的圖。
    全部用寫死的數字與假的報價檔狀態，不讀 data/。
    """
    import build
    import cboe as _cboe
    tol = _cboe.FWD_TOL

    def PK(field, pc, mid):
        cand = {"prev_close": dict(zip(("fwd", "rel", "n_pairs"), pc)),
                "mid": dict(zip(("fwd", "rel", "n_pairs"), mid))}
        f = cand.get(field) if field else None
        return {"field": field, "fwd": f["fwd"] if f else None, "rel": f["rel"] if f else None,
                "n_pairs": f["n_pairs"] if f else 0, "candidates": cand}

    M = (7702.30, -0.00048, 40)
    Q53 = PK("mid", (7710.19, 0.00054, 40), M)              # 本案：盤中中價剛好比較近
    FAR = PK("mid", (7760.0, 0.0070, 40), M)
    FEW = PK("mid", (7707.0, 0.00013, 3), M)
    NOPC = PK("mid", (None, None, 0), M)
    PCB = PK("prev_close", (7710.19, 0.00054, 40), (7760.0, 0.0070, 40))
    EIN = PK("mid", (7679.06, -0.0035, 40), M)              # 剛好等於容忍值 → 放行
    EOUT = PK("mid", (7733.77, 0.0036, 40), M)
    LIVE = {"opened": True, "session_over": False, "rolled": False}
    AFTER_NR = {"opened": True, "session_over": True, "rolled": False}
    ROLLED = {"opened": True, "session_over": True, "rolled": True}
    PRE = {"opened": False, "session_over": False, "rolled": False}

    for name, pick, st, use_prev, want in (
            ("m1 盤中、中價比較近（本案）→ 改用 prev_close", Q53, LIVE, True, ("prev_close", True)),
            ("m2 盤中、prev_close 偏太遠 → 不產出", FAR, LIVE, True, (None, True)),
            ("m3 盤中、prev_close 對數太少 → 不產出", FEW, LIVE, True, (None, True)),
            ("m4 盤中、prev_close 算不出來 → 不產出", NOPC, LIVE, True, (None, True)),
            ("m5 盤中、本來就選 prev_close → 照舊", PCB, LIVE, True, ("prev_close", True)),
            ("m6 盤中、prev_close 剛好等於容忍值 → 放行", EIN, LIVE, True, ("prev_close", True)),
            ("m7 盤中、prev_close 超過容忍值 → 不產出", EOUT, LIVE, True, (None, True)),
            ("m8 收盤後、prev_day_close 還沒換日 → 只用 prev_close", Q53, AFTER_NR, True, ("prev_close", True)),
            ("m9 收盤後已換日（台北早班）→ 中價可用", Q53, ROLLED, True, ("mid", False)),
            ("m10 新場次還沒開盤 → 中價仍是前一場次收盤、可用", Q53, PRE, True, ("mid", False)),
            ("m11 --live-price（看盤中結構）→ 不限制", Q53, LIVE, False, ("mid", False))):
        got = build._session_price_field(pick, st, use_prev, tol)
        check(f"盤中只用 prev_close：{name}", got == want, f"得到 {got}")

    S = lambda ts, ltt, close, pv, cur: {"timestamp": ts, "data": {
        "last_trade_time": ltt, "close": close, "prev_day_close": pv, "current_price": cur}}
    for name, payload, want in (
            ("m12 真實狀態：本案（美東 13:58 盤中）",
             S("2026-09-24 17:58:00", "2026-09-24T13:58:00", 7702.5, 7706.0298, 7702.5), ("prev_close", True)),
            ("m13 真實狀態：收盤後已換日（台北早班）",
             S("2026-09-25 04:30:00", "2026-09-24T16:15:00", 7700.0, 7700.0, 7700.0), ("mid", False)),
            ("m14 真實狀態：收盤後、prev_day_close 還沒換日",
             S("2026-09-24 20:05:00", "2026-09-24T16:00:00", 7700.0, 7706.0298, 7700.0), ("prev_close", True)),
            ("m15 真實狀態：新場次開盤前（盤前成交）",
             S("2026-09-25 12:15:00", "2026-09-25T08:15:00", None, 767.81, 768.2), ("mid", False))):
        got = build._session_price_field(Q53, _cboe.snapshot_state(payload), True, tol)
        check(f"盤中只用 prev_close：{name}", got == want, f"得到 {got}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--date")
    a = ap.parse_args()
    math_tests()
    print()
    chain_tests()
    print()
    cboe_snapshot_tests()
    print()
    oi_delta_tests()
    print()
    occ_tests()
    print()
    us_stall_tests()
    print()
    quote_page_tests()
    print()
    session_field_tests()
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
