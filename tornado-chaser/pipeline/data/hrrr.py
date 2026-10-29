"""HRRR (noaa-hrrr-bdp-pds) surface fields via .idx byte-range reads, cropped to bbox."""
import os, tempfile, datetime as dt
import numpy as np, eccodes
from .common import s3_list, s3_get, dump, utcnow
B = "noaa-hrrr-bdp-pds"
WANT = {"UGRD:10 m above ground": "u10", "VGRD:10 m above ground": "v10", "CAPE:surface": "cape",
        "USTM:0-6000 m above ground": "ustm", "VSTM:0-6000 m above ground": "vstm",
        "HLCY:3000-0 m above ground": "srh03"}

def latest_run():
    for h in range(0, 6):
        t = utcnow() - dt.timedelta(hours=h); key = f"hrrr.{t:%Y%m%d}/conus/hrrr.t{t:%H}z.wrfsfcf00.grib2"
        if s3_list(B, key + ".idx"): return key
    raise RuntimeError("no HRRR run")

def fetch(path, bbox, stride=3):
    key = latest_run(); idx = s3_get(B, key + ".idx").decode().splitlines(); rows = [l.split(":") for l in idx]
    out = {"source": f"s3://{B}/{key}", "fields": {}}; lats = lons = None
    for i, r in enumerate(rows):
        name = WANT.get(f"{r[3]}:{r[4]}")
        if not name or name in out["fields"]: continue
        end = int(rows[i + 1][1]) - 1 if i + 1 < len(rows) else None
        msg = s3_get(B, key, (int(r[1]), end)); g = eccodes.codes_new_from_message(msg)
        v = eccodes.codes_get_values(g).reshape(eccodes.codes_get(g, "Ny"), eccodes.codes_get(g, "Nx"))
        if lats is None:
            lats = eccodes.codes_get_array(g, "latitudes").reshape(v.shape)
            lons = eccodes.codes_get_array(g, "longitudes").reshape(v.shape); lons = np.where(lons > 180, lons - 360, lons)
            w, s, e, n = bbox; mask = (lats >= s) & (lats <= n) & (lons >= w) & (lons <= e)
            ys, xs = np.where(mask); sl = (slice(ys.min(), ys.max() + 1, stride), slice(xs.min(), xs.max() + 1, stride))
            out["lat"] = np.round(lats[sl], 3).tolist(); out["lon"] = np.round(lons[sl], 3).tolist()
            vd, vt = str(eccodes.codes_get(g,'validityDate')), eccodes.codes_get(g,'validityTime'); out["valid"] = f"{vd[:4]}-{vd[4:6]}-{vd[6:]}T{vt//100:02d}:{vt%100:02d}:00+00:00"
        out["fields"][name] = np.round(v[sl], 1).tolist(); eccodes.codes_release(g)
    out["shape"] = [len(out["lat"]), len(out["lat"][0])]; out["grid_stride_km"] = 3 * stride
    dump(out, path)
    f = out["fields"]; c = (out["shape"][0] // 2, out["shape"][1] // 2)
    bunk = {"time": out["valid"], "u_ms": f["ustm"][c[0]][c[1]], "v_ms": f["vstm"][c[0]][c[1]], "lat": out["lat"][c[0]][c[1]], "lon": out["lon"][c[0]][c[1]]} if "ustm" in f else None
    return {"json": os.path.basename(path), "source": out["source"], "valid": out["valid"], "fields": list(f), "shape": out["shape"]}, bunk
