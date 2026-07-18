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
```

沒有 build / lint / test 步驟——前端是手寫 JS,vendor 函式庫(Leaflet、markercluster)已 commit 進 `docs/vendor/`。

## 架構要點

**兩條資料管線,更新頻率天差地別:**

1. **雷達(每 10 分鐘,CI 自動)** — `scripts/fetch_radar.py` 由 `.github/workflows/deploy.yml` 的 cron 執行,在伺服器端抓 CWA QPlus 原始格點、解碼、上色成透明底 RGBA PNG,連同 `docs/` 一起部署到 Pages。前端 `app.js` 每 3 分鐘輪詢 `radar/latest.json`,以 `L.imageOverlay` 疊圖。`docs/radar/latest.*` 是產物,**不進 git**(見 `.gitignore`),每次部署由 CI 重建。

2. **CCTV 清單(幾乎不變,手動)** — `scripts/export_cctv.R` 一次性從 WX_Monitor 專案的 RData 匯出 `docs/data/cctv.json`(**已 commit**)。跑完後 self-contained,CI 完全不碰 R,也不需要存取 WX_Monitor。

**為何雷達要繞道 CI 而非前端直抓:** 氣象署格點與官網回波圖都沒有 CORS 標頭,瀏覽器無法 `fetch`/讀像素。改由 Actions 伺服器端渲染成 PNG。CCTV 串流走 `<img>`/`<iframe>`,不受 CORS 限制,故可留在前端。

**移植自 WX_Monitor 的關鍵對應(改動時務必保持一致):**
- `fetch_radar.py` 的格點解碼、方位翻轉、dBZ 色階,逐段對應 WX_Monitor 的 `R/data_fetch/data_cwb_qplus.R` 與 `mod_leaflet_radarLayer.R`(檔內註解標了行號)。
- dBZ 12 色色階 `RAD_COL` 在 `fetch_radar.py`(疊圖)與 `app.js`(圖例)**各有一份,必須同步**。
- CCTV popup 樣式、隧道過濾邏輯對應 `mod_CCTV.R`。

## 修改時的注意事項

- **CCTV URL 一律 http→https:** `export_cctv.R` 尾段把所有 `.gov.tw` 的 http 升成 https,因為站台跑在 https、混合內容會被瀏覽器擋。新增來源時沿用此規則。
- **iframe vs img:** 台北/新北是政府 viewer 頁,`embed: "iframe"`(可能被 `X-Frame-Options` 擋,故 popup 另附開新視窗連結);其餘是 MJPEG/JPEG 串流,`embed: "img"`。此欄位由 `export_cctv.R` 決定,`app.js` 的 `popupHtml()` 據此分流。
- **CCTV popup 延遲產生:** marker 用 `bindPopup(() => popupHtml(c))`,點擊才建 iframe/img,避免同時開數千串流。勿改成預先產生。
- **CI 抓雷達失敗不擋部署:** workflow 對 `fetch_radar.py` 設 `continue-on-error`,失敗時仍部署上一版網站 + CCTV。
- GitHub 排程在 repo 連續 60 天無活動後會停用;繁忙時 cron 可能延遲數分鐘。
