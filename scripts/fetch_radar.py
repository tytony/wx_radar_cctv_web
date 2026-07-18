#!/usr/bin/env python3
# =============================================================================
# fetch_radar.py  —  抓 CWA QPlus 整合雷達回波原始格點 → 解碼 → 產生透明底 RGBA PNG
#
#   由 GitHub Actions 排程執行(每 10 分鐘)。伺服器端抓取,不受瀏覽器 CORS 限制。
#   移植自 WX_Monitor 的 R/data_fetch/data_cwb_qplus.R:
#     - qp_latestFilePath("雷達觀測-整合回波")   取最新檔路徑
#     - read_qplus_grid()                          CSC 稀疏格點解碼
#     - cwb_qp_radar() 的方位/範圍                 t() + 上下翻轉,EPSG:4326
#     - dBZ 色階同 mod_leaflet_radarLayer.R
#
#   輸出：docs/radar/latest.png   (透明底回波)
#         docs/radar/latest.json  {refTime, bounds:[[s,w],[n,e]]}
#
#   相依：numpy, pillow(標準庫 urllib 抓取,不需 requests)
# =============================================================================
import json
import os
import ssl
import sys
import random
import urllib.request
from datetime import datetime, timezone, timedelta

import numpy as np
from PIL import Image

HOST = "https://qpeplus.cwa.gov.tw"
DATA_TAG = "雷達觀測-整合回波"
TPE = timezone(timedelta(hours=8))  # Asia/Taipei

# 站台部署範圍(cell edge),同 cwb_qp_radar():lon[113.495,128.505] lat[15.995,31.005]
EXTENT = dict(w=113.495, e=128.505, s=15.995, n=31.005)

# dBZ 色階(同 mod_leaflet_radarLayer.R:566-572),於 dBZ [14.9, 69.9] 線性內插
RAD_COL = ["#00FF41", "#30E80C", "#5DC700", "#FAF100", "#FFD200",
           "#FF8709", "#FA4A09", "#FF0000", "#CC076F", "#A41DFF",
           "#D064FF", "#E6A1FF"]
DBZ_MIN, DBZ_MAX = 14.9, 69.9

# 原始格點為 0.01°(約 1501x1501),前端疊圖放大後邊緣呈方塊狀。
# 在伺服器端以雙線性內插超取樣,讓回波邊緣平滑、視覺解析度提升(檔案仍以 PNG 壓縮)。
UPSCALE = 3

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "docs", "radar")

# QPlus 憑證鏈偶有問題,放寬(僅抓公開觀測格點,無敏感資料)
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE
_UA = {"User-Agent": "Mozilla/5.0 (wx-radar-cctv-web)"}


def _get(url, as_bytes=False):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, context=_SSL, timeout=60) as r:
        data = r.read()
    return data if as_bytes else data.decode("utf-8", "replace")


def latest_file_path():
    """對應 qp_latestFilePath('雷達觀測-整合回波')。回傳 (完整url, data_time datetime)。"""
    u = f"{HOST}/pub/webmap/webmap_json/?lang=tw&r={random.randint(1000, 99999)}"
    obs = json.loads(_get(u))["obs_data"]
    for x in obs:
        if x["data_tag"] == DATA_TAG:
            rec = x["data_file"][-1]
            if isinstance(rec, list):
                rec = rec[-1]
            ts = rec.get("data_time_timestamp")
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc) if ts else None
            return HOST + rec["file_path"], dt
    raise RuntimeError(f"webmap json 找不到 data_tag={DATA_TAG}")


def read_qplus_grid(text):
    """對應 read_qplus_grid():CSC 稀疏格點解碼,回傳 float 陣列 (nrow, ncol)。"""
    lines = text.split("\n")
    dims = lines[0].split(",")
    nrow, ncol = int(dims[0]), int(dims[1])

    # 第 1 行 linearTransform(ratio,offset) → 取第一個數字為 ratio
    import re
    m = re.search(r"[-+]?\d*\.\d+|\d+", lines[1])
    ratio = float(m.group()) if m else 1.0

    def after_colon(s):
        return s.split(":", 1)[1] if ":" in s else s

    col_ix = np.fromstring(after_colon(lines[4]), sep=",", dtype=np.int64)  # colIdx
    row_ptr = np.fromstring(after_colon(lines[5]), sep=",", dtype=np.int64)  # rowPtr
    vals = np.fromstring(after_colon(lines[6]), sep=",", dtype=np.float64) * ratio  # vals

    # 比照 R:matrix[cbind(L5, col_idx)] <- L7
    #   L5 = colIdx(第一維索引)、col_idx 由 rowPtr 差分展開(第二維索引)
    counts = np.diff(row_ptr)
    second_ix = np.repeat(np.arange(ncol), counts)

    out = np.full((nrow, ncol), np.nan, dtype=np.float64)
    n = min(len(col_ix), len(vals), len(second_ix))
    out[col_ix[:n], second_ix[:n]] = vals[:n]
    return out


def orient(mat):
    """比照 cwb_qp_radar():t() 後上下翻轉;回傳 row0=最北 的陣列。"""
    mat = mat.T
    mat = mat[::-1, :]
    mat[mat < 0] = np.nan
    return mat


def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def build_lut(levels=1024):
    """dBZ→RGBA 查表:在 12 色間 RGB 線性內插(視覺上等同 leaflet colorNumeric)。"""
    stops = np.array([_hex(c) for c in RAD_COL], dtype=np.float64)  # (12,3)
    pos = np.linspace(0.0, 1.0, len(stops))
    t = np.linspace(0.0, 1.0, levels)
    lut = np.empty((levels, 3), dtype=np.uint8)
    for ch in range(3):
        lut[:, ch] = np.round(np.interp(t, pos, stops[:, ch])).astype(np.uint8)
    return lut


def upscale_field(mat, factor):
    """以雙線性內插把 dBZ 格點放大 factor 倍;無回波(NaN)區域用 mask 還原成透明。

    直接對上色後的 RGBA 放大會讓透明(黑)像素滲入邊緣造成暗邊,故改在數值場放大:
      - 值場:NaN 先填 DBZ_MIN 再雙線性放大(邊緣自然收斂到最低色)
      - 遮罩:isfinite 放大後以 0.5 為界重建有效區
    """
    if factor <= 1:
        return mat
    h, w = mat.shape
    finite = np.isfinite(mat)
    filled = np.where(finite, mat, DBZ_MIN).astype(np.float32)
    size = (w * factor, h * factor)
    hi = np.asarray(
        Image.fromarray(filled, mode="F").resize(size, Image.BILINEAR),
        dtype=np.float64,
    )
    himask = np.asarray(
        Image.fromarray((finite * 255).astype(np.uint8), mode="L").resize(size, Image.BILINEAR)
    ) >= 128
    hi[~himask] = np.nan
    return hi


def colorize(mat):
    """把 dBZ 陣列上色成 RGBA;<14.9 或 NaN → 透明。"""
    levels = 1024
    lut = build_lut(levels)
    h, w = mat.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)

    valid = np.isfinite(mat) & (mat >= DBZ_MIN)
    tnorm = np.clip((mat - DBZ_MIN) / (DBZ_MAX - DBZ_MIN), 0.0, 1.0)
    idx = np.zeros_like(mat, dtype=np.int64)
    idx[valid] = np.clip((tnorm[valid] * (levels - 1)).astype(np.int64), 0, levels - 1)

    rgb = lut[idx]                      # (h,w,3)
    rgba[..., :3] = rgb
    rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
    return rgba


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    url, dt_utc = latest_file_path()
    print("radar file:", url, flush=True)

    text = _get(url)
    mat = read_qplus_grid(text)
    mat = orient(mat)
    print("grid shape:", mat.shape,
          "dBZ range:", np.nanmin(mat) if np.isfinite(mat).any() else None,
          "~", np.nanmax(mat) if np.isfinite(mat).any() else None, flush=True)

    mat = upscale_field(mat, UPSCALE)
    rgba = colorize(mat)
    png_path = os.path.join(OUT_DIR, "latest.png")
    Image.fromarray(rgba, "RGBA").save(png_path, optimize=True)

    ref_local = dt_utc.astimezone(TPE) if dt_utc else datetime.now(TPE)
    meta = {
        "refTime": ref_local.strftime("%Y-%m-%d %H:%M"),
        "refTimeISO": ref_local.isoformat(),
        "bounds": [[EXTENT["s"], EXTENT["w"]], [EXTENT["n"], EXTENT["e"]]],
        "generatedAt": datetime.now(TPE).isoformat(),
    }
    with open(os.path.join(OUT_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    npix = int((rgba[..., 3] > 0).sum())
    print(f"wrote {png_path}  ({rgba.shape[1]}x{rgba.shape[0]}, {npix} echo px)")
    print("refTime:", meta["refTime"])
    if npix == 0:
        print("WARNING: 無回波像素(可能無降水或解碼異常)", file=sys.stderr)


if __name__ == "__main__":
    main()
