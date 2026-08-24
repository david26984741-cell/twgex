#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用無頭 Chromium 代抓 CME 的選擇權結算表。

為什麼要這樣做：CME 的網站 API（/CmeWS/...）擋掉非瀏覽器的請求，直接回 HTTP 403
（Akamai 的機器人防護會看 TLS 指紋，光換 User-Agent 沒用）。所以先用 Chromium
真的把 CME 的頁面載入一次、拿到 Akamai 的 cookie，再從頁面內部（同源）去呼叫 API。

輸出的 JSON 直接餵給 build.py：
    python cme_fetch.py --date 20260821 --out raw/cme_ES.json
    python build.py --symbol ES --json raw/cme_ES.json

格式與 cme.chain_from_dump 對應：
    {"tradeDate": "MM/DD/YYYY",
     "futures": [[month, settle, openInterest], ...],
     "series": [{"code","name","type","lastTrade","pid","rows":[[strike,type,settle,oi,vol],...]}]}
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

SEED_URL = "https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.settlements.options.html"
FUT_PRODUCT = {"ES": 133}

# 在頁面內執行：列出所有系列，逐系列要結算表。
# productId 與系列代碼的配對：代碼裡的數字就是第幾週（E4A → productIds[3]），
# 先照這個猜，猜不中才退回逐一試，可以把請求數壓到接近 1 次/系列。
JS = r"""
async ({futProduct, tradeDate, maxDays, pause}) => {
  const j = async (u) => {
    const r = await fetch(u, {headers: {Accept: 'application/json'}});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const cal = await j('/CmeWS/mvc/ProductCalendar/Options/' + futProduct);

  const [mm, dd, yy] = tradeDate.split('/');
  const td0 = new Date(Date.UTC(+yy, +mm - 1, +dd));
  const parseLT = s => {
    const d = new Date(s + ' UTC');
    return isNaN(d) ? null : d;
  };

  const series = [];
  for (const ty of cal) {
    const pids = (ty.productIds && ty.productIds.length) ? ty.productIds : [ty.productId];
    for (const e of ty.calendarEntries || []) {
      const lt = parseLT(e.lastTrade);
      if (!lt || lt <= td0) continue;                       // 當日（含）以前到期的不要
      if ((lt - td0) / 86400000 > maxDays) continue;        // 太遠期的略過（未平倉極小）
      const m = /^[A-Z]*?(\d)/.exec(e.productCode || '');   // 代碼裡的週次
      const wk = m ? +m[1] : 0;
      const order = [];
      if (wk >= 1 && wk <= pids.length) order.push(pids[wk - 1]);
      for (const p of pids) if (!order.includes(p)) order.push(p);
      series.push({code: e.productCode, name: ty.name, type: ty.optionType,
                   lastTrade: e.lastTrade, order});
    }
  }

  const out = [];
  let reqs = 0;
  for (const s of series) {
    for (const pid of s.order) {
      reqs++;
      let data = null;
      try {
        data = await j('/CmeWS/mvc/Settlements/Options/Settlements/' + pid +
          '/OOF?monthYear=' + encodeURIComponent(s.code) +
          '&tradeDate=' + encodeURIComponent(tradeDate) + '&strategy=DEFAULT');
      } catch (err) { await sleep(pause); continue; }
      const rows = (data.settlements || [])
        .filter(x => x.strike && String(x.strike).toLowerCase() !== 'total')
        .map(x => [x.strike, x.type, x.settle, x.openInterest, x.volume]);
      if (rows.length) {
        out.push({code: s.code, name: s.name, type: s.type,
                  lastTrade: s.lastTrade, pid, rows});
        break;
      }
      await sleep(pause);
    }
    await sleep(pause);
  }

  let futures = [];
  try {
    const f = await j('/CmeWS/mvc/Settlements/Futures/Settlements/' + futProduct +
      '/FUT?tradeDate=' + encodeURIComponent(tradeDate) + '&strategy=DEFAULT');
    futures = (f.settlements || [])
      .filter(x => x.month && String(x.month).toLowerCase() !== 'total')
      .map(x => [x.month, x.settle, x.openInterest]);
  } catch (err) {}

  return {tradeDate, futures, series: out,
          stats: {candidates: series.length, fetched: out.length, requests: reqs}};
}
"""


def us_prev_session(today: dt.date) -> dt.date:
    """前一個美股交易日。有休市日表就用它，沒有就只跳週末。"""
    try:
        import engine
        hol = engine.load_holidays(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "calendar_us.txt"))
        return engine.prev_trading_day(today, hol)
    except Exception:                                 # noqa: BLE001
        d = today - dt.timedelta(days=1)
        while d.weekday() >= 5:
            d -= dt.timedelta(days=1)
        return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="ES")
    ap.add_argument("--date", help="YYYYMMDD，預設為美東時間的前一個交易日")
    ap.add_argument("--out", default="raw/cme_ES.json")
    ap.add_argument("--max-days", type=int, default=400,
                    help="只抓這麼多天內到期的系列（更遠期的未平倉極小）")
    ap.add_argument("--pause", type=int, default=120, help="每次請求之間的毫秒數")
    ap.add_argument("--timeout", type=int, default=600, help="頁內腳本的秒數上限")
    ap.add_argument("--base", help="測試用：改打別的站台（預設 cmegroup.com）")
    a = ap.parse_args()

    if a.date:
        day = a.date
    else:
        et = dt.datetime.utcnow() - dt.timedelta(hours=5)
        day = us_prev_session(et.date()).strftime("%Y%m%d")
    td = f"{day[4:6]}/{day[6:8]}/{day[:4]}"

    from playwright.sync_api import sync_playwright

    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    with sync_playwright() as p:
        br = p.chromium.launch(args=[
            "--no-sandbox", "--disable-dev-shm-usage",
            # CME 的邊緣節點會把 headless Chromium 的 HTTP/2 連線打掉
            # （net::ERR_HTTP2_PROTOCOL_ERROR），退回 HTTP/1.1 才連得上
            "--disable-http2",
            "--disable-blink-features=AutomationControlled",
        ])
        ctx = br.new_context(locale="en-US", viewport={"width": 1440, "height": 900},
                             user_agent=UA,
                             extra_http_headers={"Accept-Language": "en-US,en;q=0.9"})
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()
        print("載入 CME 頁面取得 cookie …", file=sys.stderr)
        last = None
        for attempt in range(3):
            try:
                page.goto(a.base or SEED_URL, wait_until="domcontentloaded", timeout=90_000)
                last = None
                break
            except Exception as e:                        # noqa: BLE001
                last = e
                print(f"  第 {attempt+1} 次載入失敗：{str(e).splitlines()[0]}", file=sys.stderr)
                page.wait_for_timeout(4000)
        if last is not None:
            raise last
        page.wait_for_timeout(6000)                      # 等 Akamai 的 script 跑完
        print(f"開始抓 {a.symbol} {td} 的結算表 …", file=sys.stderr)
        data = page.evaluate(JS, {"futProduct": FUT_PRODUCT[a.symbol], "tradeDate": td,
                                  "maxDays": a.max_days, "pause": a.pause})
        br.close()

    st = data.pop("stats", {})
    if not data.get("series"):
        print(f"{a.symbol}: 一個系列都沒抓到（{st}）", file=sys.stderr)
        return 1
    oi = sum(int(str(r[3]).replace(",", "") or 0)
             for s in data["series"] for r in s["rows"])
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"{a.symbol} {td}  候選系列 {st.get('candidates')}  抓到 {st.get('fetched')}  "
          f"請求 {st.get('requests')} 次  未平倉合計 {oi:,}  -> {a.out} "
          f"({os.path.getsize(a.out)/1024:.0f} KB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
