#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 SPX 的曝險結構換算到 ES（小S&P 期貨）的價格刻度。

【為什麼要這個】客戶能做的是 ES／MES 的日選，但他們看的價位是**期貨**的價位；
SPX 的履約價是**現貨指數**的價位，兩者差一個期貨基差。同一道牆，在 SPX 講是
7,700、在 ES 講是 7,762，差了六十幾點——直接拿 SPX 的數字去看 ES 會整排錯位。

【為什麼換算得出來，而且不需要 CME 的資料】
ES 選擇權的標的是「最近到期的季月 ES 期貨」（CME 的 FAQ 講得很明確），
而期貨價格就是**遠期價格**。遠期價格我們本來就在算——`build.py` 對每個到期日
都用 put-call parity 從 SPX 選擇權自己反解出遠期，那是只由選擇權報價決定的東西。
所以只要取「對到 ES 季月到期日」的那個遠期，就等於拿到了 ES 的期貨價格。

  ratio = F(季月) / S(現貨)        ES 價位 ≈ SPX 價位 × ratio

【為什麼是乘不是加】基差 ≈ S×(r−q)×T 會隨價位等比例變化。用加的，在離價平 8%
的履約價上會差五點左右；用乘的則**所有價內外關係（K/F）完全保持不變**，
IV、gamma、skew、flip 全部自動保持一致，不必重算任何希臘字母。

【這張圖是什麼、不是什麼】
  是：**SPX 市場的 gamma／vanna 結構，用 ES 的價格刻度表示**。
  不是：ES 自己那些選擇權的結構。ES 有自己的未平倉，履約價落在整數的 ES 點位，
       分佈不一樣。
  金額（百萬美元）仍然是 **SPX 部位的金額**（乘數 ×$100），沒有換算成 ES 的
  ×$50——換算金額會讓人以為那是 ES 的曝險，那是錯的。
把 SPX 的結構拿來看 ES 是有道理的：SPX＋SPXW 的未平倉是 ES 的四倍上下，
整個 S&P 複合體的 gamma 主要是那一池在推。但它終究是「別人的部位畫在你的刻度上」。

【基差不是固定的】每到季月換倉（3／6／9／12 的第三個星期五）會跳一階，
平常隨著逼近到期慢慢收斂到 0。所以每天都要重算，不可以寫死一個數字。
2026/09/18 就是換倉日：Sep 到期、front 換成 Dec，基差當天跳了一整季的持有成本。
"""
from __future__ import annotations

import copy
import datetime as dt
from typing import Optional, Tuple

QUARTER_MONTHS = (3, 6, 9, 12)


def third_friday(year: int, month: int) -> dt.date:
    """某年某月的第三個星期五（ES 季月期貨的最後交易日）。"""
    d = dt.date(year, month, 15)
    while d.weekday() != 4:                      # 4 = 星期五
        d += dt.timedelta(days=1)
    return d


def quarterly_ltd(after: dt.date) -> dt.date:
    """`after` 之後最近一個還沒到期的 ES 季月最後交易日。

    用嚴格大於：季月到期當天，front 就換成下一個季月了
    （我們的鏈本來也會把當日到期的排除掉）。
    """
    for y in (after.year, after.year + 1):
        for m in QUARTER_MONTHS:
            d = third_friday(y, m)
            if d > after:
                return d
    raise ValueError(f"找不到 {after} 之後的季月")


def find_quarter_expiry(payload: dict, q: dt.date) -> Optional[dict]:
    """在 SPX 的到期別裡找出季月那一檔。

    **要用 code 不能用 ltd。** SPX 的 AM 結算（第三個星期五「開盤」以 SET 結算）
    在我們的資料裡 ltd 已經被往前挪了一個交易日，用 ltd 找會找不到、或找到
    隔壁那檔 PM 的。code 保留的是原始到期日（例如 20261218A / 20261218）。
    ES 期貨的最後結算也是用第三個星期五的 SOQ，跟 SPX 的 AM 是同一個東西，
    所以**優先取 A（AM）那一檔**，沒有才退回 PM。
    """
    key = q.strftime("%Y%m%d")
    cands = [e for e in (payload.get("expiries") or [])
             if str(e.get("code", "")).startswith(key) and e.get("F")]
    if not cands:
        return None
    cands.sort(key=lambda e: 0 if str(e["code"]).endswith("A") else 1)
    return cands[0]


# 季月到期前這麼多天（日曆日）之內，就要把「換倉中」講出來。
#
# 【為什麼不自己挑一個換倉日——2026/08/21~09/16 拿真的 CME 結算價比對過】
# 用日曆規則（下一個還沒到期的季月）算出來的價，跟 CME 實際的主力月結算價比：
#   ・離季月還有 7 天以上的 11 天：平均差 −0.08 點、標準差 6.3 點、最大 12 點，
#     沒有系統性偏差——方法是對的，殘差就是選擇權買賣價差的寬度。
#   ・剩 4 / 3 / 2 天那三天：差 −10 / −73 / −88 點。**不是算錯，是指到不同的契約**
#     ——我們算 9 月，市場的未平倉已經滾到 12 月了。
# 那三天的交叉點落在剩 3 天，但 CME 公告的換倉慣例是到期前 8 天，兩者對不起來，
# 而且我只有兩天的樣本。**只有兩個樣本就挑一個門檻，就是「先假設再寫防線」**，
# 所以不挑：日曆規則照用（那是 CME 對「標的是哪一口」的定義），
# 但在換倉窗口裡把**兩個季月都算出來**交給看的人自己判斷。
ROLL_WARN_DAYS = 14


def ratio_of(payload: dict, session: dt.date = None):
    """回傳 (ratio, 用到的季月到期別, 季月最後交易日, 換倉資訊或 None)。"""
    if session is None:
        td = (payload.get("meta") or {}).get("trade_date", "")
        y, m, d = (int(x) for x in td.replace("-", "/").split("/"))
        session = dt.date(y, m, d)
    q = quarterly_ltd(session)
    e = find_quarter_expiry(payload, q)
    if not e:
        raise ValueError(f"SPX 的鏈裡找不到季月 {q}（換算不出 ES 的價格刻度）")
    S = (payload.get("meta") or {}).get("s_ref")
    if not S or S <= 0:
        raise ValueError("SPX 沒有現貨價，換算不出比例")
    roll = None
    left = (q - session).days
    if left <= ROLL_WARN_DAYS:
        q2 = quarterly_ltd(q)
        e2 = find_quarter_expiry(payload, q2)
        if e2:
            roll = {"days_left": left, "next_quarter": quarter_code(q2),
                    "next_ltd": q2.strftime("%Y/%m/%d"),
                    "next_ratio": e2["F"] / S,
                    "next_basis": round(e2["F"] - S, 2)}
    return e["F"] / S, e, q, roll


def quarter_code(q: dt.date) -> str:
    return "ES" + "HMUZ"[QUARTER_MONTHS.index(q.month)] + str(q.year % 100)


def derive(payload: dict, session: dt.date = None) -> dict:
    """產出換算後的 payload。只動價格類欄位，其餘原封不動。"""
    r, qe, q, roll = ratio_of(payload, session)
    out = copy.deepcopy(payload)
    m = out["meta"]
    S0 = m["s_ref"]

    m["s_ref"] = round(S0 * r, 2)
    for e in out.get("expiries") or []:
        if e.get("F"):
            e["F"] = round(e["F"] * r, 2)
    for v in (out.get("views") or {}).values():
        for s in v.get("strikes") or []:
            s["K"] = round(s["K"] * r, 2)
        c = v.get("curve") or {}
        if c.get("x"):
            c["x"] = [round(x * r, 2) for x in c["x"]]

    code = quarter_code(q)
    m.update({
        "symbol": "ES",
        "label": "ES 換算",
        "desc": "SPX 選擇權的曝險結構，換算到 ES（小S&P 期貨）的價格刻度",
        "s_label": "期貨",
        "s_ref_source": f"SPX 現貨 × 遠期比（{code}，{q:%Y/%m/%d} 到期）",
        "source": "由 SPX 換算（CBOE 報價 ＋ OCC 未平倉）；**不是 CME 的資料**",
        "derived_from": "SPX",
        "derived_note": (
            "這是 **SPX 市場的結構畫在 ES 的刻度上**，不是 ES 自己那些選擇權的結構。"
            "金額仍是 SPX 部位的金額（乘數 ×$100），沒有換成 ES 的 ×$50。"),
        "es_ratio": r,
        "es_basis": round(m["s_ref"] - S0, 2),
        "es_quarter": code,
        "es_quarter_ltd": q.strftime("%Y/%m/%d"),
        "es_spx_spot": S0,
        "es_roll": roll,
    })
    return out
