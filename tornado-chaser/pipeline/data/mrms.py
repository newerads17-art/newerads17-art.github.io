"""MRMS MergedReflectivityQCComposite from noaa-mrms-pds, cropped to bbox -> PNG + bounds."""
import gzip, os, tempfile, datetime as dt
import numpy as np, eccodes
from .common import s3_list, s3_get, ref_rgba, save_png, utcnow
B = "noaa-mrms-pds"; PROD = "MergedReflectivityQCComposite_00.50"

def latest_key():
    for d in range(2):
        day = (utcnow() - dt.timedelta(days=d)).strftime("%Y%m%d")
        ks = [k for k in s3_list(B, f"CONUS/{PROD}/{day}/") if k.endswith(".grib2.gz")]
        if ks: return sorted(ks)[-1]
    raise RuntimeError("no MRMS files")

def fetch(out_png, bbox):
    key = latest_key(); raw = gzip.decompress(s3_get(B, key))
    with tempfile.NamedTemporaryFile(suffix=".grib2") as t:
        t.write(raw); t.flush()
        with open(t.name, "rb") as fh:
            g = eccodes.codes_grib_new_from_file(fh)
            nx, ny = eccodes.codes_get(g, "Ni"), eccodes.codes_get(g, "Nj")
            la1, lo1 = eccodes.codes_get(g, "latitudeOfFirstGridPointInDegrees"), eccodes.codes_get(g, "longitudeOfFirstGridPointInDegrees")
            la2, lo2 = eccodes.codes_get(g, "latitudeOfLastGridPointInDegrees"), eccodes.codes_get(g, "longitudeOfLastGridPointInDegrees")
            vals = eccodes.codes_get_values(g).reshape(ny, nx); vt = f"{eccodes.codes_get(g,'validityDate')}{eccodes.codes_get(g,'validityTime'):04d}"
            eccodes.codes_release(g)
    lo1 = lo1 - 360 if lo1 > 180 else lo1; lo2 = lo2 - 360 if lo2 > 180 else lo2
    lats = np.linspace(la1, la2, ny); lons = np.linspace(lo1, lo2, nx)   # N->S rows
    w, s, e, n = bbox
    ri = np.where((lats >= s) & (lats <= n))[0]; ci = np.where((lons >= w) & (lons <= e))[0]
    sub = vals[ri[0]:ri[-1]+1, ci[0]:ci[-1]+1].astype(float); sub[sub < 0] = np.nan
    save_png(ref_rgba(sub), out_png)
    t = dt.datetime.strptime(vt, "%Y%m%d%H%M").replace(tzinfo=dt.timezone.utc)
    return {"source": f"s3://{B}/{key}", "time": t.isoformat(), "png": os.path.basename(out_png), "units": "dBZ",
            "bounds": {"west": float(lons[ci[0]]), "south": float(lats[ri[-1]]), "east": float(lons[ci[-1]]), "north": float(lats[ri[0]])},
            "shape": list(sub.shape), "max_dbz": float(np.nanmax(sub)) if np.isfinite(sub).any() else None}
