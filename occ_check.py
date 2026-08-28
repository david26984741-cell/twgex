#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拿 OCC 的逐履約價未平倉跟 CBOE 那份檔案逐檔對照。

為什麼要做這件事
----------------
OCC 在交易日**當天傍晚**（美東約 20:00）就把逐履約價的未平倉發出來，
CBOE 的 delayed_quotes 檔卻要**隔天早上**（美東 10:00~10:30）才跟上——差十幾個小時。
如果兩邊的數字逐檔對得起來，美股三檔就能改用 OCC 當未平倉來源，
價格繼續取 CBOE 的 prev_day_close，整張圖可以提前十幾個小時上線。

比對的時點很重要
----------------
排在台北 22:30（美東 10:30）跑：那時 CBOE 剛更新到前一個交易日 D，
而 OCC 從 D 當天傍晚起就是 D——**兩邊同時都是 D**，可以直接同一時刻對照，
不需要存快照隔天再比。

這支程式只讀不寫，不影響任何產出；壞掉也只是少一份報告。

    python occ_check.py --symbols SPX SPY QQQ
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from collections import defaultdict
from typing import Dict, Tuple

OCC = "https://marketdata.theocc.com/series-search?symbolType=U&symbol={sym}"
UA = "Mozilla/5.0 (compatible; twgex/1.0)"

# 每個標的要留哪些根碼。開頭是數字的（2SPX、4QQQ…）是公司行為調整過的序列，
# 履約價與乘數都不一樣，本來就不進圖，這裡也一律排除。
ROOTS = {"SPX": ("SPX", "SPXW"), "SPY": ("SPY",), "QQQ": ("QQQ",)}


def fetch_occ(sym: str, timeout: int = 120) -> str:
    req = urllib.request.Request(OCC.format(sym=sym), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def parse_occ(text: str, keep: Tuple[str, ...]) -> Dict[Tuple[str, float, str], int]:
    """欄位：0 根碼 1 空 2 年 3 月 4 日 5 履約價整數 6 小數 7 C/P 8 買權OI 9 賣權OI 10 部位限額

    注意根碼後面有兩個 tab，欄位很容易整排錯開一格——這裡用欄數與內容再確認一次。
    """
    out: Dict[Tuple[str, float, str], int] = {}
    for ln in text.split("\n"):
        c = ln.rstrip("\n").split("\t")
        if len(c) < 10:
            continue
        root = c[0].strip()
        if root not in keep:
            continue
        y, m, d = c[2].strip(), c[3].strip(), c[4].strip()
        if not (y.isdigit() and m.isdigit() and d.isdigit()):
            continue
        whole, dec = c[5].strip(), c[6].strip()
        if not whole.isdigit():
            continue
        K = int(whole) + (int(dec) / 1000.0 if dec.isdigit() else 0.0)
        exp = f"{y}{m.zfill(2)}{d.zfill(2)}"
        for cp, col in (("C", 8), ("P", 9)):
            v = c[col].strip()
            if v.isdigit():
                out[(exp, round(K, 3), cp)] = int(v)
    return out


def parse_cboe(payload: dict) -> Dict[Tuple[str, float, str], int]:
    out: Dict[Tuple[str, float, str], int] = {}
    for o in (payload.get("data") or {}).get("options") or []:
        code = o.get("option") or ""
        if len(code) < 16:
            continue
        exp = "20" + code[-15:-9]
        cp = code[-9]
        K = int(code[-8:]) / 1000.0
        out[(exp, round(K, 3), cp)] = int(o.get("open_interest") or 0)
    return out


def compare(sym: str) -> None:
    import cboe

    keep = ROOTS.get(sym, (sym,))
    occ = parse_occ(fetch_occ(sym), keep)
    cbo = parse_cboe(cboe.fetch_json("_SPX" if sym == "SPX" else sym))

    both = set(occ) & set(cbo)
    same = [k for k in both if occ[k] == cbo[k]]
    diff = [k for k in both if occ[k] != cbo[k]]
    # 只看有部位的：0 對 0 沒有資訊量
    live = [k for k in both if occ[k] > 0 or cbo[k] > 0]
    live_same = [k for k in live if occ[k] == cbo[k]]

    occ_only = [k for k in set(occ) - set(cbo) if occ[k] > 0]
    cbo_only = [k for k in set(cbo) - set(occ) if cbo[k] > 0]

    tot_occ = sum(occ.values())
    tot_cbo = sum(cbo.values())

    print(f"### {sym}")
    print("")
    print(f"- 共同的合約 **{len(both):,}**；其中有部位的 **{len(live):,}**")
    pct = (len(live_same) / len(live) * 100) if live else 0.0
    print(f"- 有部位的裡面逐檔完全相同 **{len(live_same):,} / {len(live):,}（{pct:.2f}%）**")
    print(f"- 未平倉合計：OCC **{tot_occ:,}** ／ CBOE **{tot_cbo:,}** "
          f"（差 {tot_occ - tot_cbo:+,}）")
    print(f"- 只有一邊有的（且有部位）：OCC 獨有 {len(occ_only):,}、CBOE 獨有 {len(cbo_only):,}")

    if diff:
        d = sorted(diff, key=lambda k: -abs(occ[k] - cbo[k]))
        print("")
        print(f"- 逐檔不同的有 **{len(diff):,}** 個，差距最大的前 8 個：")
        print("")
        print("| 到期 | 履約價 | C/P | OCC | CBOE | 差 |")
        print("|---|---|---|---|---|---|")
        for k in d[:8]:
            print(f"| {k[0]} | {k[1]:g} | {k[2]} | {occ[k]:,} | {cbo[k]:,} | {occ[k]-cbo[k]:+,} |")
    print("")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["SPX", "SPY", "QQQ"])
    a = ap.parse_args()
    print("## OCC vs CBOE 逐檔未平倉對照")
    print("")
    print("兩邊在這個時點應該都是**前一個交易日**的收盤未平倉。"
          "如果逐檔完全相同，就代表 OCC 這個來源可以取代 CBOE，"
          "而且它早十幾個小時就有了。")
    print("")
    for s in a.symbols:
        try:
            compare(s)
        except Exception as e:                                   # noqa: BLE001
            print(f"### {s}\n\n- 對照失敗：`{type(e).__name__}: {e}`\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
