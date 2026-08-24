#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把瀏覽器端匯出的精簡文字表轉回 cme.chain_from_dump 吃的 JSON。

格式（管線分隔）：
  H|MM/DD/YYYY|報表版本(F/P)|未平倉基準(close/prev)
  F|月份|結算價|未平倉            ← 期貨，可有多列
  S|系列碼|最後交易日|選擇權型別|未平倉來源   ← 之後的列都屬於這個系列
  履約價|C或P|結算價|未平倉|成交量
"""
import json
import sys

NAME = {"AME": "E-mini S&P 500 Options", "EOM": "E-mini S&P 500 EOM Options",
        "MW1": "E-mini S&P 500 Monday Weekly Options",
        "AB1": "E-mini S&P 500 Tuesday Weekly Options",
        "WD1": "E-mini S&P 500 Wednesday Weekly Options",
        "BB1": "E-mini S&P 500 Thursday Weekly Options",
        "E21": "E-mini S&P 500 Friday Weekly Options"}


def convert(src: str, dst: str) -> dict:
    head = None
    futures, series, cur = [], [], None
    with open(src, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.rstrip("\n")
            if not ln:
                continue
            p = ln.split("|")
            if p[0] == "H":
                head = p
            elif p[0] == "F":
                futures.append([p[1], p[2], p[3]])
            elif p[0] == "S":
                cur = {"code": p[1], "lastTrade": p[2], "type": p[3],
                       "oiSrc": p[4] if len(p) > 4 else "",
                       "name": NAME.get(p[3], p[3]), "rows": []}
                series.append(cur)
            else:
                if cur is None:
                    raise SystemExit(f"沒有 S 標頭就出現資料列：{ln[:60]}")
                cur["rows"].append([p[0], "Call" if p[1] == "C" else "Put",
                                    p[2], p[3], p[4]])
    if head is None:
        raise SystemExit("缺少 H 標頭")
    dump = {"tradeDate": head[1], "oiReport": head[2],
            "oiAsOf": head[3] if len(head) > 3 else "close",
            "futures": futures, "series": series}
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(dump, fh, ensure_ascii=False, separators=(",", ":"))
    return dump


if __name__ == "__main__":
    d = convert(sys.argv[1], sys.argv[2])
    n = sum(len(s["rows"]) for s in d["series"])
    oi = sum(int(r[3]) for s in d["series"] for r in s["rows"])
    print(f"{d['tradeDate']}  系列 {len(d['series'])}  契約 {n:,}  未平倉 {oi:,}  "
          f"期貨 {len(d['futures'])}  未平倉基準 {d['oiAsOf']}/{d['oiReport']}")
