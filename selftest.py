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
    check("沒給 am_roots 時維持 SPY / QQQ 的原本行為",
          set(plain) == {"20260918", "20260824"}, str(sorted(plain)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--date")
    a = ap.parse_args()
    math_tests()
    print()
    chain_tests()
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
