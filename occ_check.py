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

from collections import defaultdict


# 解析與抓取都用 occ.py 那一份，避免兩邊各寫一次、日後改一邊忘一邊。
# key = (根碼, 到期, C/P, 履約價×1000)。**根碼一定要放進 key**：
# SPX（AM 結算）與 SPXW（PM 結算）在每月第三個星期五會撞在同一個到期日、
# 履約價還大量重疊，key 裡少了根碼的話兩邊各自會被後讀到的那一批蓋掉，
# 比對出來的「100% 相同」是假的。


def compare(sym: str) -> None:
    import cboe
    import occ as occ_src

    occ = occ_src.fetch_oi(sym)
    payload = cboe.fetch_json("_SPX" if sym == "SPX" else sym)
    keep = occ_src.ROOTS.get(sym, (sym,))
    # CBOE 那邊也只留同樣的根碼，不然公司行為調整過的序列（2SPX、SPY1…）
    # 會被算成「CBOE 獨有」，看起來像對不上。
    cbo = {k: v for k, v in occ_src.cboe_oi_map(payload).items() if k[0] in keep}

    both = set(occ) & set(cbo)
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
        print("| 根碼 | 到期 | C/P | 履約價 | OCC | CBOE | 差 |")
        print("|---|---|---|---|---|---|---|")
        for k in d[:8]:
            print(f"| {k[0]} | {k[1]} | {k[2]} | {k[3]/1000:g} | "
                  f"{occ[k]:,} | {cbo[k]:,} | {occ[k]-cbo[k]:+,} |")

    # 換源前唯一還沒回答的問題：OCC 多出來的那些序列到底是什麼，該不該進圖。
    # 逐檔比對已經是 100%，差額全部來自這裡，所以把它們的長相攤開來看。
    if occ_only:
        oo = sorted(occ_only, key=lambda k: -occ[k])
        by_exp = defaultdict(int)
        for k in occ_only:
            by_exp[k[1]] += occ[k]
        tot_only = sum(occ[k] for k in occ_only)
        print("")
        print(f"- **OCC 獨有的 {len(occ_only):,} 個序列，合計 {tot_only:,} 口"
              f"（佔 OCC 總量 {tot_only / max(tot_occ, 1) * 100:.2f}%）**")
        print("")
        print("| 根碼 | 到期 | C/P | 履約價 | 未平倉 |")
        print("|---|---|---|---|---|")
        for k in oo[:10]:
            print(f"| {k[0]} | {k[1]} | {k[2]} | {k[3]/1000:g} | {occ[k]:,} |")
        print("")
        top_exp = sorted(by_exp.items(), key=lambda x: -x[1])[:6]
        print("  依到期日分佈（前 6）：" +
              "、".join(f"{e} {v:,} 口" for e, v in top_exp))
        # 履約價有沒有落在正常的整數／半數格線上——不是的話多半是公司行為調整過的序列
        odd = [k for k in occ_only if k[3] % 500 != 0]
        print(f"  履約價不在 0.5 整數格上的：{len(odd):,} 個"
              f"（這種通常是公司行為調整過的序列）")
        print("")
        print("  **這些序列進不了圖，而且不是選擇——CBOE 那份檔案根本沒有列它們，"
              "就沒有報價，沒有報價就反解不出 IV、算不出 gamma。**"
              "換不換來源都一樣，所以它們不構成換源的阻礙。")
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
