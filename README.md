# 選擇權曝險地圖 — 台指 TXO / SPY / QQQ

由公開的每日盤後資料，算出全市場的 gamma / vanna 曝險結構，畫成五個面板：
逐履約價 GEX、逐履約價 VEX、GEX vs GEX+ 情境曲線、曝險摘要、到期日結構拆解。
三個標的共用同一套引擎與版面，上方分頁切換。

```
GEX  = M × S² × 0.01 × Σ sign × gamma × OI      元 / 標的移動 1%
VEX  = −M × S ÷ 100  × Σ sign × vanna × OI      元 / 隱含波動率 1 個百分點
GEX+ = GEX + β × VEX
```

純標準庫（Python 3.9+），前端無外部相依，可直接掛 GitHub Pages。

> **先讀這一段。** 「造市商曝險」是**假設**不是觀測——期交所公布的是全市場未平倉，
> 沒有任何欄位能識別造市商的方向。詳見 [METHODOLOGY.md 第 1 節](METHODOLOGY.md)。

## 檔案

| 檔案 | 做什麼 |
|---|---|
| `symbols.py` | 各標的規格（乘數、單位、結算慣例、日曆） |
| `taifex.py` | 台指：期交所 TXO・TX 每日行情 + 證交所加權指數收盤 |
| `cboe.py` | 美股：CBOE 公開延遲報價（SPY / QQQ 完整鏈，用買賣中價） |
| `engine.py` | Black-76、IV 反解、Greeks、遠期 parity、情境曲線 |
| `build.py` | 串起來，產出 `data/latest.json` 與 `data/history/YYYYMMDD.json` |
| `index.html` + `app.js` | 網頁（讀 `data/latest.json`） |
| `make_standalone.py` | 打包成單一 HTML（含資料，可離線 / 寄檔） |
| `calendar_tw.txt` | 台股休市日表，每年期交所公告後更新 |
| `calendar_us.txt` | 美股休市日表 |
| `spot_history.txt` | 加權指數收盤對照檔（回補歷史時用） |
| `selftest.py` | 19 項不變量測試（數學層 + 資料層） |
| `METHODOLOGY.md` | 方法論、定義式、已知限制 |

## 用法

```bash
# 台指：連期交所 + 證交所抓最新一天
python build.py

# 美股：連 CBOE
python build.py --symbol SPY
python build.py --symbol QQQ

# 用已存好的原始 CSV 重跑（離線 / 補歷史）
python build.py --csv raw/taifex_TXO_20260806_20260820.csv --date 20260819 \
                --spot-file spot_history.txt

# 本機看（file:// 會被瀏覽器擋掉 fetch，所以要起個小伺服器）
python -m http.server 8000     # 然後開 http://localhost:8000

# 或打包成單一檔案，直接雙擊開
python make_standalone.py
```

## 開一個新 repo

```bash
cd gexmap
git init -b main
git add -A
git commit -m "台指選擇權曝險地圖：初版"
gh repo create twopt-gexmap --private --source=. --push
# 沒裝 gh 就先在 GitHub 網頁開一個空 repo，然後
# git remote add origin https://github.com/<你的帳號>/twopt-gexmap.git && git push -u origin main
```

`data/history/` 裡已經放了 2026/08/06 ~ 08/20 共 11 個交易日的成果，
推上去之後不用等隔天就有東西可以看。

## 自動更新

`.github/workflows/daily.yml` 的排程（時間都是台北時間，cron 寫死 UTC，所以全年固定）：

| 台北時間 | 標的 | 備註 |
|---|---|---|
| 週一～五 15:15 | TXO | 一般交易時段 13:45 收盤，期交所盤後檔約 15:00 上架 |
| 週一～五 21:20 | SPX / SPY / QQQ | 美東夏令 09:20 / 冬令 08:20，抓的是**前一個**美股收盤 |

**ES（CME 小型 S&P 期貨選擇權）不在排程裡。** CME 的邊緣節點擋掉 GitHub Actions 的 IP——
純 Python 請求回 403、無頭 Chromium 走 HTTP/2 連線被重置、改走 HTTP/1.1 則 90 秒逾時（連試三次）。
程式碼（`cme.py` / `cme_fetch.py`）與單元測試都留著，在一般網路環境下可以直接跑：

```
python cme_fetch.py --out raw/cme_ES.json
python build.py --symbol ES --json raw/cme_ES.json
```


沒有保險班。期交所當天延遲上架的話，到 Actions 頁面按 **Run workflow** 補跑即可
（輸入框留空 = 三個標的都跑，只想補台指就打 `TXO`）。
手動與排程之間有 `concurrency` 群組擋著，不會同時跑，只會排隊。

資料沒更新（假日、來源延遲）時不會產生空提交。提交訊息會帶上各標的實際的資料日期，
例如 `曝險地圖更新 TXO 2026/08/21 / SPY 2026/08/21 / QQQ 2026/08/20`，
從 commit 清單一眼就看得出這次有沒有抓到新的一天。

開啟 GitHub Pages：Settings → Pages → Source 選 `main` branch `/ (root)`。
repo 內已有 `.nojekyll`。

## 介面上可以調的東西

| 控制項 | 說明 |
|---|---|
| 到期別 | 全部合併，或單看某一個到期別（週三選 / 週五選 / 月選） |
| 顯示區間 | 現價 ±3% / ±6% / ±10% / 全部 |
| 履約價分桶 | 50 / 100 / 200 點。週選是 50 點跳、月選是 100 點跳，合併看時分桶才不會參差 |
| GEX 假設 | 買權多・賣權空（預設）／ 兩邊皆空 |
| VEX 假設 | 兩邊皆空（預設）／ 買權多・賣權空。預設不同的理由見 METHODOLOGY 第 5 節 |
| β | GEX+ 的 vanna 回饋強度。0 = 純黏性履約價、1 = 完全黏性 delta |
| 色盲友善 | 綠正紅負 ↔ 藍正橘負 |

## 驗證過的東西

**內部不變量**（`python selftest.py`，19 項，2026/08/06~08/21 共 12 個交易日全數通過）：

- 買賣權 IV 一致性：同履約價價平 ±5% 內，買權 IV 與賣權 IV 中位差 0.13 個波動率點
- 遠期單調性、ATM IV 期限結構單調（20.6% → 28.3%）
- 零丟棄：OI 覆蓋率 100%，沒有任何 leg 因反解失敗被剔除
- Greeks 對 60 位精度數值微分：gamma / vega / vanna 相對誤差 ~1e-14
- 曲線 ↔ 長條圖一致（GEX 與 VEX 皆然）、到期別可加性、β=0 時 GEX+ ≡ GEX
- VEX 在價平兩側同號（vanna 的特徵，vega 版做不到）
- IV 反解往返：4,000 組隨機參數誤差 < 1e-5，零失敗
- 前端 ↔ 後端一致：網頁重組出來的總量與 Flip 跟 Python 完全相同

**外部交叉驗證**（2026/08/21，對照 GoOptions 同日公布數字，兩邊各自獨立實作）：

| 項目 | 本專案 | 對照 |
|---|---|---|
| 現貨 S | 45,224 | 45,224 |
| 總 GEX | +11.36 億 | +11.50 億 |
| Gamma Flip | 44,706 | 44,695 |
| GEX+ Flip | 45,008 | 44,985 |
| 總 VEX | −6.56 億 | −6.30 億 |
| 正/負 GEX 集中前 5 | 履約價、順序、數值全同（±0.01 億） | |

GEX 一側可視為完全吻合；VEX 還有 3~11% 的系統性差距，成因與無法收斂的理由寫在
[METHODOLOGY.md 第 9 節](METHODOLOGY.md)。

## 三個標的的口徑差異

| | 台指 TXO | SPY / QQQ |
|---|---|---|
| 資料源 | 期交所 optDataDown + 證交所加權指數 | CBOE 公開延遲報價端點 |
| 用的價格 | 結算價 | 買賣中價（bid/ask 的中點） |
| 契約乘數 | 50 元/點 | 100 股/口 |
| 顯示單位 | 億元 | 百萬美元 |
| 到期時間 T | 算到最後交易日之次一營業日（最終結算價在那天決定） | 算到最後交易日（PM 結算，收盤即到期） |
| 未平倉時間差 | 當日盤後即公布 | OCC 隔日早上才發布，所以排程放在美東開盤前抓前一日 |

CBOE 端點自帶的 `iv` 與 greeks 欄位大量為 0、不可信，本專案一律自己反解、自己算。

## 資料來源

臺灣期貨交易所「選擇權每日交易行情」`optDataDown`（TXO）、
「期貨每日交易行情」`futDataDown`（TX），一般交易時段、結算價。

僅供個人研究參考，不構成投資建議。
