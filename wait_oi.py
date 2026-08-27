#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""等到 CBOE 檔案裡的未平倉量更新到「前一個交易日收盤」為止。

為什麼需要這一步：CBOE 的 delayed_quotes 檔案裡，價格是即時的，
未平倉量卻要等 OCC 隔天早上發布（實測大約美東 10:00~10:30 之間）才會跟上。
本專案的價格一律取 prev_day_close，所以只要「未平倉已經更新」這一個條件成立，
價格與未平倉就是同一個交易日的收盤，而且這個窗口一路開到當天收盤，
不怕 GitHub 排程延遲。這支程式就是在等那個條件成立。

    python wait_oi.py --minutes 150

已經更新就馬上結束（exit 0）；等到逾時仍未更新回 exit 1，
呼叫端應該直接放棄這一天，不要產出拼裝的圖。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    import cboe
    import engine

    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY",
                    help="用哪一檔當偵測器。要選 CBOE 有保留已到期序列的（SPY / QQQ），"
                         "SPX 的檔案不保留，無法反推")
    ap.add_argument("--minutes", type=float, default=150, help="最多等幾分鐘")
    ap.add_argument("--every", type=float, default=5, help="每幾分鐘試一次")
    a = ap.parse_args()

    hol = engine.load_holidays(os.path.join(HERE, "calendar_us.txt"))
    prev = lambda d: engine.prev_trading_day(d, hol)
    deadline = time.time() + a.minutes * 60
    n = 0
    while True:
        n += 1
        try:
            payload = cboe.fetch_json(a.symbol)
            st = cboe.snapshot_state(payload)
            sess = st["sess"]
            want = prev(dt.date(int(sess[:4]), int(sess[4:6]), int(sess[6:8]))).strftime("%Y%m%d")
            got = cboe.oi_as_of(payload, sess, prev_td=prev)
            stamp = dt.datetime.utcnow().strftime("%H:%M")
            if st["rolled"]:
                # 新的一天、還沒開盤：prev_day_close 已經滾到 sess 收盤，未平倉卻還沒更新。
                # 這時 got == want 會成立但意義是錯的，不能放行。
                print(f"[{stamp}] 第 {n} 次：{st['us_date']} 美東還沒開盤（場次仍是 {sess}），"
                      f"價格已經滾到新的一天、未平倉還沒跟上，繼續等", file=sys.stderr)
            elif got == want:
                print(f"[{stamp}] 第 {n} 次：未平倉已更新到 {want} 收盤（本場次 {sess}），可以開始建圖。")
                return 0
            else:
                print(f"[{stamp}] 第 {n} 次：未平倉還停在 {got}，要等到 {want}（本場次 {sess}）",
                      file=sys.stderr)
        except Exception as e:                             # noqa: BLE001
            print(f"  讀取失敗，稍後再試：{e}", file=sys.stderr)
        if time.time() + a.every * 60 > deadline:
            print(f"::error::等了 {a.minutes:.0f} 分鐘，CBOE 的未平倉量還是沒更新到前一個交易日。"
                  f"今天不產出，以免畫出「舊未平倉 ＋ 新價格」的拼裝圖。", file=sys.stderr)
            return 1
        time.sleep(a.every * 60)


if __name__ == "__main__":
    raise SystemExit(main())
