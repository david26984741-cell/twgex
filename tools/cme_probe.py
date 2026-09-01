#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在自己的機器上測「純 Python 打不打得到 CME」。

為什麼要測這個
--------------
CME 的邊緣節點（Akamai）擋掉 GitHub 自家 runner 的 IP：純 Python 回 403、
無頭 Chromium 走 HTTP/2 連線被重置、走 HTTP/1.1 90 秒逾時。所以 ES 那一檔
一直只能靠使用者自己開瀏覽器抓，是整條流程唯一還要人的環節。

改成在自己的機器上跑 self-hosted runner 之後，IP 問題就沒了。剩下的問題是：
**還需不需要瀏覽器？** 如果最陽春的 urllib 就打得通，整條 ES 可以純 Python，
那台機器連 Playwright / Chromium 都不用裝。這支就是回答這個問題。

這支只讀不寫，失敗也只是少一份報告。輸出是 Markdown，直接進 workflow 摘要。
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request

BASE = "https://www.cmegroup.com"
ES = 133  # ES 的期貨 productId（見 cme.py 的 FUT_PRODUCT）

# 帶得像瀏覽器一點。CME 對 User-Agent 有反應，但真正決定生死的是 IP。
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE + "/",
}

TESTS = [
    ("行事曆 ProductCalendar", f"/CmeWS/mvc/ProductCalendar/Options/{ES}"),
    ("成交量 Volume/Details",
     f"/CmeWS/mvc/Volume/Options/Details?productid={ES}&tradedate=&reporttype=P&exchange=CME"),
]


def probe(name: str, path: str) -> str:
    t0 = time.time()
    req = urllib.request.Request(BASE + path, headers=HEADERS)
    try:
        # urllib 會自己讀 https_proxy 環境變數（runner 的 .env 已經設好公司的 Proxy）
        with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()) as r:
            body = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        return f"| {name} | {e.code} | — | {time.time()-t0:.1f} | HTTPError：{e.reason} |"
    except Exception as e:                                       # noqa: BLE001
        return f"| {name} | — | — | {time.time()-t0:.1f} | {type(e).__name__}: {e} |"
    try:
        j = json.loads(body.decode("utf-8", "replace"))
        note = f"JSON OK（最上層 {type(j).__name__}）"
    except (ValueError, UnicodeDecodeError):
        note = "**不是 JSON**（多半是被擋頁攔下來了）"
    return f"| {name} | {code} | {len(body):,} | {time.time()-t0:.1f} | {note} |"


def main() -> int:
    print("### 純 Python 打 CME")
    print("")
    print(f"Proxy 環境變數：`{os.environ.get('https_proxy') or '（沒設）'}`")
    print("")
    print("| 端點 | HTTP | 位元組 | 秒 | 結果 |")
    print("|---|---|---|---|---|")
    for name, path in TESTS:
        print(probe(name, path))
    print("")
    print("兩條都 200 而且是 JSON → **整條 ES 可以純 Python，不必裝瀏覽器**。")
    print("被擋或逾時 → 這台仍然要靠瀏覽器抓，得另外裝 Playwright ＋ Chromium。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
