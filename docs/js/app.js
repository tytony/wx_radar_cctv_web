/* =============================================================================
 * 雷達回波 + CCTV 即時影像  前端主程式
 *   - 底圖：CartoDB Positron(預設)/ Esri WorldStreetMap / OSM,可切換
 *   - 雷達：docs/radar/latest.{png,json}(由 GitHub Actions 每 10 分產生),imageOverlay
 *   - CCTV：docs/data/cctv.json(國道省道 + 8 縣市),markercluster
 * ============================================================================= */
"use strict";

// dBZ 色階,同 mod_leaflet_radarLayer.R(圖例用;疊圖已由 PNG 呈現)
const RAD_COL = ["#00FF41", "#30E80C", "#5DC700", "#FAF100", "#FFD200",
                 "#FF8709", "#FA4A09", "#FF0000", "#CC076F", "#A41DFF",
                 "#D064FF", "#E6A1FF"];
const RADAR_OPACITY = 0.6;          // 同 config.ini opacity_radar
const RADAR_POLL_MS = 3 * 60 * 1000; // 每 3 分鐘輪詢

// -----------------------------------------------------------------------------
// 地圖
// -----------------------------------------------------------------------------
const ATTR_SRC = '雷達 &amp; CCTV：中央氣象署 / TDX / 各縣市政府';
// 顯示範圍限定 110~130E、15~30N;zoom 不小於 7
const MAP_BOUNDS = L.latLngBounds([15, 110], [30, 130]);

const map = L.map("map", {
   preferCanvas: true,
   minZoom: 7,
   maxBounds: MAP_BOUNDS,
   maxBoundsViscosity: 1.0,
}).setView([23.7, 121.0], 7);

const baseLayers = {
   "CartoDB Positron": L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
         maxZoom: 19,
         subdomains: "abcd",
         attribution: '&copy; OpenStreetMap contributors &copy; CARTO｜' + ATTR_SRC,
      }),
   "Esri WorldStreetMap": L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
         maxZoom: 19,
         attribution: 'Tiles &copy; Esri｜' + ATTR_SRC,
      }),
   "OpenStreetMap": L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
         maxZoom: 19,
         attribution: '&copy; OpenStreetMap contributors｜' + ATTR_SRC,
      }),
};
baseLayers["CartoDB Positron"].addTo(map); // 預設底圖

// -----------------------------------------------------------------------------
// 雷達 imageOverlay + 輪詢更新
// -----------------------------------------------------------------------------
let radarOverlay = null;

async function refreshRadar() {
   try {
      const ts = Date.now();
      const meta = await fetch(`radar/latest.json?t=${ts}`, { cache: "no-store" }).then(r => r.json());
      const bounds = meta.bounds; // [[s,w],[n,e]]
      const pngUrl = `radar/latest.png?t=${ts}`;

      if (radarOverlay) {
         radarOverlay.setUrl(pngUrl);
         radarOverlay.setBounds(bounds);
      } else {
         radarOverlay = L.imageOverlay(pngUrl, bounds, {
            opacity: RADAR_OPACITY,
            interactive: false,
         }).addTo(map);
         overlaysCtl.addOverlay(radarOverlay, "雷達回波");
      }
      const el = document.getElementById("radar-time");
      if (el) el.textContent = `雷達時間：${meta.refTime || "—"}`;
   } catch (e) {
      console.error("雷達載入失敗", e);
      const el = document.getElementById("radar-time");
      if (el) el.textContent = "雷達時間：載入失敗";
   }
}

// -----------------------------------------------------------------------------
// CCTV
// -----------------------------------------------------------------------------
const cctvIcon = L.icon({
   iconUrl: "assets/CCTV_icon.svg",
   iconSize: [22, 22],
   iconAnchor: [11, 11],
   popupAnchor: [0, -10],
});

function escapeHtml(s) {
   return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
}

// 依 mod_CCTV.R 的 popup 樣式產生 HTML
function popupHtml(c) {
   const name = escapeHtml(c.name);
   const url = c.url; // 直接用於 src/href
   if (c.embed === "iframe") {
      // 政府 viewer 頁(台北/新北):可能被 X-Frame-Options 擋,故同時附上另開連結
      return `<h4><a href="${escapeHtml(url)}" target="_blank" rel="noopener">${name} ↗</a></h4>`
           + `<iframe src="${escapeHtml(url)}" width="400" height="300" loading="lazy"`
           + ` referrerpolicy="no-referrer"></iframe>`;
   }
   const w = c.type === "highway" ? 330 : 400;
   // MJPEG/JPEG 串流,以 <img> 呈現(瀏覽器自動更新)
   return `<h4><a href="${escapeHtml(url)}" target="_blank" rel="noopener">${name} ↗</a></h4>`
        + `<img src="${escapeHtml(url)}" width="${w}" referrerpolicy="no-referrer"`
        + ` alt="CCTV 影像載入中…" onerror="this.alt='此攝影機影像無法載入(來源限制)';">`;
}

function makeClusterGroup() {
   return L.markerClusterGroup({
      showCoverageOnHover: false,
      disableClusteringAtZoom: 14,
      chunkedLoading: true,
   });
}

async function loadCCTV() {
   const highwayGroup = makeClusterGroup();
   const countyGroup = makeClusterGroup();

   let data;
   try {
      data = await fetch("data/cctv.json", { cache: "no-store" }).then(r => r.json());
   } catch (e) {
      console.error("CCTV 資料載入失敗", e);
      return;
   }

   let nHw = 0, nCt = 0;
   for (const c of data) {
      if (!isFinite(c.lat) || !isFinite(c.lon)) continue;
      const m = L.marker([c.lat, c.lon], { icon: cctvIcon, title: c.name });
      // popup 內容延遲產生(點擊時才建 iframe/img,避免同時開數千串流)
      m.bindPopup(() => popupHtml(c), { minWidth: 340, maxHeight: 340 });
      if (c.type === "highway") { highwayGroup.addLayer(m); nHw++; }
      else { countyGroup.addLayer(m); nCt++; }
   }

   map.addLayer(highwayGroup);
   map.addLayer(countyGroup);
   overlaysCtl.addOverlay(highwayGroup, `國道/省道 CCTV (${nHw})`);
   overlaysCtl.addOverlay(countyGroup, `縣市 CCTV (${nCt})`);
   console.log(`CCTV 載入完成：國道省道 ${nHw}、縣市 ${nCt}`);
}

// -----------------------------------------------------------------------------
// 圖例
// -----------------------------------------------------------------------------
function buildLegend() {
   // 反轉色序:紫(高)在上、綠(低)在下,標 70,65,…,15(同 App)
   const labels = [70, 65, 60, 55, 50, 45, 40, 35, 30, 25, 20, 15];
   const body = document.getElementById("legend-body");
   const cols = RAD_COL.slice().reverse();
   // 12 色對應 12 個標籤區間
   labels.forEach((lab, i) => {
      const row = document.createElement("div");
      row.className = "legend-row";
      row.innerHTML =
         `<span class="legend-swatch" style="background:${cols[i]}"></span>` +
         `<span class="legend-label">${lab}</span>`;
      body.appendChild(row);
   });
}

// -----------------------------------------------------------------------------
// 圖層控制 + 啟動
// -----------------------------------------------------------------------------
const overlaysCtl = L.control.layers(baseLayers, {}, { collapsed: false }).addTo(map);

buildLegend();
refreshRadar();
setInterval(refreshRadar, RADAR_POLL_MS);
loadCCTV();
