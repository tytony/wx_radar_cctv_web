#!/usr/bin/env python3
# =============================================================================
# simplify_boundaries.py — 產生輕量化台灣縣市界 / 鄉鎮界 GeoJSON
#
#   一次性腳本(邊界幾乎不變,非 CI 流程),類同 export_cctv.R:輸出已 commit 的
#   docs/data/tw_county.geojson、docs/data/tw_town.geojson,前端直接 fetch。
#
#   來源:g0v/twgeojson(縣市 2010、鄉鎮 1982),原檔 9MB / 20MB 過大,故:
#     1) 座標量化到格網(round 至 nd 位小數)→ 相鄰多邊形共用頂點仍重合,不出縫隙
#     2) Douglas-Peucker 去除近共線點(tol 小,邊界為細線,微小落差視覺可忽略)
#   預設 nd=3(~100m)、tol=0.001°,產物約 縣市 0.2MB、鄉鎮 0.7MB。
#
#   用法:
#     python3 scripts/simplify_boundaries.py            # 自動下載來源並輸出
#     python3 scripts/simplify_boundaries.py 0.001      # 指定 DP tolerance(度)
#
#   相依:標準庫(urllib, json)。
# =============================================================================
import json
import os
import sys
import urllib.request

SRC = {
    "county": "https://raw.githubusercontent.com/g0v/twgeojson/master/json/twCounty2010.geo.json",
    "town":   "https://raw.githubusercontent.com/g0v/twgeojson/master/json/twTown1982.geo.json",
}
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "docs", "data")
ND = 3  # 座標保留小數位(3 ≈ 100m)


def dp(points, tol):
    """Douglas-Peucker;points 為 [[x,y],...]。"""
    if len(points) < 3:
        return points
    a, b = points[0], points[-1]
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if seg2 == 0:
            d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
            cx, cy = ax + t * dx, ay + t * dy
            d = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
        if d > dmax:
            dmax, idx = d, i
    if dmax > tol:
        return dp(points[:idx + 1], tol)[:-1] + dp(points[idx:], tol)
    return [a, b]


def simplify_ring(ring, nd, tol):
    out, last = [], None
    for x, y in ring:
        p = [round(x, nd), round(y, nd)]
        if p != last:
            out.append(p)
            last = p
    if len(out) >= 2 and out[0] != out[-1]:
        out.append(out[0][:])
    if len(out) < 4:
        return None
    out = dp(out, tol)
    if out[0] != out[-1]:
        out.append(out[0][:])
    return out if len(out) >= 4 else None


def simplify_geom(geom, nd, tol):
    t = geom["type"]
    if t == "Polygon":
        rings = [r for r in (simplify_ring(r, nd, tol) for r in geom["coordinates"]) if r]
        return {"type": "Polygon", "coordinates": rings} if rings else None
    if t == "MultiPolygon":
        polys = []
        for poly in geom["coordinates"]:
            rings = [r for r in (simplify_ring(r, nd, tol) for r in poly) if r]
            if rings:
                polys.append(rings)
        return {"type": "MultiPolygon", "coordinates": polys} if polys else None
    return geom


def process(url, dst, tol, keep):
    src = json.loads(urllib.request.urlopen(url, timeout=60).read().decode("utf-8"))
    feats = []
    for f in src["features"]:
        g = simplify_geom(f["geometry"], ND, tol)
        if not g:
            continue
        props = {k: f["properties"].get(k) for k in keep if k in f["properties"]}
        feats.append({"type": "Feature", "properties": props, "geometry": g})
    with open(dst, "w", encoding="utf-8") as fp:
        json.dump({"type": "FeatureCollection", "features": feats}, fp,
                  ensure_ascii=False, separators=(",", ":"))
    print(f"{dst}: {len(feats)} features, {os.path.getsize(dst) / 1e6:.2f} MB")


def main():
    tol = float(sys.argv[1]) if len(sys.argv) > 1 else 0.001
    os.makedirs(OUT_DIR, exist_ok=True)
    process(SRC["county"], os.path.join(OUT_DIR, "tw_county.geojson"), tol,
            ["COUNTYNAME", "name"])
    process(SRC["town"], os.path.join(OUT_DIR, "tw_town.geojson"), tol,
            ["COUNTYNAME", "TOWNNAME", "name"])


if __name__ == "__main__":
    main()
