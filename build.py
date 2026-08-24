#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""產生曝險地圖的資料檔。

  python build.py                        # TXO，連期交所 / 證交所抓最新一天
  python build.py --symbol SPY           # SPY，連 CBOE
  python build.py --symbol QQQ
  python build.py --csv raw/x.csv        # TXO 離線重跑
  python build.py --symbol SPY --json raw/cboe_SPY.json
  python build.py --date 20260819 --spot-file spot_history.txt

輸出 data/<SYMBOL>/latest.json 與 data/<SYMBOL>/history/<日期>.json，
外加 data/<SYMBOL>/index.json（可選日期）與 data/symbols.json（可選標的）。

輸出的是「積木」不是成品數字: 每個履約價分別給買權/賣權的 gamma / vanna / vega 項，
情境曲線同樣分量輸出，網頁端才組成：
  GEX  = sg.c*gc + sg.p*gp        VEX = sg.c*wc + sg.p*wp        GEX+ = GEX + beta*VEX
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import engine
import symbols as symcfg

HERE = os.path.dirname(os.path.abspath(__file__))


def fmt_date(s):
    return f"{s[:4]}/{s[4:6]}/{s[6:8]}" if s and len(s) == 8 else None
DATA = os.path.join(HERE, "data")
CURVE_N = 241
CURVE_SPAN = 0.12
MIN_REF_OI = 500
MAX_REF_SPREAD = 0.005


def pick_reference_forward(live, diag, forwards):
    """抓不到現貨時的備援：挑 parity 夠乾淨、未平倉夠大的到期別遠期。"""
    for e in live:
        if e not in forwards:
            continue
        d = diag[e]
        if d.get("oi_used", 0) >= MIN_REF_OI and \
           d.get("near_spread", 1e9) <= MAX_REF_SPREAD * forwards[e]:
            return forwards[e], e
    e = max(forwards, key=lambda k: diag[k].get("oi_used", 0))
    return forwards[e], e


def strike_components(legs, S_ref, prev_oi, mult):
    s2 = mult * S_ref * S_ref * 0.01
    sw = -mult * S_ref / 100.0
    sv = mult / 100.0
    acc = {}
    for lg in legs:
        K = round(lg.K, 2)
        a = acc.setdefault(K, {"K": K, "gc": 0.0, "gp": 0.0, "wc": 0.0, "wp": 0.0,
                               "vc": 0.0, "vp": 0.0, "oc": 0, "op": 0,
                               "dc": 0, "dp": 0, "ivn": 0.0, "ivd": 0.0})
        g, w, v = lg.gamma * lg.oi * s2, lg.vanna * lg.oi * sw, lg.vega * lg.oi * sv
        prev = prev_oi.get((lg.exp, lg.K, lg.cp), 0)
        if lg.cp == "C":
            a["gc"] += g; a["wc"] += w; a["vc"] += v
            a["oc"] += lg.oi; a["dc"] += lg.oi - prev
        else:
            a["gp"] += g; a["wp"] += w; a["vp"] += v
            a["op"] += lg.oi; a["dp"] += lg.oi - prev
        a["ivn"] += lg.iv * lg.oi; a["ivd"] += lg.oi
    out = []
    for K in sorted(acc):
        a = acc[K]
        a["iv"] = round(a["ivn"] / a["ivd"], 5) if a["ivd"] else None
        a.pop("ivn"); a.pop("ivd")
        for k in ("gc", "gp", "wc", "wp", "vc", "vp"):
            a[k] = round(a[k], 1)
        out.append(a)
    return out


def curve_components(legs, S_ref, forwards, mult, n=CURVE_N, span=CURVE_SPAN):
    xs = [S_ref * (1.0 - span + 2 * span * i / (n - 1)) for i in range(n)]
    gc, gp, wc, wp = [], [], [], []
    for S in xs:
        ratio = S / S_ref
        a = b = c = d = 0.0
        s2, sw = mult * S * S * 0.01, -mult * S / 100.0
        for lg in legs:
            gk = engine.greeks76(forwards[lg.exp] * ratio, lg.K, lg.T, lg.iv)
            g, w = gk["gamma"] * lg.oi * s2, gk["vanna"] * lg.oi * sw
            if lg.cp == "C":
                a += g; c += w
            else:
                b += g; d += w
        gc.append(a); gp.append(b); wc.append(c); wp.append(d)
    r = lambda v: [round(x, 1) for x in v]
    return {"x": [round(v, 2) for v in xs], "gc": r(gc), "gp": r(gp), "wc": r(wc), "wp": r(wp)}


def totals(strikes):
    return {k: round(sum(r[k] for r in strikes), 1)
            for k in ("gc", "gp", "wc", "wp", "vc", "vp")}


# --------------------------------------------------------------------------- 取資料

def load_tw(args):
    import taifex
    if args.csv:
        opt_txt = taifex.read_csv_file(args.csv)
        fut_txt = taifex.read_csv_file(args.fut_csv) if args.fut_csv else ""
    else:
        today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
        opt_txt = taifex.fetch_csv("TXO", today - dt.timedelta(days=args.days_back), today)
        fut_txt = taifex.fetch_csv("TX", today - dt.timedelta(days=args.days_back), today)
    days = taifex.parse_options(opt_txt)
    if not days:
        raise SystemExit("期交所沒有回傳任何選擇權資料")
    day = args.date or taifex.latest_day(days)
    if day not in days:
        raise SystemExit(f"資料中沒有 {day}，可用: {sorted(days)}")
    chain = {e: days[day][e] for e in taifex.live_expiries(days[day], day)}

    prior = sorted(d for d in days if d < day)
    prev_oi = {}
    if prior:
        for e, b in days[prior[-1]].items():
            for K, side in b["strikes"].items():
                for cp in ("C", "P"):
                    if side.get(cp):
                        prev_oi[(e, K, cp)] = side[cp].get("oi") or 0

    spot = args.spot
    if not spot and args.spot_file and os.path.exists(args.spot_file):
        for line in open(args.spot_file, encoding="utf-8"):
            line = line.split("#")[0].strip()
            if line.startswith(day):
                try:
                    spot = float(line.split()[1])
                except (IndexError, ValueError):
                    pass
                break
    if not spot and not args.csv:
        spot = taifex.fetch_taiex_close(day)

    extra = {"tx_futures_close": taifex.parse_futures(fut_txt).get(day, {}) if fut_txt else {}}
    return day, chain, prev_oi, spot, (prior[-1] if prior else None), extra


def us_last_session(holidays) -> str:
    """美東「現在」之前最近的一個已收盤交易日（YYYYMMDD）。

    排程放在美東早上（開盤前）跑，此時 CBOE 的報價與 OCC 的未平倉量
    指的都是前一個交易日的收盤，所以直接用日曆推，不看 last_trade_time。
    """
    et = dt.datetime.utcnow() - dt.timedelta(hours=5)      # 約當美東（夏令時差 1 小時，不影響判斷日期）
    d = et.date()
    if et.hour >= 17:            # 已經過了當天收盤且結算完，當天就是最後一個 session
        while d.weekday() >= 5 or d in holidays:
            d = engine.prev_trading_day(d, holidays)
        return d.strftime("%Y%m%d")
    return engine.prev_trading_day(d, holidays).strftime("%Y%m%d")


def load_us(args, sym):
    import cboe
    import symbols as _sc
    spec0 = _sc.SPECS[sym]
    payload = (cboe.read_json_file(args.json) if args.json
               else cboe.fetch_json(spec0.get("cboe_symbol", sym)))
    hol = engine.load_holidays(os.path.join(HERE, spec0["calendar"]))
    session = args.date or (None if args.json else us_last_session(hol))
    # 未平倉量可能還沒跟上（OCC 隔一個營業日才發布），用資料本身推斷它是哪一天的
    price_day = (payload.get("data", {}).get("last_trade_time") or "")[:10].replace("-", "")
    oi_day = cboe.oi_as_of(payload, price_day or session or "99999999")
    forced = oi_day or session
    chain_all, meta = cboe.parse_chain(
        payload, forced, am_roots=spec0.get("am_roots", ()),
        prev_td=lambda d: engine.prev_trading_day(d, hol))
    day = forced or meta["trade_day"]
    if oi_day and price_day and oi_day < price_day:
        print(f"  註：未平倉量為 {oi_day} 收盤（OCC 尚未發布 {price_day}），"
              f"報價為 {price_day} 收盤，本檔以未平倉日為準標示。", file=sys.stderr)
    if not day:
        raise SystemExit("CBOE 回傳裡找不到交易日")
    chain = {e: chain_all[e] for e in cboe.live_expiries(chain_all, day)}
    prev_oi = {}
    hist = os.path.join(DATA, sym, "history")
    prior = None
    if os.path.isdir(hist):
        past = sorted(f[:-5] for f in os.listdir(hist) if f.endswith(".json") and f[:-5] < day)
        if past:
            prior = past[-1]
            old = json.load(open(os.path.join(hist, prior + ".json"), encoding="utf-8"))
            for r in old["views"]["ALL"]["strikes"]:
                prev_oi[("*", r["K"], "C")] = r["oc"]
                prev_oi[("*", r["K"], "P")] = r["op"]
    extra = {"quote_time": meta.get("quote_time"), "snapshot": meta.get("snapshot"),
             "iv30": meta.get("iv30"), "n_contracts_all": meta.get("n_contracts_all"),
             "oi_as_of": fmt_date(oi_day), "price_as_of": fmt_date(price_day)}
    return day, chain, prev_oi, args.spot or meta["spot"], prior, extra


def load_cme(args, sym):
    """CME 期貨選擇權（ES）。可用 --json 餵離線抓好的原始結算表。"""
    import cme
    import symbols as _sc
    spec0 = _sc.SPECS[sym]
    hol = engine.load_holidays(os.path.join(HERE, spec0["calendar"]))
    prev = lambda d: engine.prev_trading_day(d, hol)
    if args.json:
        chain, meta = cme.chain_from_dump(cme.read_json_file(args.json), prev_td=prev)
        day = args.date or meta["trade_day"]
    else:
        day = args.date or us_last_session(hol)
        chain, meta = cme.fetch_chain(day, sym, prev_td=prev)
    prev_oi = {}
    prior = None
    hist = os.path.join(DATA, sym, "history")
    if os.path.isdir(hist):
        past = sorted(f[:-5] for f in os.listdir(hist) if f.endswith(".json") and f[:-5] < day)
        if past:
            prior = past[-1]
            old = json.load(open(os.path.join(hist, prior + ".json"), encoding="utf-8"))
            for r in old["views"]["ALL"]["strikes"]:
                prev_oi[("*", r["K"], "C")] = r["oc"]
                prev_oi[("*", r["K"], "P")] = r["op"]
    extra = {"n_contracts_all": meta.get("n_contracts_all"),
             "n_requests": meta.get("n_requests"),
             "futures": (meta.get("futures") or [])[:6]}
    return day, chain, prev_oi, args.spot or meta.get("spot"), prior, extra


# --------------------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="TXO", choices=list(symcfg.SPECS))
    ap.add_argument("--csv"); ap.add_argument("--fut-csv"); ap.add_argument("--json")
    ap.add_argument("--date"); ap.add_argument("--spot", type=float)
    ap.add_argument("--spot-file")
    ap.add_argument("--days-back", type=int, default=9)
    args = ap.parse_args()

    sym = args.symbol
    spec = symcfg.SPECS[sym]
    if spec["market"] == "TW":
        loader = load_tw(args)
    elif spec.get("venue") == "CME":
        loader = load_cme(args, sym)
    else:
        loader = load_us(args, sym)
    day, chain, prev_oi, spot, prior, extra = loader
    if not chain:
        print(f"{sym}: 沒有未到期的契約", file=sys.stderr)
        return 1

    trade_date = dt.date(int(day[:4]), int(day[4:6]), int(day[6:8]))
    holidays = engine.load_holidays(os.path.join(HERE, spec["calendar"]))
    legs, diag = engine.build_legs(chain, trade_date, holidays,
                                   settle_next_day=spec["settle_next_day"],
                                   band=spec["parity_band"])
    if not legs:
        print(f"{sym}: 沒有任何可用的部位", file=sys.stderr)
        return 1

    live = sorted(chain, key=lambda e: chain[e]["ltd"])
    forwards = {e: diag[e]["F"] for e in live if diag[e].get("F")}
    if not forwards:
        print(f"{sym}: 所有到期別都反解不出遠期價", file=sys.stderr)
        return 1
    if spot and spot > 0:
        S_ref, ref_src = float(spot), "現貨收盤"
    else:
        S_ref, e = pick_reference_forward(live, diag, forwards)
        ref_src = f"{e} 遠期（抓不到現貨）"

    mult = spec["multiplier"]
    slopes = {e: engine.skew_slope(legs, e, forwards[e]) for e in forwards}
    lo_k, hi_k = S_ref * (1 - spec["strike_band"]), S_ref * (1 + spec["strike_band"])

    views = {}
    for key in ["ALL"] + live:
        sel = legs if key == "ALL" else [l for l in legs if l.exp == key]
        if not sel:
            continue
        st_all = strike_components(sel, S_ref, prev_oi, mult)
        st = [r for r in st_all if lo_k <= r["K"] <= hi_k]
        out_band = [r for r in st_all if not (lo_k <= r["K"] <= hi_k)]
        views[key] = {
            "strikes": st,
            "curve": curve_components(sel, S_ref, forwards, mult),
            "totals": totals(st_all),
            "oi_c": sum(r["oc"] for r in st_all), "oi_p": sum(r["op"] for r in st_all),
            "truncated": {"n_strikes_dropped": len(out_band),
                          "oi_outside": sum(r["oc"] + r["op"] for r in out_band),
                          **{k: round(sum(r[k] for r in out_band), 1)
                             for k in ("gc", "gp", "wc", "wp")},
                          "band_pct": spec["strike_band"]},
        }

    atm_iv = {}
    for e in forwards:
        near = sorted([l for l in legs if l.exp == e],
                      key=lambda l: abs(l.K / forwards[e] - 1))[:6]
        if near:
            atm_iv[e] = round(sum(l.iv for l in near) / len(near), 5)

    oi_used = sum(d.get("oi_used", 0) for d in diag.values())
    oi_drop = sum(d.get("oi_dropped", 0) for d in diag.values())
    fmt_d = lambda s: f"{s[:4]}/{s[4:6]}/{s[6:8]}" if s else None

    payload = {
        "meta": {
            "symbol": sym, "label": spec["label"], "desc": spec["desc"],
            "currency": spec["currency"], "unit": spec["unit"], "unit_div": spec["unit_div"],
            "default_view_band": spec["default_view_band"],
            "trade_date": fmt_d(day), "prev_trade_date": fmt_d(prior),
            "generated_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "source": spec["source"], "price_note": spec["price_note"],
            "tz_note": spec["tz_note"], "multiplier": mult,
            "s_ref": round(S_ref, 4), "s_ref_source": ref_src,
            "n_legs": len(legs), "n_expiries": len(views) - 1,
            "oi_total": oi_used,
            "oi_coverage": round(oi_used / max(oi_used + oi_drop, 1), 5),
            **extra,
        },
        "expiries": [{
            "code": e, "kind": chain[e]["kind"], "ltd": diag[e]["ltd"],
            "trading_days": diag[e]["trading_days"], "T": diag[e]["T"],
            "F": diag[e]["F"], "atm_iv": atm_iv.get(e), "skew": round(slopes.get(e, 0.0), 5),
            "oi": diag[e]["oi_used"], "oi_dropped": diag[e]["oi_dropped"],
            "totals": views[e]["totals"],
        } for e in live if e in forwards and e in views],
        "views": views,
    }

    outdir = os.path.join(DATA, sym)
    hdir = os.path.join(outdir, "history")
    os.makedirs(hdir, exist_ok=True)
    before = sorted(f[:-5] for f in os.listdir(hdir)
                    if f.endswith(".json") and f[:-5].isdigit())
    newest = before[-1] if before else None

    # 歷史檔一律寫（同一天重跑就是覆蓋成最新的一份）
    with open(os.path.join(hdir, f"{day}.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))

    # latest.json 只在這次抓到的日期「不比現有最新的舊」時才更新。
    # 手動觸發若剛好落在來源還沒更新的時段（例如台北下午手動跑、美股那邊 OCC
    # 還沒發布前一日未平倉），抓回來的會是更舊的一天；沒有這道防線就會把首頁
    # 的資料日期往回推。舊資料還是進歷史檔，日期下拉照樣選得到。
    if newest is None or day >= newest:
        with open(os.path.join(outdir, "latest.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    else:
        print(f"  註：這次抓到的是 {day}，比現有最新的 {newest} 舊；"
              f"只寫進歷史檔，latest.json 保持不動。", file=sys.stderr)

    hist = sorted(f[:-5] for f in os.listdir(hdir)
                  if f.endswith(".json") and f[:-5].isdigit())
    json.dump({"dates": hist, "latest": max(hist) if hist else day},
              open(os.path.join(outdir, "index.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    avail = [s for s in symcfg.ORDER
             if os.path.exists(os.path.join(DATA, s, "latest.json"))]
    json.dump({"symbols": [{"code": s, "label": symcfg.SPECS[s]["label"],
                            "desc": symcfg.SPECS[s]["desc"]} for s in avail]},
              open(os.path.join(DATA, "symbols.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    t = views["ALL"]["totals"]
    D = spec["unit_div"]
    print(f"{sym} {day}  S={S_ref:.2f}({ref_src})  到期別={len(views)-1}  契約={len(legs)}  "
          f"OI={oi_used}(覆蓋{oi_used/max(oi_used+oi_drop,1)*100:.1f}%)  "
          f"GEX={(t['gc']-t['gp'])/D:+.2f}  VEX={(t['wc']-t['wp'])/D:+.2f} {spec['unit']}  "
          f"-> {outdir} ({os.path.getsize(os.path.join(outdir,'latest.json'))/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
