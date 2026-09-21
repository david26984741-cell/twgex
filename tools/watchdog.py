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

# 【2026/09/21 收緊：美股四檔 2 → 1】
# 這一關現在比網站上那則紅字提醒**嚴一格**，是故意的，理由是兩者跑的時機不同：
#   ・網站是客戶在任何時間點打開都會看到的，寧可寬一點也不要誤報紅字。
#   ・這支固定在台北 08:00 跑，那個時點「該有的落後」是算得出來的定值——
#     週二~週五是 1（前一天晚上那兩班做的是再前一個交易日的場次），週一是 0。
#     所以 >1 不會誤報，而 2 一定是真的漏了一天。
# 為什麼要收：2026/09/21 早上 ES 停在 09/16、實際漏掉 09/17 與 09/18 兩個場次，
# 但中間隔著週末，落後只算出 **2**，在舊的門檻下剛好過關——這已經是第二次被
# 「剛好卡在門檻上」放過去了（第一次是 09/10 撞到勞動節）。
LAG_MAX = {"TXO": 1}
LAG_MAX_DEFAULT = 1

SYMBOLS = [("TXO", "calendar_tw.txt", 8), ("SPX", "calendar_us.txt", -5),
           ("ES", "calendar_us.txt", -5), ("SPY", "calendar_us.txt", -5),
           ("QQQ", "calendar_us.txt", -5)]

# 不用自己監看的標的：照常把狀態印出來，但不讓它害這次執行失敗。
# 【2026/09/21 起 ES 改成由 SPX 換算】ES 不再有自己的資料來源與資料夾——
# 它是前端拿 SPX 乘上期貨基差算出來的（見 es_view.py 與 README）。
# 所以它的新舊**完全等於 SPX 的新舊**，SPX 那一關過了它就一定是對的，
# 再單獨看一次只會多一個必定失敗的項目（根本沒有 data/ES/latest.json）。
PAUSED = {"ES": "由 SPX 換算，沒有自己的資料來源；新舊看 SPX 那一列就夠了"}

# 要盯的排程。連續兩次「排程觸發」的執行都失敗才算數——手動 dispatch 不列入，
# 那些多半是在試東西（2026/09/08 我自己就連按了四次失敗的），列進來會誤報。
WATCHED = ["es-auto.yml", "daily.yml"]
# 排程已經關掉的 workflow，最近兩次當然不會是 success，不要因此報警
WATCHED_PAUSED = {"es-auto.yml": "已退役（ES 改成由 SPX 換算，不再跑這支）"}


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
        if sym in PAUSED:
            rows.append((sym, td, lag, None, True, f"⏸ 已停用：{PAUSED[sym]}"))
            continue
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
    """最近幾次「排程觸發」而且跑完的執行，新的在前。回傳 [(run_number, 結論)]。

    **不可以在這裡挑結論。**第一版只收 success / failure / timed_out，
    把 cancelled 濾掉了——2026/09/21 就是被這個濾掉而沒叫：那幾天實際是
    #38 cancelled、#39 cancelled、#40 cancelled、#41 failure，
    濾掉三個 cancelled 之後「最近兩次」變成 [#41 failure、#37 success]，
    只有一個壞的，判定過關。但 cancelled 明明就是「這一班沒送到」。
    """
    url = (f"https://api.github.com/repos/{repo}/actions/workflows/{wf}"
           f"/runs?event=schedule&status=completed&per_page=10")
    j = _api(url, token)
    out = []
    for w in (j.get("workflow_runs") or []):
        c = w.get("conclusion")
        if not c:
            continue                              # 還沒有結論的（理論上不會出現在 completed）
        out.append((w.get("run_number"), c))
        if len(out) >= want:
            break
    return out


def judge_runs(runs: list) -> tuple:
    """連續兩次排程都沒成功才算壞掉。回傳 (過關嗎, 說明)。

    判準是「不是 success 就算沒送到」——cancelled（排隊超過 24 小時沒有 runner
    來領，GitHub 自己砍掉）跟 failure 一樣，結果都是那一天沒有資料。
    """
    if len(runs) < 2:
        return True, "排程紀錄不足兩次，先不判斷"
    bad = [r for r in runs[:2] if r[1] != "success"]
    desc = "、".join(f"#{n} {c}" for n, c in runs[:2])
    if len(bad) == 2:
        return False, f"最近兩次排程連續沒成功（{desc}）"
    return True, f"最近兩次排程：{desc}"


# 排隊超過這麼久還沒有 runner 來領，就是那台沒在線上（單位：小時）
QUEUED_MAX_HOURS = 3


def stuck_queued(repo: str, wf: str, token: str, now: dt.datetime = None) -> list:
    """目前還卡在隊列裡、而且已經排很久的執行。回傳 [(run_number, 排了幾小時)]。

    這是「runner 掉線」最早、也最直接的訊號。2026/09/18 晚上紅線那台掉線之後，
    #38 在隊列裡躺了整整 24 小時才被 GitHub 砍掉——那 24 小時裡這一關就會叫，
    比等資料日落後到門檻早了兩天。
    """
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    url = (f"https://api.github.com/repos/{repo}/actions/workflows/{wf}"
           f"/runs?status=queued&per_page=10")
    j = _api(url, token)
    out = []
    for w in (j.get("workflow_runs") or []):
        try:
            t = dt.datetime.strptime(w["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        except (KeyError, ValueError):
            continue
        hrs = (now - t).total_seconds() / 3600.0
        if hrs >= QUEUED_MAX_HOURS:
            out.append((w.get("run_number"), round(hrs, 1)))
    return out


HOWTO = {
    "es-auto.yml": (
        "  看那兩次的 job summary 寫什麼：\n"
        "  ・「限流」→ CME 的邊緣節點在擋，**隔半小時以上**再按一次 Run workflow，"
        "連續重試只會養深它。\n"
        "  ・「還沒發布」→ 等 CME 發布，晚幾小時再跑。\n"
        "  ・cancelled → **排隊超過 24 小時沒有 runner 來領**，GitHub 自己砍的。"
        "紅線那台掉線了，去 Settings → Actions → Runners 看。\n"
        "  ・runner lost communication → 那台跑到一半失聯（2026/09/21 的 #41 是"
        "在封網時段被領走才這樣）。\n"
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
            if wf in WATCHED_PAUSED:
                lines.append(f"- `{wf}`：⏸ {WATCHED_PAUSED[wf]}，這次不判斷")
                continue
            try:
                runs = recent_schedule_runs(repo, wf, token)
            except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
                lines.append(f"- `{wf}`：問不到執行紀錄（{e}），這次不判斷")
                continue
            ok, desc = judge_runs(runs)
            lines.append(f"- `{wf}`：{'✅' if ok else '❌'} {desc}")
            if not ok:
                bad.append(f"{wf} {desc}\n{HOWTO.get(wf, '')}")
            try:
                stuck = stuck_queued(repo, wf, token)
            except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
                stuck = []
            if stuck:
                who = "、".join(f"#{n}（排了 {h} 小時）" for n, h in stuck)
                lines.append(f"  - ❌ 還卡在隊列裡沒有 runner 來領：{who}")
                bad.append(f"{wf} 有執行排了超過 {QUEUED_MAX_HOURS} 小時還沒有 runner "
                           f"來領：{who}\n"
                           "  這是紅線那台沒在線上。去 Settings → Actions → Runners 看 "
                           "A51350-W11 是不是 Offline；\n"
                           "  排超過 24 小時 GitHub 會直接把那一班砍掉（conclusion 變 cancelled）。")
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
