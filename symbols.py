#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""各標的的規格與口徑。要加新標的就在這裡加一筆。"""

SPECS = {
    "TXO": {
        "label": "台指 TXO", "desc": "臺灣加權股價指數選擇權",
        "market": "TW", "multiplier": 50.0,
        "currency": "NT$", "unit": "億元", "unit_div": 1e8,
        "settle_next_day": True,            # 最終結算價在最後交易日之次一營業日決定
        "calendar": "calendar_tw.txt",
        "parity_band": 0.03,                # 反解遠期時取價平 ±band 的中位數
        "strike_band": 0.25,                # 輸出的履約價範圍（相對現貨）
        "default_view_band": 0.20,
        "source": "臺灣期貨交易所 optDataDown（TXO・一般交易時段・結算價）"
                  " + 臺灣證券交易所 加權股價指數收盤",
        "price_note": "結算價",
        "tz_note": "台北時間收盤後更新",
    },
    "SPX": {
        "label": "SPX", "desc": "S&P 500 指數選擇權",
        "market": "US", "multiplier": 100.0,
        "currency": "US$", "unit": "百萬美元", "unit_div": 1e6,
        "settle_next_day": False,           # 逐序列處理：AM 結算的那批已在解析時把 ltd 往前挪
        "calendar": "calendar_us.txt",
        "parity_band": 0.05,
        "strike_band": 0.50,                # 美股的長天期履約價鋪得很開，帶寬太窄會把可觀的 GEX 留在圖外
                                            # （±30% 時 QQQ 有 10.7%、SPY 3.0%、SPX 9.5% 在範圍外）
        "default_view_band": 0.20,
        "cboe_symbol": "_SPX",              # CDN 端點的指數代號要加底線
        "am_roots": ("SPX",),               # SPX 根碼 = AM 結算；SPXW = PM 結算
        "source": "CBOE 公開資料（前一交易日收盤價 ＋ 同日收盤未平倉量）",
        "price_note": "收盤價",
        "tz_note": "美東時間收盤後更新；未平倉量由 OCC 隔日發布",
    },
    "ES": {
        "label": "ES", "desc": "CME 小型 S&P 500 期貨選擇權",
        "market": "US", "multiplier": 50.0,
        "currency": "US$", "unit": "百萬美元", "unit_div": 1e6,
        "settle_next_day": False,           # 逐系列處理：季月選（美式）已在解析時把 ltd 往前挪
        "calendar": "calendar_us.txt",
        "parity_band": 0.05,
        "strike_band": 0.50,
        "default_view_band": 0.20,
        "venue": "CME",
        "source": "CME 公開結算表 + 成交量表（未平倉取當日收盤）",
        "price_note": "結算價",
        "tz_note": "美東時間收盤後更新",
        "spot_note": "主力月期貨結算價",
        "s_label": "期貨",           # 這是期貨選擇權，沒有「現貨」這回事
    },
    "SPY": {
        "label": "SPY", "desc": "SPDR S&P 500 ETF",
        "market": "US", "multiplier": 100.0,
        "currency": "US$", "unit": "百萬美元", "unit_div": 1e6,
        "settle_next_day": False,           # PM 結算，最後交易日收盤即到期
        "calendar": "calendar_us.txt",
        "parity_band": 0.05,
        "strike_band": 0.50,
        "default_view_band": 0.20,
        "source": "CBOE 公開資料（前一交易日收盤價 ＋ 同日收盤未平倉量）",
        "price_note": "收盤價",
        "tz_note": "美東時間收盤後更新；未平倉量由 OCC 隔日發布",
    },
    "QQQ": {
        "label": "QQQ", "desc": "Invesco QQQ Trust",
        "market": "US", "multiplier": 100.0,
        "currency": "US$", "unit": "百萬美元", "unit_div": 1e6,
        "settle_next_day": False,
        "calendar": "calendar_us.txt",
        "parity_band": 0.05,
        "strike_band": 0.50,
        "default_view_band": 0.20,
        "source": "CBOE 公開資料（前一交易日收盤價 ＋ 同日收盤未平倉量）",
        "price_note": "收盤價",
        "tz_note": "美東時間收盤後更新；未平倉量由 OCC 隔日發布",
    },
}

ORDER = ["TXO", "SPX", "ES", "SPY", "QQQ"]
