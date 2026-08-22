#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 index.html + app.js + data/latest.json 打包成單一 HTML 檔。

用途: 直接用瀏覽器開（file://）也能看，不需要架伺服器。
      repo 上的 index.html 走 fetch，這支是給離線 / 寄檔用的。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main(out=None, data_path=None, symbol="TXO"):
    html = open(os.path.join(HERE, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(HERE, "app.js"), encoding="utf-8").read()
    data = open(data_path or os.path.join(HERE, "data", symbol, "latest.json"),
                encoding="utf-8").read()

    payload = json.loads(data)
    stamp = payload["meta"]["trade_date"].replace("/", "")
    out = out or os.path.join(HERE, f"曝險地圖_{payload['meta']['symbol']}_{stamp}.html")

    inline = ("<script>window.__GEXMAP__=" + data + ";</script>\n<script>" + js + "</script>")
    html = html.replace('<script src="app.js"></script>', inline)
    html = html.replace("<title>台指選擇權曝險地圖</title>",
                        f"<title>{payload['meta']['label']} 曝險地圖 {payload['meta']['trade_date']}</title>")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"{out}  ({os.path.getsize(out)/1024:.0f} KB)")
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None,
         sys.argv[2] if len(sys.argv) > 2 else None,
         sys.argv[3] if len(sys.argv) > 3 else "TXO")
