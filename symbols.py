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
    "SPY": {
        "label": "SPY", "desc": "SPDR S&P 500 ETF",
        "market": "US", "multiplier": 100.0,
        "currency": "US$", "unit": "百萬美元", "unit_div": 1e6,
        "settle_next_day": False,           # PM 結算，最後交易日收盤即到期
        "calendar": "calendar_us.txt",
        "parity_band": 0.05,
        "strike_band": 0.30,
        "default_view_band": 0.20,
        "source": "CBOE 公開延遲報價（買賣中價）",
        "price_note": "買賣中價",
        "tz_note": "美東時間收盤後更新；未平倉量由 OCC 隔日發布",
    },
    "QQQ": {
        "label": "QQQ", "desc": "Invesco QQQ Trust",
        "market": "US", "multiplier": 100.0,
        "currency": "US$", "unit": "百萬美元", "unit_div": 1e6,
        "settle_next_day": False,
        "calendar": "calendar_us.txt",
        "parity_band": 0.05,
        "strike_band": 0.30,
        "default_view_band": 0.20,
        "source": "CBOE 公開延遲報價（買賣中價）",
        "price_note": "買賣中價",
        "tz_note": "美東時間收盤後更新；未平倉量由 OCC 隔日發布",
    },
}

ORDER = ["TXO", "SPY", "QQQ"]
