#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""紅線那台的外網時段守門：台北 14:00 ~ 隔天 06:00 開放，06:00~14:00 公司封外網。

【為什麼 cron 排得再對也不夠——2026/09/18~21 的教訓】
把 cron 排在開放時段，只保證「run 被建立」的時間點是對的。
**排隊中的 run 不受 cron 保護**：runner 掉線期間 run 會一直排隊，
runner 一回來就被領走，不管當下幾點。

那幾天的真實經過：
  #37  09/18 01:23  成功（建出 09/16）—— 之後 runner 就掉線了
  #38  09/18 20:13 進隊列 → 09/19 20:13 被取消（**整整 24 小時沒有 runner 來領**，
                                              GitHub 的排隊上限）
  #39  同樣被取消（排在 #38 後面，連 job 都還沒建就被後來的取代）
  #40  09/19 20:13 進隊列 → 09/20 20:13 被取消（又是整整 24 小時）
  #41  09/20 00:10 建立，一路排到 **09/21 08:05** 才被領走——週一早上，
       正在封網時段裡。checkout、裝 Python、selftest 都過了（封網時段連得到
       GitHub），第 5 步抓 CME 在 08:06 開始，09:20 runner 直接跟伺服器失聯。

所以要在 job 裡自己再看一次現在幾點。落在封網時段就乾淨地跳過——
反正下一班 cron 就排在 15:15（開網後 75 分鐘），跳過不會損失什麼，
硬跑則會浪費一小時又把 runner 拖死。
"""
from __future__ import annotations

import datetime as dt
import os
import sys

CLOSED_FROM = 6      # 台北 06:00 起封外網
CLOSED_TO = 14       # 台北 14:00 開外網
TAIPEI = 8           # UTC+8


def taipei_now(now: dt.datetime = None) -> dt.datetime:
    """用 UTC 換算台北時間，不依賴那台機器的時區設定。"""
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    return now + dt.timedelta(hours=TAIPEI)


def is_closed(t: dt.datetime) -> bool:
    """這個台北時間點在不在封網時段內。"""
    return CLOSED_FROM <= t.hour < CLOSED_TO


def minutes_until_open(t: dt.datetime) -> int:
    """還要多久才開網（分鐘）。已經開著就回 0。"""
    if not is_closed(t):
        return 0
    return (CLOSED_TO - t.hour) * 60 - t.minute


def main() -> int:
    t = taipei_now()
    closed = is_closed(t)
    stamp = t.strftime("%Y-%m-%d %H:%M")
    if closed:
        wait = minutes_until_open(t)
        msg = (f"現在是台北 {stamp}，落在紅線的封網時段"
               f"（{CLOSED_FROM:02d}:00~{CLOSED_TO:02d}:00），還要 {wait} 分鐘才開網。\n"
               f"這一輪**跳過**，不硬跑——硬跑抓不到 CME，還會把 runner 拖到失聯"
               f"（2026/09/21 的 #41 就是這樣死的）。\n"
               f"下一班 cron 排在台北 15:15，開網後 75 分鐘，會自己補上。")
    else:
        msg = f"現在是台北 {stamp}，外網開著，照常跑。"
    print(msg)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"skip={'true' if closed else 'false'}\n")
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        with open(sp, "a", encoding="utf-8") as fh:
            fh.write(("### 跳過：封網時段\n\n" if closed else "### 外網時段檢查\n\n")
                     + msg + "\n\n")
    return 0                                      # 跳過不是錯誤，一律回 0


if __name__ == "__main__":
    raise SystemExit(main())
