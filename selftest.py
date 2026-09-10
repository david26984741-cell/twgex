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

    # --- 掉系列的守門（ES 2026/09/05~07 連三天）---
    _bb = __import__('build')
    class _S:
        allow_stale_oi = False
    class _S2(_S):
        allow_stale_oi = True
    def _try(meta, args=None):
        try:
            _bb._cme_series_guard(args or _S(), 'ES', meta)
            return None
        except SystemExit as e:
            return str(e)
    # 09/07 的真實比例：只抓到 8.6% 的部位 → 系列也掉了大半
    r = _try({'n_series': 59, 'n_series_lost': 51, 'lost_codes': ['EW1U26', 'EW2U26']})
    check('問不到的太多會被擋下來', r is not None and '86.4%' in r, (r or '')[:70])
    # 掉一兩個是常態，要放行
    r = _try({'n_series': 59, 'n_series_lost': 4, 'lost_codes': ['EW1U26']})
    check('只有少數問不到照樣產出', r is None, '4/59 = 6.8%，在 10% 門檻內')
    # 【2026/09/08 的真實反例】87 個系列裡 21 個「問到了但還沒有結算資料」
    # （2028 季月、2026/10~12 與 2027/10 的週選，都還沒開始交易）。
    # 第一版把這種也算成失敗，門檻 10%，結果把完全健康的一輪擋掉三次。
    r = _try({'n_series': 87, 'n_series_lost': 0, 'n_series_empty': 21, 'empty_codes': ['ESU28']})
    check('「還沒開始交易」的空系列不算失敗', r is None,
          '87 個裡 21 個是空的（24%），照樣要產出')
    # 空的很多、同時真的有幾個問不到 → 只看問不到的那幾個
    r = _try({'n_series': 87, 'n_series_lost': 5, 'n_series_empty': 21, 'lost_codes': ['EWU26']})
    check('空系列不會把問不到的比例灌大', r is None, '5/87 = 5.7%，在門檻內')
    # 空的太多＝CME 還沒發布這一天的結算（跟「問不到」是不同的失敗）
    r = _try({'n_series': 87, 'n_series_lost': 0, 'n_series_empty': 70, 'trade_day': '20260907'})
    check('空得太多會判成「CME 還沒發布」', r is not None and '還沒發布' in r and '80%' in r,
          (r or '')[:80])
    r = _try({'n_series': 87, 'n_series_lost': 0, 'n_series_empty': 43})
    check('剛好 50% 不擋', r is None, '43/87 = 49.4%')
    # 錯誤訊息要被帶出來（之後查是逾時還是被擋）
    r = _try({'n_series': 87, 'n_series_lost': 40, 'lost_codes': ['EWU26'],
              'lost_errors': ['EWU26: CME 讀取失敗 /CmeWS/...: timed out']})
    check('擋下來時會附上失敗原因', r is not None and 'timed out' in r, (r or '')[-60:])
    # 剛好在門檻上
    r = _try({'n_series': 100, 'n_series_lost': 10, 'lost_codes': []})
    check('剛好 10% 不擋', r is None, '門檻是「超過 10%」才擋')
    r = _try({'n_series': 100, 'n_series_lost': 11, 'lost_codes': []})
    check('超過 10% 就擋', r is not None)
    # 一個都沒掉
    r = _try({'n_series': 59, 'n_series_lost': 0, 'lost_codes': []})
    check('一個都沒掉時不吭聲', r is None)
    # --json 餵檔的舊路徑沒有這些欄位，不可以因此炸掉
    r = _try({'n_contracts_all': 100})
    check('舊路徑（--json）沒有系列計數時不擋', r is None)
    # 強制放行
    r = _try({'n_series': 59, 'n_series_lost': 51, 'lost_codes': []}, _S2())
    check('加了 --allow-stale-oi 可以強行放行（掉系列）', r is None)

    # --- CME 邊緣節點限流：回 HTTP 200 但 settlements 是空的 -------------
    # 【2026/09/09~10 的真實反例】同一個 trade_day、同一份程式碼連跑六輪，
    # 「沒有結算資料」的系列數是 50 → 55 → 62 → 76 → 55 → 80，行事曆本身
    # 也在 87 ↔ 82 之間跳。輸入一樣、結果每次不同，就不可能是「還沒發布」。
    import cme as _cme

    def _calendar(codes, pids=(9, 11)):
        return [{"optionType": "EUR", "name": "Weekly Friday",
                 "productIds": list(pids),
                 "calendarEntries": [{"productCode": c, "lastTrade": "18 Dec 2026",
                                      "contractMonth": "DEC 26"} for c in codes]}]

    def _settle_rows():
        return {"settlements": [{"strike": "7700", "type": "Call", "settle": "50.0",
                                 "openInterest": "1000", "volume": "10", "last": "50.0"},
                                {"strike": "7700", "type": "Put", "settle": "40.0",
                                 "openInterest": "900", "volume": "8", "last": "40.0"}]}

    class _Stub:
        """假的 CME。可以指定行事曆每次回幾筆、哪些系列這一遍回空的。"""
        def __init__(self, cals, empty_passes, good_pid=11):
            self.cals = list(cals)          # 每次要行事曆回哪一份
            self.empty_passes = empty_passes  # code -> 前幾遍要回空的
            self.good_pid = good_pid
            self.n_cal = 0
            self.n_oof = 0
            self.seen = {}                  # code -> 已經被問過幾遍
        def get(self, path, params=None, **kw):
            if "ProductCalendar" in path:
                c = self.cals[min(self.n_cal, len(self.cals) - 1)]
                self.n_cal += 1
                return c
            if "/FUT" in path:
                return {"settlements": [{"month": "DEC 26", "settle": "7700.0",
                                         "openInterest": "1000000"}]}
            if "/OOF" in path:
                self.n_oof += 1
                pid = int(path.split("/")[-2])
                code = (params or {}).get("monthYear")
                if pid != self.good_pid:
                    return {"settlements": []}      # 錯的 pid：回空
                n = self.seen.get(code, 0)
                self.seen[code] = n + 1
                if n < self.empty_passes.get(code, 0):
                    return {"settlements": []}      # 被限流：HTTP 200 但內容是空的
                return _settle_rows()
            return {}

    def _with_stub(stub, fn):
        og, ov = _cme._get, _cme.fetch_volume_oi
        _cme._get = stub.get
        _cme.fetch_volume_oi = lambda pid, code, td, wm="", rt="": (
            {("C", 7700.0): (1234, 0), ("P", 7700.0): (1111, 0)}, "F")
        try:
            return fn()
        finally:
            _cme._get, _cme.fetch_volume_oi = og, ov

    # 行事曆殘缺時取聯集，不能只信一次的結果
    st = _Stub([_calendar(["A26", "B26"]), _calendar(["A26", "B26", "C26", "D26"])], {})
    ser = _with_stub(st, lambda: _cme.list_series("ES"))
    check("行事曆問兩次取聯集，殘的那份不會決定分母",
          len(ser) == 4, f"第一次 2 筆、第二次 4 筆 → 聯集 {len(ser)} 筆")

    # 同一個 type 底下的系列共用 pid，記住上一個成功的那個就不用每次試錯
    codes = [f"E{i}26" for i in range(10)]
    st = _Stub([_calendar(codes)], {})
    ch, mt = _with_stub(st, lambda: _cme.fetch_chain(
        "20260910", "ES", pause=0, retry_waits=()))
    check("記住上一次成功的 pid，不用每個系列都從頭試錯",
          st.n_oof == 11, f"10 個系列只打了 {st.n_oof} 個結算請求（不記的話是 20）")

    # 限流：昨天有的系列今天空手 → 補抓要把它撈回來
    st = _Stub([_calendar(codes)], {"E026": 1, "E526": 1, "E726": 2})
    ch, mt = _with_stub(st, lambda: _cme.fetch_chain(
        "20260910", "ES", pause=0, known_live=set(codes), retry_waits=(0, 0, 0)))
    check("被限流回空的系列會被補抓回來",
          mt["n_recovered"] == 3 and mt["n_known_missing"] == 0,
          f"補回 {mt['n_recovered']} 個、還缺 {mt['n_known_missing']} 個")
    check("補抓回來的系列真的有進到鏈裡", len(ch) == 10, f"{len(ch)} 個到期別")

    # 昨天沒有的系列（還沒開始交易的遠月）永遠是空的，不該去補抓它
    st = _Stub([_calendar(codes)], {c: 99 for c in codes[6:]})
    ch, mt = _with_stub(st, lambda: _cme.fetch_chain(
        "20260910", "ES", pause=0, known_live=set(codes[:6]), retry_waits=(0, 0, 0)))
    check("『還沒開始交易』的空系列不會被反覆補抓",
          mt["n_known_missing"] == 0 and mt["n_series_empty"] == 4 and mt["n_recovered"] == 0,
          f"空 {mt['n_series_empty']} 個、基準缺 {mt['n_known_missing']} 個")

    # 昨天有的幾乎全滅＝這一場次還沒發布，補抓只是白打請求，不做
    st = _Stub([_calendar(codes)], {c: 99 for c in codes})
    base = None
    ch, mt = _with_stub(st, lambda: _cme.fetch_chain(
        "20260910", "ES", pause=0, known_live=set(codes), retry_waits=(0, 0, 0)))
    check("昨天有的全滅時不補抓（那是還沒發布，重打只會養深限流）",
          st.n_oof == 20 and mt["n_recovered"] == 0 and mt["n_known_missing"] == 10,
          f"只打了 {st.n_oof} 個請求（補抓的話會多打幾十個）")

    # --- 有前一天可比時，門檻改看「昨天有、今天沒有」---------------------
    # 昨天有 60 個、今天缺 20 個 → 擋，而且要說是限流不是還沒發布
    r = _try({'n_series': 87, 'n_series_lost': 0, 'n_series_empty': 41,
              'n_known_live': 60, 'n_known_missing': 20,
              'known_missing_codes': ['EW1U26'], 'trade_day': '20260909'})
    check('昨天有、今天缺了三分之一會被擋下來',
          r is not None and '限流' in r and '33%' in r, (r or '')[:80])
    check('缺一部分時不會誤報成「還沒發布」', r is not None and '還沒發布' not in r)
    # 昨天有的全滅 → 訊息要改口說是還沒發布
    r = _try({'n_series': 87, 'n_series_lost': 0, 'n_series_empty': 87,
              'n_known_live': 60, 'n_known_missing': 60, 'trade_day': '20260909'})
    check('昨天有的全滅時判成「CME 還沒發布」',
          r is not None and '還沒發布' in r, (r or '')[:80])
    # 【這是這次改動的重點】空的很多、但昨天有的一個都沒缺 → 照樣產出。
    # 舊的 empty/n > 50% 那一條會把這種健康的一輪擋掉。
    r = _try({'n_series': 87, 'n_series_lost': 0, 'n_series_empty': 70,
              'n_known_live': 60, 'n_known_missing': 0, 'trade_day': '20260909'})
    check('空的再多，只要昨天有的都在就照樣產出', r is None,
          '70/87 是空的，但那 70 個昨天本來就沒有')
    # 缺一兩個是常態
    r = _try({'n_series': 87, 'n_series_lost': 0, 'n_series_empty': 24,
              'n_known_live': 60, 'n_known_missing': 3, 'trade_day': '20260909'})
    check('昨天有的缺個位數照樣產出', r is None, '3/60 = 5%，剛好在門檻上')
    r = _try({'n_series': 87, 'n_series_lost': 0, 'n_series_empty': 25,
              'n_known_live': 60, 'n_known_missing': 4, 'trade_day': '20260909'})
    check('超過 5% 就擋', r is not None)
    # 沒有基準時（第一次建置）退回舊的粗篩
    r = _try({'n_series': 87, 'n_series_lost': 0, 'n_series_empty': 70,
              'n_known_live': 0, 'trade_day': '20260909'})
    check('沒有前一天可比時，退回舊的 empty/n 粗篩', r is not None and '還沒發布' in r)
    # 強制放行
    r = _try({'n_series': 87, 'n_series_lost': 0, 'n_series_empty': 41,
              'n_known_live': 60, 'n_known_missing': 20}, _S2())
    check('加了 --allow-stale-oi 可以強行放行（基準缺件）', r is None)

    # --- 「昨天有哪些系列」這個基準怎麼撈出來的 -------------------------
    import tempfile as _tf, json as _js, os as _os2, shutil as _sh
    _tmp = _tf.mkdtemp()
    _os2.makedirs(_os2.path.join(_tmp, "ES", "history"))
    _old_data = _bb.DATA
    def _write(name, trade_date, exps):
        p = (_os2.path.join(_tmp, "ES", "history", name + ".json") if name
             else _os2.path.join(_tmp, "ES", "latest.json"))
        with open(p, "w", encoding="utf-8") as fh:
            _js.dump({"meta": {"trade_date": trade_date},
                      "expiries": [{"code": c, "ltd": l} for c, l in exps]}, fh)
    try:
        _bb.DATA = _tmp
        _write("20260909", "2026/09/09",
               [("EW1U26", "2026-09-11"), ("E2AU26", "2026-09-10"),
                ("OLDU26", "2026-09-09"), ("ESZ26", "2026-12-18")])
        kl = _bb._cme_known_live("ES", "20260910")
        check("基準只留下今天之後才到期的系列",
              kl == {"EW1U26", "ESZ26"},
              f"{sorted(kl)}（09-10 當天到期的 E2AU26 與 09-09 就到期的 OLDU26 要被濾掉）")
        # 只有 latest.json、沒有 history 也要能當基準
        _os2.remove(_os2.path.join(_tmp, "ES", "history", "20260909.json"))
        _write(None, "2026/09/09", [("EW1U26", "2026-09-11")])
        check("沒有 history 時退回 latest.json",
              _bb._cme_known_live("ES", "20260910") == {"EW1U26"})
        # 檔裡就是今天（重跑同一天）→ 不能拿自己當基準
        _write(None, "2026/09/10", [("EW1U26", "2026-09-11")])
        check("重跑同一天時不拿自己當基準",
              _bb._cme_known_live("ES", "20260910") == set(),
              "拿自己比的話永遠不缺，這一關就等於沒有")
        # 沒有任何檔 → 空集合，退回舊的粗篩，不可以炸掉
        _bb.DATA = _os2.path.join(_tmp, "nope")
        check("第一次建置沒有檔時回空集合", _bb._cme_known_live("ES", "20260910") == set())
    finally:
        _bb.DATA = _old_data
        _sh.rmtree(_tmp, ignore_errors=True)

    # --- 看門狗：兩個訊號各自擋得住什麼 ---------------------------------
    import importlib.util as _ilu, datetime as _dt2, os as _os
    import tempfile as _tf, os as _os2, shutil as _sh
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
    check("【真實反例】ES 停兩天，但撞到勞動節就剛好卡在門檻上不會叫",
          lag == 2 and lag <= _wd.LAG_MAX_DEFAULT,
          f"落後 {lag}、門檻 {_wd.LAG_MAX_DEFAULT} → 資料日這個訊號叫不出來")
    # 同一個時點，排程那個訊號當場就叫（#23、#24 連續失敗）
    ok, desc = _wd.judge_runs([(24, "failure"), (23, "failure")])
    check("【真實反例】同一個時點，連續兩次排程失敗會叫",
          ok is False and "連續失敗" in desc, desc)

    ok, _ = _wd.judge_runs([(25, "success"), (24, "failure")])
    check("失敗一次之後自己救回來就不叫", ok is True, "最近一次成功＝它恢復了")
    ok, _ = _wd.judge_runs([(24, "failure"), (23, "success")])
    check("只有最近一次失敗不叫（單次抖動）", ok is True)
    ok, _ = _wd.judge_runs([(24, "timed_out"), (23, "failure")])
    check("逾時也算失敗", ok is False)
    ok, d2 = _wd.judge_runs([(24, "failure")])
    check("紀錄不足兩次時不判斷（新 repo / 剛改完 workflow）", ok is True, d2)
    ok, _ = _wd.judge_runs([])
    check("完全沒有排程紀錄時不判斷", ok is True)

    # 門檻要跟網站上那則紅字提醒一致，不然兩邊會各講各話
    check("看門狗的門檻跟 app.js 的 staleNotice 一致",
          _wd.LAG_MAX.get("TXO") == 1 and _wd.LAG_MAX_DEFAULT == 2,
          "台指 >1、美股四檔 >2")
    check("五個標的都在看門狗的名單裡",
          {s[0] for s in _wd.SYMBOLS} == {"TXO", "SPX", "ES", "SPY", "QQQ"})
    check("台指看台北、美股看美東",
          dict((s[0], s[2]) for s in _wd.SYMBOLS)["TXO"] == 8
          and dict((s[0], s[2]) for s in _wd.SYMBOLS)["ES"] == -5)

    # 資料檔壞掉 / 不見時要當成失敗，不可以安靜略過
    _t2 = _tf.mkdtemp()
    try:
        _os2.makedirs(_os2.path.join(_t2, "data", "TXO"))
        open(_os2.path.join(_t2, "calendar_tw.txt"), "w").write("")
        open(_os2.path.join(_t2, "calendar_us.txt"), "w").write("")
        r = dict((x[0], x) for x in _wd.check_data(_t2))
        check("latest.json 不見時判成失敗", r["ES"][4] is False, r["ES"][5])
        with open(_os2.path.join(_t2, "data", "TXO", "latest.json"), "w") as fh:
            fh.write("{ 壞掉的 json")
        r = dict((x[0], x) for x in _wd.check_data(_t2))
        check("latest.json 壞掉時判成失敗，不是當作沒事",
              r["TXO"][4] is False, r["TXO"][5][:40])
    finally:
        _sh.rmtree(_t2, ignore_errors=True)

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


    # 2026/09/01 踩到：EW3M28（很遠的週選）未平倉是 0，卻被算成
    # 「占總未平倉 100.00%（0 / 0 口）」，ES 整批不產出。
    # 兩個成因都修了：fetch_chain 現在會給 oi_total，guard 也不再把「0 口」當成 100%。
    check("退回的系列一口部位都沒有時不該擋",
          _guard_ok(_A(), {"oi_fellback": 1, "oi_fellback_oi": 0, "oi_total": 0,
                           "oi_fellback_codes": ["EW3M28"]}),
          "0 / 0 不是 100%，是「沒有東西被弄舊」")
    check("oi_total 有值、退回 0 口，一樣放行",
          _guard_ok(_A(), {"oi_fellback": 1, "oi_fellback_oi": 0, "oi_total": 500_000,
                           "oi_fellback_codes": ["X"]}))
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
    print()
    occ_tests()
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
