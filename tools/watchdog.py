#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看門狗：每天早上檢查五個標的的資料有沒有跟上，以及排程最近有沒有連續失敗。

**這支跑在 GitHub 自己的機器上（ubuntu-latest），跟紅線那台完全無關。**
它只做兩件事：讀 checkout 下來的 `data/*/latest.json`，以及打本 repo 的
Actions API 問最近的執行結果。**不連 CME、不連期交所、不連 CBOE、不需要瀏覽器。**
所以紅線那台早上 06:00~14:00 封外網，影響不到它。

兩個獨立的訊號，任一個成立就讓這次執行失敗（GitHub 預設會寄信）：

  1. **資料日落後太多** —— 跟網站上那則紅字提醒用同一套規則，兩邊不要各講各話。
  2. **同一支 workflow 最近兩次「排程」的執行連續失敗** —— 連續兩次代表它沒有
     自己恢復，不是單次抖動。

【為什麼第 2 個是必要的，不能只靠第 1 個】
2026/09/10 早上 08:00 的真實數字：ES 停在 09/04 已經兩天沒更新，但 09/07 是
美國勞動節，所以「落後幾個交易日」只算出 2，**剛好卡在門檻上不會叫**。
那天早上單靠第 1 個訊號是安靜的，使用者是下午自己發現的。
而那個時點 es-auto 已經連續失敗兩次（#23、#24），第 2 個訊號當場就會叫。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import engine  # noqa: E402  （load_holidays 只有這一份，不要再寫第二個 parser）

# 跟 app.js 的 staleNotice 用同一組門檻。
# 台指當天就更新（跑之前會落後 1 天）；美股四檔本來就是看前一個交易日（跑之前落後 2 天）。
# 註：這組門檻對 ES 偏鬆——見上面 2026/09/10 那個例子。等累積幾週的實際落後值
#     再決定要不要收緊，現在先不憑感覺改，早期預警交給第 2 個訊號。
LAG_MAX = {"TXO": 1}
LAG_MAX_DEFAULT = 2

SYMBOLS = [("TXO", "calendar_tw.txt", 8), ("SPX", "calendar_us.txt", -5),
           ("ES", "calendar_us.txt", -5), ("SPY", "calendar_us.txt", -5),
           ("QQQ", "calendar_us.txt", -5)]

# 要盯的排程。連續兩次「排程觸發」的執行都失敗才算數——手動 dispatch 不列入，
# 那些多半是在試東西（2026/09/08 我自己就連按了四次失敗的），列進來會誤報。
WATCHED = ["es-auto.yml", "daily.yml"]


def today_in(offset_hours: int, now: dt.datetime = None) -> dt.date:
    """用某個時區偏移看「今天」是哪一天。台指看台北（+8），美股看美東（用 −5 保守估）。"""
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    return (now + dt.timedelta(hours=offset_hours)).date()


def trading_days_since(trade_date: dt.date, today: dt.date, hol: set) -> int:
    """資料日之後到 today 為止（不含資料日、含 today）有幾個交易日。"""
    n = 0
    cur = trade_date
    guard = 0
    while cur < today and guard < 400:
        guard += 1
        cur += dt.timedelta(days=1)
        if cur.weekday() >= 5 or cur in hol:
            continue
        n += 1
    return n


def check_data(root: str, now: dt.datetime = None) -> list:
    """回傳 [(標的, 資料日, 落後幾個交易日, 門檻, 過關嗎, 備註)]。"""
    rows = []
    for sym, cal, off in SYMBOLS:
        path = os.path.join(root, "data", sym, "latest.json")
        if not os.path.exists(path):
            rows.append((sym, "—", None, None, False, "找不到 latest.json"))
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                td = json.load(fh)["meta"]["trade_date"]
            y, m, d = (int(x) for x in td.replace("-", "/").split("/"))
            day = dt.date(y, m, d)
        except Exception as e:                        # noqa: BLE001
            rows.append((sym, "—", None, None, False, f"讀不出資料日：{e}"))
            continue
        hol = engine.load_holidays(os.path.join(root, cal))
        lag = trading_days_since(day, today_in(off, now), hol)
        cap = LAG_MAX.get(sym, LAG_MAX_DEFAULT)
        rows.append((sym, td, lag, cap, lag <= cap, ""))
    return rows


def _api(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def recent_schedule_runs(repo: str, wf: str, token: str, want: int = 2) -> list:
    """最近幾次「排程觸發」而且真的跑完的執行，新的在前。回傳 [(run_number, 結論)]。"""
    url = (f"https://api.github.com/repos/{repo}/actions/workflows/{wf}"
           f"/runs?event=schedule&status=completed&per_page=10")
    j = _api(url, token)
    out = []
    for w in (j.get("workflow_runs") or []):
        if w.get("conclusion") in ("success", "failure", "timed_out"):
            out.append((w.get("run_number"), w.get("conclusion")))
        if len(out) >= want:
            break
    return out


def judge_runs(runs: list) -> tuple:
    """連續兩次排程都失敗才算壞掉。回傳 (過關嗎, 說明)。"""
    if len(runs) < 2:
        return True, "排程紀錄不足兩次，先不判斷"
    bad = [r for r in runs[:2] if r[1] != "success"]
    desc = "、".join(f"#{n} {c}" for n, c in runs[:2])
    if len(bad) == 2:
        return False, f"最近兩次排程連續失敗（{desc}）"
    return True, f"最近兩次排程：{desc}"


HOWTO = {
    "es-auto.yml": (
        "  看那兩次的 job summary 寫什麼：\n"
        "  ・「限流」→ CME 的邊緣節點在擋，**隔半小時以上**再按一次 Run workflow，"
        "連續重試只會養深它。\n"
        "  ・「還沒發布」→ 等 CME 發布，晚幾小時再跑。\n"
        "  ・完全沒有執行紀錄 → 紅線那台的 self-hosted runner 掉線了，"
        "去 Settings → Actions → Runners 看。\n"
        "  手動補跑要挑**台北 14:00 ~ 隔天 06:00**，那台 06:00~14:00 封外網。"),
    "daily.yml": (
        "  多半是期交所或 OCC / CBOE 晚上架。到 Actions 按一次 Run workflow 就會補；"
        "連兩次失敗就要看 log 是不是有別的原因。"),
}


def main() -> int:
    rows = check_data(ROOT)
    lines = ["## 資料有沒有跟上", "",
             "| 標的 | 資料日 | 落後 | 門檻 | |", "|---|---|---|---|---|"]
    bad = []
    for sym, td, lag, cap, ok, note in rows:
        mark = "✅" if ok else "❌"
        lines.append(f"| {sym} | {td} | {lag if lag is not None else '—'} | "
                     f"{cap if cap is not None else '—'} | {mark} {note} |")
        if not ok:
            bad.append(f"{sym} 停在 {td}（落後 {lag} 個交易日，門檻 {cap}）{note}")

    lines += ["", "## 排程最近跑得怎麼樣", ""]
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if repo and token:
        for wf in WATCHED:
            try:
                runs = recent_schedule_runs(repo, wf, token)
            except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
                lines.append(f"- `{wf}`：問不到執行紀錄（{e}），這次不判斷")
                continue
            ok, desc = judge_runs(runs)
            lines.append(f"- `{wf}`：{'✅' if ok else '❌'} {desc}")
            if not ok:
                bad.append(f"{wf} {desc}\n{HOWTO.get(wf, '')}")
    else:
        lines.append("- 沒有 GITHUB_REPOSITORY / GH_TOKEN，跳過這一段")

    summary = "\n".join(lines)
    print(summary)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        with open(sp, "a", encoding="utf-8") as fh:
            fh.write(summary + "\n")

    if not bad:
        print("\n一切正常。")
        return 0
    for b in bad:
        print(f"::error::{b.splitlines()[0]}")
    print("\n" + "\n\n".join(bad), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
