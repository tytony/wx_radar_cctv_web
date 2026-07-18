#!/usr/bin/env Rscript
# =============================================================================
# export_cctv.R  —  一次性把 WX_Monitor 的 CCTV RData 匯出成靜態 docs/data/cctv.json
#
#   資料範圍：省道/國道 CCTV（全部、剔除隧道）
#             縣市 CCTV 僅取 基隆/新北/台北/桃園/台中/台南/高雄/台東 8 縣市
#             不含 YouTube
#
#   跑法：  Rscript scripts/export_cctv.R
#   跑完後 docs/data/cctv.json 即 self-contained，之後 CI 不需 R、不需 WX_Monitor。
# =============================================================================

suppressPackageStartupMessages({
   library(jsonlite)
})

# --- 可調路徑：WX_Monitor 專案根目錄（CCTV 原始資料來源） --------------------
SRC <- Sys.getenv("WX_MONITOR_SRC", "/home/tytony/shiny-local/apps/WX_Monitor")

# 本腳本所在 repo 根目錄（scripts/ 的上一層）
this_file <- sub("^--file=", "",
                 grep("^--file=", commandArgs(FALSE), value = TRUE)[1])
REPO <- if (!is.na(this_file) && nzchar(this_file)) {
   normalizePath(file.path(dirname(this_file), ".."))
} else {
   normalizePath(".")
}
OUT <- file.path(REPO, "docs", "data", "cctv.json")

stopifnot(dir.exists(SRC))
cat("SRC :", SRC, "\n")
cat("OUT :", OUT, "\n")

TARGET_COUNTIES <- c("Keelung", "NewTaipei", "Taipei", "Taoyuan",
                     "Taichung", "Tainan", "Kaohsiung", "Taitung")
IFRAME_COUNTIES <- c("Taipei", "NewTaipei")   # 政府 viewer 頁需 iframe（見 mod_CCTV.R）

# =============================================================================
# 1. 國道/省道 CCTV（cctvData_highway.RData → cctv.traffic）
# =============================================================================
load(file.path(SRC, "data/processed/cctvData_highway.RData"))   # cctv.traffic, updateTime

hw <- cctv.traffic
hw <- hw[!is.na(hw$VideoStreamURL) & nzchar(hw$VideoStreamURL), ]

# 剔除隧道 CCTV（完全比照 mod_CCTV.R:142-148 的字串+里程過濾）
tunnel <- read.csv(file.path(SRC, "R/data_fetch/cctv/Highway_tunnel.csv"),
                   header = TRUE, fileEncoding = "UTF-8", stringsAsFactors = FALSE)
for (n in seq_len(nrow(tunnel))) {
   hw <- hw[!(hw$RoadNumber == tunnel$RoadNumber[n] &
                 hw$RoadMile > tunnel$km.start[n] &
                 hw$RoadMile < tunnel$km.end[n]), ]
}

highway <- data.frame(
   type  = "highway",
   name  = hw$CCTVname,
   lon   = as.numeric(hw$PositionLon),
   lat   = as.numeric(hw$PositionLat),
   url   = hw$VideoStreamURL,
   embed = "img",
   stringsAsFactors = FALSE
)
highway <- highway[!is.na(highway$lon) & !is.na(highway$lat), ]
cat("highway CCTV:", nrow(highway), "（去隧道後）\n")

# =============================================================================
# 2. 縣市 CCTV（cctvData_county.RData → cctv.county，已含新北）
# =============================================================================
load(file.path(SRC, "data/processed/cctvData_county.RData"))    # cctv.county, updateTime

ct <- cctv.county
ct <- ct[ct$county %in% TARGET_COUNTIES, ]
ct <- ct[!is.na(ct$VideoStreamURL) & nzchar(ct$VideoStreamURL), ]

# RoadName 帶了殘留 names 屬性，取字串值
road_name <- as.character(ct$RoadName)
road_name[is.na(road_name) | !nzchar(road_name)] <- "CCTV"

county <- data.frame(
   type   = "county",
   name   = road_name,
   lon    = as.numeric(ct$PositionLon),
   lat    = as.numeric(ct$PositionLat),
   url    = ct$VideoStreamURL,
   embed  = ifelse(ct$county %in% IFRAME_COUNTIES, "iframe", "img"),
   county = ct$county,
   stringsAsFactors = FALSE
)
county <- county[!is.na(county$lon) & !is.na(county$lat), ]
cat("county CCTV :", nrow(county), "\n")
print(table(county$county))

# =============================================================================
# 3. 合併輸出
# =============================================================================
# 補齊欄位讓兩者 rbind
highway$county <- NA_character_
all_cctv <- rbind(highway, county)

# http → https 升級：站台部署在 https(GitHub Pages),http 串流會被當混合內容擋掉。
# 所有來源皆為 .gov.tw 政府伺服器,升級成 https 是唯一可行機會(無損:http 本就會被擋)。
gov_http <- grepl("^http://[^/]*\\.gov\\.tw", all_cctv$url)
cat("http→https 升級筆數(.gov.tw):", sum(gov_http), "\n")
all_cctv$url[gov_http] <- sub("^http://", "https://", all_cctv$url[gov_http])

dir.create(dirname(OUT), showWarnings = FALSE, recursive = TRUE)
write_json(all_cctv, OUT, auto_unbox = TRUE, pretty = FALSE, na = "null")

cat("\n寫出:", OUT, "  共", nrow(all_cctv), "筆\n")
cat("iframe 筆數（台北/新北）:", sum(all_cctv$embed == "iframe"), "\n")
