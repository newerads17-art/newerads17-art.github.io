"""NEXRAD Level II (unidata-nexrad-level2) decode via MetPy -> lat/lon grid PNGs, points JSON, couplet + cell."""
import io, os, datetime as dt
import numpy as np
from metpy.io import Level2File
from .common import s3_list, s3_get, ref_rgba, vel_rgba, save_png, dump, utcnow
B = "unidata-nexrad-level2"; R_E = 6371000.0

def recent_keys(site, n=2, at=None):
    """Latest n volumes at/before `at` (UTC datetime; default now) -> enables historical replay."""
    ref = at or utcnow(); ks = []
    for d in range(2):
        day = (ref - dt.timedelta(days=d)).strftime("%Y/%m/%d")
        ks += [k for k in s3_list(B, f"{day}/{site}/") if not k.endswith("_MDM")
               and (at is None or k.split("/")[-1][4:19] <= at.strftime("%Y%m%d_%H%M%S"))]
        if len(ks) >= n: break
    return sorted(ks, key=lambda k: k.split("/")[-1])[-n:]

def _sweep(f, moment):
    for i, sw in enumerate(f.sweeps):
        if sw and moment in sw[0][4]: return i, sw
    return None, None

def decode(key):
    f = Level2File(io.BytesIO(s3_get(B, key)))
    lat0, lon0 = f.sweeps[0][0][1].lat, f.sweeps[0][0][1].lon
    out = {"key": key, "site": f.stid.decode() if isinstance(f.stid, bytes) else f.stid, "radar": (lat0, lon0),
           "time": f.dt.replace(tzinfo=dt.timezone.utc)}
    for mom, name in ((b"REF", "ref"), (b"VEL", "vel")):
        i, sw = _sweep(f, mom)
        if sw is None: continue
        hdr = sw[0][4][mom][0]
        az = np.array([r[0].az_angle for r in sw]); el = float(np.mean([r[0].el_angle for r in sw]))
        data = np.array([r[4][mom][1] for r in sw], dtype=float)
        rng = hdr.first_gate + np.arange(hdr.num_gates) * hdr.gate_width  # km
        o = np.argsort(az)
        out[name] = {"az": az[o], "rng_m": rng * 1000.0, "data": data[o], "elev": el, "sweep": i}
    return out

def gate_latlon(lat0, lon0, az_deg, rng_m):
    a = np.deg2rad(az_deg)[:, None]; r = rng_m[None, :]
    x, y = r * np.sin(a), r * np.cos(a)
    return lat0 + np.rad2deg(y / R_E), lon0 + np.rad2deg(x / (R_E * np.cos(np.deg2rad(lat0))))

def grid(scan, name, max_km, res_deg=0.01):
    m = scan[name]; lat0, lon0 = scan["radar"]; keep = m["rng_m"] <= max_km * 1000
    la, lo = gate_latlon(lat0, lon0, m["az"], m["rng_m"][keep]); v = m["data"][:, keep]
    dlat = max_km * 1000 / R_E * 57.2958; dlon = dlat / np.cos(np.deg2rad(lat0))
    b = {"west": lon0 - dlon, "east": lon0 + dlon, "south": lat0 - dlat, "north": lat0 + dlat}
    ny, nx = int(2 * dlat / res_deg), int(2 * dlon / res_deg)
    g = np.full((ny, nx), np.nan); ok = np.isfinite(v)
    ri = ((b["north"] - la[ok]) / (2 * dlat) * ny).astype(int).clip(0, ny - 1)
    ci = ((lo[ok] - b["west"]) / (2 * dlon) * nx).astype(int).clip(0, nx - 1)
    order = np.argsort(np.abs(v[ok]))  # keep the strongest magnitude per pixel
    g[ri[order], ci[order]] = v[ok][order]
    return g, b

def points(scan, name, thresh, step=2, max_km=230):
    m = scan[name]; lat0, lon0 = scan["radar"]; keep = m["rng_m"] <= max_km * 1000
    la, lo = gate_latlon(lat0, lon0, m["az"][::step], m["rng_m"][keep][::step])
    v = m["data"][::step][:, keep][:, ::step]; ok = np.isfinite(v) & (np.abs(v) >= thresh)
    return [[round(float(a), 4), round(float(b), 4), round(float(c), 1)] for a, b, c in zip(la[ok], lo[ok], v[ok])]

def strongest_cell(scan, thresh=45.0):
    """Reflectivity-weighted centroid of the strongest-core region (>=thresh dBZ, else top 0.5%)."""
    m = scan.get("ref")
    if not m: return None
    la, lo = gate_latlon(*scan["radar"], m["az"], m["rng_m"]); d = m["data"]
    ok = np.isfinite(d)
    if not ok.any(): return None
    pk = np.nanargmax(np.where(ok, d, -99)); pla, plo = la.flat[pk], lo.flat[pk]
    th = thresh if np.nanmax(d) >= thresh else np.nanpercentile(d[ok], 99.5)
    near = ok & (d >= th) & (np.hypot((la - pla) * 111e3, (lo - plo) * 111e3 * np.cos(np.deg2rad(pla))) < 20e3)
    if near.sum() < 30: return None  # too small to be a convective core
    w = d[near] - th + 1
    return {"lat": float((la[near] * w).sum() / w.sum()), "lon": float((lo[near] * w).sum() / w.sum()),
            "max_dbz": float(np.nanmax(d)), "time": scan["time"].isoformat()}

def find_couplet(scan, max_km=100, az_win_deg=4.0, min_rot=10.0, max_diam_m=10000):
    """Scan lowest velocity sweep for the strongest cyclonic gate-to-gate-ish azimuthal shear pair.
    Cyclonic (NH) couplet: inbound (Vmin<0) at smaller azimuth, outbound (Vmax>0) at larger azimuth, same range band."""
    m = scan.get("vel")
    if not m: return None
    az, rng, v = m["az"], m["rng_m"], m["data"]; ri = np.where((rng > 5000) & (rng <= max_km * 1000))[0]
    if not len(ri): return None
    daz = np.median(np.diff(az)); w = max(1, int(round(az_win_deg / daz)))
    best = None; vv = v[:, ri]; n = len(az)
    for k in range(1, w + 1):
        b = np.roll(vv, -k, axis=0)  # gate k radials clockwise
        rot = (b - vv) / 2.0
        rot[~(np.isfinite(rot) & (vv < 0) & (b > 0))] = np.nan
        # require the shear to persist over 3 consecutive range gates (rejects single-gate noise / aliasing speckle)
        rot = np.minimum(np.minimum(rot, np.roll(rot, 1, axis=1)), np.roll(rot, -1, axis=1))
        if not np.isfinite(rot).any(): continue
        i, j = np.unravel_index(np.nanargmax(rot), rot.shape)
        r = rng[ri[j]]; diam = r * np.deg2rad(k * daz)
        if rot[i, j] >= min_rot and diam <= max_diam_m and (best is None or rot[i, j] > best[0]):
            best = (float(rot[i, j]), i, (i + k) % n, ri[j], diam, float(vv[i, j]), float(b[i, j]))
    if not best: return None
    rot, i1, i2, gj, diam, vmin, vmax = best
    rf = scan.get("ref")
    if rf is not None:  # must sit in a precipitating echo (>=30 dBZ within ~2 km) to reject clutter/biological/noise
        ai = int(np.argmin(np.abs((rf["az"] - az[i1] + 180) % 360 - 180))); gi = int(np.argmin(np.abs(rf["rng_m"] - rng[gj])))
        win = rf["data"][max(0, ai - 3):ai + 4, max(0, gi - 8):gi + 9]
        if not np.isfinite(win).any() or np.nanmax(win) < 30: return None
    caz = (az[i1] + daz * ((i2 - i1) % n) / 2) % 360
    la, lo = gate_latlon(*scan["radar"], np.array([caz]), np.array([rng[gj]]))
    return {"rotational_velocity_ms": round(rot, 1), "vmax_ms": vmax, "vmin_ms": vmin,
            "core_radius_m": float(round(diam / 2, 0)), "lat": float(la[0, 0]), "lon": float(lo[0, 0]),
            "range_km": float(round(rng[gj] / 1000, 1)), "azimuth_deg": round(float(caz), 1),
            "elevation_deg": round(m["elev"], 2), "time": scan["time"].isoformat(),
            "classification": "TVS-like" if rot >= 25 and diam <= 2000 else ("mesocyclone" if rot >= 15 else "weak rotation")}

def export(scan, outdir, max_km=230):
    os.makedirs(outdir, exist_ok=True); res = {"site": scan["site"], "source": f"s3://{B}/{scan['key']}",
          "time": scan["time"].isoformat(), "radar": {"lat": scan["radar"][0], "lon": scan["radar"][1]}, "products": {}}
    for name, cm, thr in (("ref", ref_rgba, 20.0), ("vel", vel_rgba, 15.0)):
        if name not in scan: continue
        g, b = grid(scan, name, max_km); png = f"nexrad_{name}.png"; save_png(cm(g), os.path.join(outdir, png))
        pts = points(scan, name, thr, max_km=max_km); pj = f"nexrad_{name}_points.json"
        dump({"fields": ["lat", "lon", "dBZ" if name == "ref" else "m/s"], "threshold": thr, "points": pts}, os.path.join(outdir, pj))
        res["products"][name] = {"png": png, "points": pj, "n_points": len(pts), "bounds": b, "elevation_deg": round(scan[name]["elev"], 2),
                                 "units": "dBZ" if name == "ref" else "m/s (+ away from radar)"}
    return res
