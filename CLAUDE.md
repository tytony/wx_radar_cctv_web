# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概觀

純靜態網頁,在 Leaflet 地圖上同時疊放**中央氣象署整合雷達回波**與 **CCTV 即時影像**(國道/省道全部 + 8 縣市)。部署於 GitHub Pages,無後端伺服器。整個前端在 `docs/`,由兩支離線腳本(`scripts/`)餵資料。

## 常用指令

```bash
# 本機預覽(產生雷達 overlay 後起靜態伺服器)
python3 scripts/fetch_radar.py          # 需 numpy pillow;輸出 docs/radar/latest.{png,json}
cd docs && python3 -m http.server 8000  # 瀏覽器開 http://localhost:8000

# 重新產生 CCTV 清單(來源 RData 變動時才需要,非 CI 流程)
Rscript scripts/export_cctv.R                                  # 預設讀 /home/tytony/shiny-local/apps/WX_Monitor
WX_MONITOR_SRC=/path/to/WX_Monitor Rscript scripts/export_cctv.R

# 重新產生行政區界(邊界幾乎不變,非 CI 流程)
python3 scripts/simplify_boundaries.py                         # 下載 g0v geojson,量化簡化後輸出 docs/data/tw_{county,town}.geojson
```

沒有 build / lint / test 步驟——前端是手寫 JS,vendor 函式庫(Leaflet、markercluster)已 commit 進 `docs/vendor/`。

## 架構要點

**兩條資料管線,更新頻率天差地別:**

1. **雷達(每 10 分鐘,CI 自動)** — `scripts/fetch_radar.py` 由 `.github/workflows/deploy.yml` 的 cron 執行,在伺服器端抓 CWA QPlus 原始格點、解碼、上色成透明底 RGBA PNG,連同 `docs/` 一起部署到 Pages。前端 `app.js` 每 3 分鐘輪詢 `radar/latest.json`,以 `L.imageOverlay` 疊圖。`docs/radar/latest.*` 是產物,**不進 git**(見 `.gitignore`),每次部署由 CI 重建。

2. **CCTV 清單(幾乎不變,手動)** — `scripts/export_cctv.R` 一次性從 WX_Monitor 專案的 RData 匯出 `docs/data/cctv.json`(**已 commit**)。跑完後 self-contained,CI 完全不碰 R,也不需要存取 WX_Monitor。

3. **行政區界(幾乎不變,手動)** — `scripts/simplify_boundaries.py` 下載 g0v/twgeojson 的縣市(2010)、鄉鎮(1982)邊界,經**座標量化 + Douglas-Peucker** 簡化(原檔 9MB/20MB → 約 0.2MB/0.7MB),輸出 `docs/data/tw_county.geojson`、`docs/data/tw_town.geojson`(**已 commit**)。前端 `loadBoundaries()` 以 `L.geoJSON` 疊為可切換圖層(縣市界預設開、鄉鎮界預設關,僅描邊不填色、`interactive:false` 不攔點擊)。簡化用量化(非拓樸簡化)以確保相鄰多邊形共用頂點重合、不出縫隙。

**為何雷達要繞道 CI 而非前端直抓:** 氣象署格點與官網回波圖都沒有 CORS 標頭,瀏覽器無法 `fetch`/讀像素。改由 Actions 伺服器端渲染成 PNG。CCTV 串流走 `<img>`/`<iframe>`,不受 CORS 限制,故可留在前端。

**移植自 WX_Monitor 的關鍵對應(改動時務必保持一致):**
- `fetch_radar.py` 的格點解碼、方位翻轉、dBZ 色階,逐段對應 WX_Monitor 的 `R/data_fetch/data_cwb_qplus.R` 與 `mod_leaflet_radarLayer.R`(檔內註解標了行號)。
- dBZ 12 色色階 `RAD_COL` 在 `fetch_radar.py`(疊圖)與 `app.js`(圖例)**各有一份,必須同步**。
- CCTV popup 樣式、隧道過濾邏輯對應 `mod_CCTV.R`。

## 修改時的注意事項

- **雷達疊圖需 Web Mercator 列重取樣,勿移除:** `fetch_radar.py` 的 `mercator_warp_rows()` 把等經緯度間距的格點,重新取樣成等 Web Mercator Y 間距。原因:前端 `L.imageOverlay` 只用兩角點座標線性拉伸圖片、不做逐像素重投影,但底圖是 Web Mercator——網格橫跨 16~31°N(15 度緯度跨距很大),若直接輸出等緯度間距的圖,拉伸到地圖上會在台灣緯度(~23°N)一帶造成約 20~24 公里的偏北視覺誤差(緯度愈高、同樣的緯度間距在 Mercator 地圖上愈長)。R 版 WX_Monitor 用 `leaflet::addRasterImage()` 沒有這個問題,因為該函式內部會把 raster 重投影到 EPSG:3857 再輸出;純前端 JS 沒有對應機制,故改在伺服器端手動做等效重取樣。經 R 端 `t()+flip` 解碼、方位邏輯逐 element 比對驗證兩者一致後才定位出此 bug(不在解碼/翻轉,而在最後的疊圖投影)。
- **CCTV URL 一律 http→https:** `export_cctv.R` 尾段把所有 `.gov.tw` 的 http 升成 https,因為站台跑在 https、混合內容會被瀏覽器擋。新增來源時沿用此規則。
- **iframe vs img:** 台北/新北是政府 viewer 頁,`embed: "iframe"`(可能被 `X-Frame-Options` 擋,故 popup 另附開新視窗連結);其餘是 MJPEG/JPEG 串流,`embed: "img"`。此欄位由 `export_cctv.R` 決定,`app.js` 的 `popupHtml()` 據此分流。
- **CCTV popup 延遲產生:** marker 用 `bindPopup(() => popupHtml(c))`,點擊才建 iframe/img,避免同時開數千串流。勿改成預先產生。
- **CI 抓雷達失敗不擋部署:** workflow 對 `fetch_radar.py` 設 `continue-on-error`,失敗時仍部署上一版網站 + CCTV。
- GitHub 排程在 repo 連續 60 天無活動後會停用;繁忙時 cron 可能延遲數分鐘。
