#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台指選擇權曝險地圖 — 計算核心。

只用 Python 標準庫。所有數學與慣例都寫在 METHODOLOGY.md，
這裡的註解只說明「這段在算什麼」，不重複推導。

名詞:
  F   該到期別自己的遠期價（由結算價 put-call parity 反解），不用加權指數現貨
  M   TXO 契約乘數 = 50 元/點
  sign 造市商方向假設: 買權 +1、賣權 -1（見 METHODOLOGY.md 第 1 節，這是假設不是觀測）
"""
from __future__ import annotations

import bisect
import datetime as dt
import math
import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

M_TXO = 50.0            # 元 / 指數點
SQRT_2PI = math.sqrt(2.0 * math.pi)
TRADING_DAYS_PER_YEAR = 252.0

# --------------------------------------------------------------------------- 常態分佈

def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


# --------------------------------------------------------------------------- Black-76

def bs76(F: float, K: float, T: float, sigma: float, cp: str, df: float = 1.0) -> float:
    """歐式選擇權理論價（標的為遠期）。"""
    if T <= 0 or sigma <= 0 or F <= 0 or K <= 0:
        intrinsic = (F - K) if cp == "C" else (K - F)
        return df * max(intrinsic, 0.0)
    v = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    if cp == "C":
        return df * (F * norm_cdf(d1) - K * norm_cdf(d2))
    return df * (K * norm_cdf(-d2) - F * norm_cdf(-d1))


def greeks76(F: float, K: float, T: float, sigma: float, df: float = 1.0) -> Dict[str, float]:
    """回傳對「遠期」微分的 gamma / vega / vanna。買權賣權同 K 同 T 同 sigma 時三者相同。

      gamma = d2V/dF2          (每 1 指數點^2)
      vega  = dV/dsigma        (每 1.0 波動率, 例如 0.20 -> 20%)
      vanna = d2V/dF dsigma    (= dDelta/dsigma)
    """
    if T <= 0 or sigma <= 0 or F <= 0 or K <= 0:
        return {"gamma": 0.0, "vega": 0.0, "vanna": 0.0, "d1": 0.0, "d2": 0.0}
    v = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    pdf = norm_pdf(d1)
    return {
        "gamma": df * pdf / (F * v),
        "vega": df * F * pdf * math.sqrt(T),
        "vanna": -df * pdf * d2 / sigma,
        "d1": d1,
        "d2": d2,
    }


def implied_vol(price: float, F: float, K: float, T: float, cp: str,
                df: float = 1.0, lo: float = 1e-4, hi: float = 5.0,
                tol: float = 1e-8) -> Optional[float]:
    """由價格反解隱含波動率。

    先做無套利邊界檢查，再用「二分法保證收斂 + 牛頓法收尾」。
    不用純割線法: 深度價內時 f(sigma) 在低波動區幾乎是平的，割線會停滯，
    會解出 200%+ 的假波動率（這是本專案實際踩過的坑，見 METHODOLOGY.md 第 4 節）。
    """
    if price is None or T <= 0 or F <= 0 or K <= 0 or price <= 0:
        return None
    intrinsic = df * max((F - K) if cp == "C" else (K - F), 0.0)
    upper = df * (F if cp == "C" else K)
    if price <= intrinsic * (1.0 + 1e-12) + 1e-9:
        return None                      # 價格不高於內含值 -> 沒有時間價值可反解
    if price >= upper - 1e-9:
        return None

    a, b = lo, hi
    fa = bs76(F, K, T, a, cp, df) - price
    fb = bs76(F, K, T, b, cp, df) - price
    if fa > 0 or fb < 0:
        return None                      # 價格落在模型可達範圍之外

    for _ in range(60):                  # 二分: 5/2^60 遠超所需精度
        m = 0.5 * (a + b)
        fm = bs76(F, K, T, m, cp, df) - price
        if fm < 0:
            a, fa = m, fm
        else:
            b, fb = m, fm
        if (b - a) < 1e-7:
            break
    sigma = 0.5 * (a + b)

    for _ in range(6):                   # 牛頓收尾（vega 為導數）
        diff = bs76(F, K, T, sigma, cp, df) - price
        if abs(diff) < tol * max(1.0, price):
            break
        vega = greeks76(F, K, T, sigma, df)["vega"]
        if vega < 1e-10:
            break
        step = diff / vega
        nxt = sigma - step
        if not (lo < nxt < hi):
            break
        sigma = nxt
    return sigma if lo < sigma < hi else None


# --------------------------------------------------------------------------- 交易日 / 到期時間

def load_holidays(path: str) -> set:
    out = set()
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#")[0].strip()
            if not line:
                continue
            tok = line.split()[0].replace("-", "/")
            try:
                y, m, d = (int(x) for x in tok.split("/"))
                out.add(dt.date(y, m, d))
            except ValueError:
                continue
    return out


def trading_days_between(start: dt.date, end: dt.date, holidays: set) -> int:
    """(start, end] 之間的交易日數。start 當天不算，end 當天算。"""
    if end <= start:
        return 0
    n, cur = 0, start + dt.timedelta(days=1)
    while cur <= end:
        if cur.weekday() < 5 and cur not in holidays:
            n += 1
        cur += dt.timedelta(days=1)
    return n


def prev_trading_day(d: dt.date, holidays: set) -> dt.date:
    """d 之前最近的一個交易日（不含 d 自己）。"""
    cur = d - dt.timedelta(days=1)
    while cur.weekday() >= 5 or cur in holidays:
        cur -= dt.timedelta(days=1)
    return cur


def next_trading_day(d: dt.date, holidays: set) -> dt.date:
    cur = d + dt.timedelta(days=1)
    while cur.weekday() >= 5 or cur in holidays:
        cur += dt.timedelta(days=1)
    return cur


def time_to_expiry(trade_date: dt.date, last_trading_day: dt.date, holidays: set,
                   settle_next_day: bool = True) -> float:
    """T（年），以 252 交易日折算。最少給 0.2 個交易日，避免到期當日 gamma 發散。

    settle_next_day=True （台指選擇權）: 最終結算價在「最後交易日之次一營業日」
        開盤後 15 分鐘決定，所以把結算日也算進來。
    settle_next_day=False（SPY / QQQ）: PM 結算，最後交易日收盤即到期，不多算一天。
    """
    end = next_trading_day(last_trading_day, holidays) if settle_next_day else last_trading_day
    n = trading_days_between(trade_date, end, holidays)
    return max(n, 0.2) / TRADING_DAYS_PER_YEAR


# --------------------------------------------------------------------------- 遠期反解

def forward_from_parity(strikes: Dict[float, Dict[str, dict]], df: float = 1.0,
                        band: float = 0.03) -> Tuple[Optional[float], dict]:
    """由 put-call parity 反解遠期價: F = K + (C - P)/df。

    做法: 先用全部「買賣權結算價都有」的履約價算一次 F_k，取中位數當粗估，
    再只用粗估 +-band 內的價平附近履約價重算中位數（價平的 parity 最可信，
    深度價內外的結算價常是理論價、誤差被放大）。
    """
    cand = []
    for K, side in strikes.items():
        c = side.get("C", {}).get("settle")
        p = side.get("P", {}).get("settle")
        if c is None or p is None:
            continue
        cand.append((K, K + (c - p) / df))
    if not cand:
        return None, {"n": 0}

    def median(xs):
        xs = sorted(xs)
        n = len(xs)
        return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])

    rough = median([f for _, f in cand])
    near = [f for K, f in cand if abs(K / rough - 1.0) <= band]
    if len(near) < 3:
        near = [f for _, f in cand]
    F = median(near)
    spread = (max(near) - min(near)) if near else 0.0
    return F, {"n_all": len(cand), "n_near": len(near), "rough": rough,
               "near_spread": spread}


# --------------------------------------------------------------------------- 主計算

class Leg:
    """一個到期別 x 履約價 x 買賣權 的部位。"""
    __slots__ = ("exp", "K", "cp", "oi", "settle", "T", "iv", "gamma", "vega", "vanna")

    def __init__(self, exp, K, cp, oi, settle, T):
        self.exp, self.K, self.cp, self.oi, self.settle, self.T = exp, K, cp, oi, settle, T
        self.iv = self.gamma = self.vega = self.vanna = None


DEALER_SIGN = {"long_call_short_put": {"C": +1.0, "P": -1.0},
               "short_both": {"C": -1.0, "P": -1.0},
               "long_both": {"C": +1.0, "P": +1.0}}


def build_legs(chain: dict, trade_date: dt.date, holidays: set, df: float = 1.0,
               min_oi: int = 1, iv_floor: float = 0.01, iv_cap: float = 3.0,
               settle_next_day: bool = True, band: float = 0.03
               ) -> Tuple[List[Leg], Dict[str, dict]]:
    """chain: {exp: {"ltd": date, "strikes": {K: {"C": {...}, "P": {...}}}}}

    每個 (到期別, 履約價) 只反解「一個」隱含波動率，買權賣權共用:
      K < F 用賣權、K >= F 用買權（也就是價外那一側），失敗才退回另一側。
    理由: 價平價外的結算價才有真正的時間價值，深度價內的時間價值只有幾點，
    IV 對零點幾點的誤差極度敏感；而且 put-call parity 成立時兩邊本來就該同 IV。
    這樣做的副作用是 gamma_call == gamma_put，GEX 在單一履約價上就是
    gamma * (OI_call - OI_put) 的乾淨形式。

    回傳 (legs, 每個到期別的診斷)。
    """
    legs: List[Leg] = []
    diag: Dict[str, dict] = {}
    for exp, blk in chain.items():
        ltd = blk["ltd"]
        T = time_to_expiry(trade_date, ltd, holidays, settle_next_day)
        F, fdiag = forward_from_parity(blk["strikes"], df, band)
        if F is None or F <= 0:
            diag[exp] = {"ltd": ltd.isoformat(), "T": T, "F": None,
                         "skipped": "無法反解遠期價", **fdiag}
            continue
        n_ok = n_drop = 0
        n_otm = n_fallback = 0
        for K, side in blk["strikes"].items():
            oi_c = (side.get("C") or {}).get("oi") or 0
            oi_p = (side.get("P") or {}).get("oi") or 0
            if oi_c + oi_p < min_oi:
                continue
            prefer = "P" if K < F else "C"
            other = "C" if prefer == "P" else "P"
            iv = None
            used = None
            for cp in (prefer, other):
                rec = side.get(cp)
                if not rec or rec.get("settle") is None:
                    continue
                cand = implied_vol(rec["settle"], F, K, T, cp, df)
                if cand is not None and iv_floor <= cand <= iv_cap:
                    iv, used = cand, cp
                    break
            if iv is None:
                n_drop += oi_c + oi_p
                continue
            n_otm += 1 if used == prefer else 0
            n_fallback += 1 if used == other else 0
            g = greeks76(F, K, T, iv, df)
            for cp, oi in (("C", oi_c), ("P", oi_p)):
                if oi < 1:
                    continue
                rec = side.get(cp) or {}
                leg = Leg(exp, K, cp, oi, rec.get("settle"), T)
                leg.iv, leg.gamma, leg.vega, leg.vanna = iv, g["gamma"], g["vega"], g["vanna"]
                legs.append(leg)
                n_ok += oi
        diag[exp] = {"ltd": ltd.isoformat(), "T": round(T, 6), "F": round(F, 2),
                     "oi_used": n_ok, "oi_dropped": n_drop,
                     "iv_from_otm": n_otm, "iv_from_itm_fallback": n_fallback,
                     "trading_days": round(T * TRADING_DAYS_PER_YEAR, 1), **fdiag}
    return legs, diag


def skew_slope(legs: Sequence[Leg], exp: str, F: float) -> float:
    """該到期別在價平附近的 d(sigma)/d(lnK)，用價平 +-8% 內的腿做最小平方直線。

    用於 GEX+ 的 vanna 修正: 黏性 delta 下，現貨移動 dS/S 會讓固定履約價的
    隱含波動率變動 -slope * dS/S。
    """
    xs, ys = [], []
    for lg in legs:
        if lg.exp != exp or lg.iv is None:
            continue
        x = math.log(lg.K / F)
        if abs(x) > 0.08:
            continue
        xs.append(x)
        ys.append(lg.iv)
    n = len(xs)
    if n < 4:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den > 1e-12 else 0.0


def exposure_by_strike(legs: Sequence[Leg], S_ref: float, sign_mode: str,
                       bucket: int = 1, mult: float = M_TXO) -> List[dict]:
    """逐履約價（可分桶）的 GEX / VEX。

      GEX(K) = M * S^2 * 0.01 * sum(sign * gamma * OI)   -> 元 / 標的移動 1%
      VEX(K) = -M * S / 100  * sum(sign * vanna * OI)    -> 元 / 隱含波動率 1 個百分點

    VEX 用的是 **vanna**（dDelta/dsigma）不是 vega。理由見 METHODOLOGY.md 第 5 節:
    這張圖描述的是造市商被迫調整的避險流量，vega 講的是損益、vanna 才是流量。
    另外附上 vega 曝險（vex_vega）供參考，那是「多空波動率部位」的量。
    """
    sg = DEALER_SIGN[sign_mode]
    s2 = mult * S_ref * S_ref * 0.01
    sw = mult * S_ref / 100.0
    sv = mult / 100.0
    acc: Dict[int, dict] = {}
    for lg in legs:
        kb = int(round(lg.K / bucket) * bucket) if bucket > 1 else int(round(lg.K))
        a = acc.setdefault(kb, {"K": kb, "gex": 0.0, "vex": 0.0, "vex_vega": 0.0,
                                "oi_c": 0, "oi_p": 0, "iv_num": 0.0, "iv_den": 0.0})
        s = sg[lg.cp]
        a["gex"] += s * lg.gamma * lg.oi * s2
        a["vex"] += -s * lg.vanna * lg.oi * sw
        a["vex_vega"] += s * lg.vega * lg.oi * sv
        if lg.cp == "C":
            a["oi_c"] += lg.oi
        else:
            a["oi_p"] += lg.oi
        a["iv_num"] += lg.iv * lg.oi
        a["iv_den"] += lg.oi
    out = []
    for kb in sorted(acc):
        a = acc[kb]
        a["iv"] = (a["iv_num"] / a["iv_den"]) if a["iv_den"] else None
        a.pop("iv_num"); a.pop("iv_den")
        out.append(a)
    return out


def profile_curve(legs: Sequence[Leg], S_ref: float, forwards: Dict[str, float],
                  sign_mode: str, beta: float = 1.0,
                  lo_pct: float = -0.12, hi_pct: float = 0.12, n: int = 241,
                  mult: float = M_TXO
                  ) -> Tuple[List[float], List[float], List[float], List[float]]:
    """情境曲線: 把標的平移到 S，重算全簿的 GEX / VEX / GEX+。

    平移方式: 各到期別遠期同比例移動 F_e(S) = F_e * (S / S_ref)（保持基差比例），
    隱含波動率固定在今天反解出來的值（黏性履約價）。

      GEX(S)  = M * S^2 * 0.01 * sum(sign * gamma(S) * OI)
      VEX(S)  = -M * S / 100  * sum(sign * vanna(S) * OI)
      GEX+(S) = GEX(S) + beta * VEX(S)

    beta 的意思是「標的每移動 1%，隱含波動率反向變動 beta 個波動點」。
    beta = 0 時 GEX+ 退化成 GEX。回傳 (xs, gex, vex, gexp)。
    """
    sg = DEALER_SIGN[sign_mode]
    xs = [S_ref * (1.0 + lo_pct + (hi_pct - lo_pct) * i / (n - 1)) for i in range(n)]
    gex_c, vex_c, gexp_c = [], [], []
    for S in xs:
        ratio = S / S_ref
        g_sum = w_sum = 0.0
        for lg in legs:
            F = forwards[lg.exp] * ratio
            gk = greeks76(F, lg.K, lg.T, lg.iv)
            s = sg[lg.cp]
            g_sum += s * gk["gamma"] * lg.oi
            w_sum += s * gk["vanna"] * lg.oi
        gex = mult * S * S * 0.01 * g_sum
        vex = -mult * S / 100.0 * w_sum
        gex_c.append(gex)
        vex_c.append(vex)
        gexp_c.append(gex + beta * vex)
    return xs, gex_c, vex_c, gexp_c


def zero_crossings(xs: Sequence[float], ys: Sequence[float]) -> List[float]:
    """線性內插求所有零交叉點。"""
    out = []
    for i in range(len(xs) - 1):
        y0, y1 = ys[i], ys[i + 1]
        if y0 == 0.0:
            out.append(xs[i])
        elif y0 * y1 < 0:
            t = y0 / (y0 - y1)
            out.append(xs[i] + t * (xs[i + 1] - xs[i]))
    return out


def pick_flip(xs, ys, S_ref: float) -> Optional[float]:
    """挑最靠近現貨的零交叉點當翻轉點。"""
    cs = zero_crossings(xs, ys)
    if not cs:
        return None
    return min(cs, key=lambda x: abs(x - S_ref))
