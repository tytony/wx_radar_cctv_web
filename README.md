# 雷達回波 + CCTV 即時影像網頁

一個純靜態網頁,在 Leaflet 地圖上同時顯示：

- **中央氣象署整合雷達回波**（透明底疊圖,每 10 分鐘由 GitHub Actions 更新）
- **CCTV 即時影像**：國道/省道（全部）+ 縣市（基隆、新北、台北、桃園、台中、台南、高雄、台東）

部署於 GitHub Pages,無需自架伺服器。

## 架構

```
docs/                    # GitHub Pages 網站根目錄(Pages source = GitHub Actions)
  index.html
  css/ js/ vendor/       # 前端與內嵌的 Leaflet / markercluster
  assets/CCTV_icon.svg
  data/cctv.json         # CCTV 清單(由 scripts/export_cctv.R 產生,已 commit)
  radar/latest.{png,json}# 雷達 overlay(CI 於部署時產生,不進 git)
scripts/
  export_cctv.R          # 從 WX_Monitor 匯出 CCTV 清單(一次性/資料變動時重跑)
  fetch_radar.py         # 抓 QPlus 雷達格點 → 解碼 → 透明底 PNG(CI 執行)
.github/workflows/deploy.yml
```

雷達為何要走 GitHub Actions：氣象署原始格點與官網回波圖皆未提供 CORS 標頭,瀏覽器
無法直接 `fetch`／讀取像素。改由 Actions 在伺服器端抓取解碼、渲染成透明 PNG 隨網站
部署,前端用 `L.imageOverlay` 疊圖。CCTV 串流以 `<img>`／`<iframe>` 呈現,不受 CORS 限制。

## 首次部署

1. 於 GitHub 建立新的 repo,把本目錄推上去（分支 `main` 或 `master`）。
2. Repo → **Settings → Pages → Build and deployment → Source** 選 **GitHub Actions**。
3. Actions 頁手動觸發一次 `Build radar & deploy to Pages`（或 push 觸發）。
4. 開啟 `https://<帳號>.github.io/<repo>/`。

之後排程每 10 分鐘自動更新雷達並重新部署。

## 重新產生 CCTV 清單

CCTV 站點清單變動時（來源 RData 更新後）：

```bash
# 需可存取 WX_Monitor 專案(預設 /home/tytony/shiny-local/apps/WX_Monitor)
Rscript scripts/export_cctv.R
# 或指定來源：
WX_MONITOR_SRC=/path/to/WX_Monitor Rscript scripts/export_cctv.R
git add docs/data/cctv.json && git commit -m "chore: 更新 CCTV 清單" && git push
```

## 本機預覽

```bash
python3 scripts/fetch_radar.py        # 需 numpy pillow;產生 docs/radar/latest.*
cd docs && python3 -m http.server 8000
# 瀏覽器開 http://localhost:8000
```

## 已知限制

- 台北/新北的 CCTV 為政府 viewer 頁,以 `<iframe>` 內嵌,若對方設 `X-Frame-Options`
  可能無法內嵌;popup 內附「↗ 另開連結」作為備援。
- 部分政府 MJPEG/JPEG 串流可能有來源（Referer）限制,不保證每支都能在 github.io 播放。
- 雷達以 `L.imageOverlay`（EPSG:4326 線性拉伸）疊圖,與真投影相比在高緯度略有差異,
  台灣範圍內可忽略。
