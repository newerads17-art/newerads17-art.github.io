"""CLI: python -m data.fetch --site KTLX [--bbox W S E N] [--no-hrrr]  -> data/out/manifest.json"""
import argparse, math, os, traceback, datetime as dt
from .common import OUT, dump, utcnow
from . import nws, mrms, nexrad, hrrr

SITES = {"KTLX": (35.333, -97.278), "KFWS": (32.573, -97.303), "KINX": (36.175, -95.564), "KICT": (37.654, -97.443),
         "KDDC": (37.761, -99.969), "KAMA": (35.233, -101.709), "KLBB": (33.654, -101.814), "KDMX": (41.731, -93.723),
         "KOAX": (41.320, -96.367), "KLZK": (34.836, -92.262), "KSHV": (32.451, -93.841), "KBMX": (33.172, -86.770),
         "KGWX": (33.897, -88.329), "KHTX": (34.931, -86.084), "KLSX": (38.699, -90.683), "KEAX": (38.810, -94.264)}

def step(man, name, fn):
    try: man["sources"][name] = {"status": "ok", **(fn() or {})}
    except Exception as e:
        man["sources"][name] = {"status": "error", "error": f"{type(e).__name__}: {e}"}; traceback.print_exc()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--site", default="KTLX")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    ap.add_argument("--out", default=OUT); ap.add_argument("--no-hrrr", action="store_true")
    ap.add_argument("--time", help="replay NEXRAD at/before UTC YYYYmmddHHMM (alerts/MRMS/HRRR stay live)")
    ap.add_argument("--lsr-hours", type=int, default=24); a = ap.parse_args()
    site = a.site.upper(); os.makedirs(a.out, exist_ok=True)
    if not a.bbox:
        la, lo = SITES.get(site, (35.333, -97.278)); a.bbox = [lo - 2.5, la - 2, lo + 2.5, la + 2]
    man = {"version": 1, "replay_time": a.time, "generated": utcnow().isoformat(), "site": site,
           "bbox": dict(zip(("west", "south", "east", "north"), a.bbox)), "sources": {}, "files": {}}
    P = lambda f: os.path.join(a.out, f)
    step(man, "nws_alerts", lambda: {"geojson": "alerts.geojson", "count": nws.fetch_alerts(P("alerts.geojson"), a.bbox)})
    step(man, "storm_reports", lambda: {"geojson": "lsr.geojson", "count": nws.fetch_lsr(P("lsr.geojson"), a.lsr_hours, a.bbox)})
    step(man, "mrms", lambda: mrms.fetch(P("mrms_ref.png"), a.bbox))
    scans = []
    def do_nexrad():
        for k in nexrad.recent_keys(site, 2, dt.datetime.strptime(a.time, '%Y%m%d%H%M') if a.time else None):
            scans.append(nexrad.decode(k))
        return nexrad.export(scans[-1], a.out)
    step(man, "nexrad_level2", do_nexrad)
    bunk = None
    if not a.no_hrrr:
        def do_hrrr():
            nonlocal bunk; info, bunk = hrrr.fetch(P("hrrr.json"), a.bbox); return info
        step(man, "hrrr", do_hrrr)
    man["kinematics"] = kinematics(scans, bunk)
    for f in sorted(os.listdir(a.out)):
        if f != "manifest.json": man["files"][f] = os.path.getsize(P(f))
    dump(man, P("manifest.json")); print(f"wrote {P('manifest.json')}")
    for k, v in man["sources"].items(): print(f"  {k}: {v['status']} {v.get('error','')}")
    print("  kinematics:", man["kinematics"])

def kinematics(scans, bunk):
    k = {"storm_motion": None, "couplet": None, "notes": []}
    if len(scans) >= 2:
        c0, c1 = nexrad.strongest_cell(scans[-2]), nexrad.strongest_cell(scans[-1])
        dt_s = (scans[-1]["time"] - scans[-2]["time"]).total_seconds()
        if c0 and c1 and dt_s > 0 and min(c0["max_dbz"], c1["max_dbz"]) < 35:
            k["notes"].append("no convective cell >=35 dBZ to track")
        elif c0 and c1 and dt_s > 0:
            dx = (c1["lon"] - c0["lon"]) * 111320 * math.cos(math.radians(c1["lat"])); dy = (c1["lat"] - c0["lat"]) * 110540
            u, v = dx / dt_s, dy / dt_s
            if math.hypot(u, v) <= 40 and math.hypot(dx, dy) < 15000:
                k["storm_motion"] = {"u_ms": round(u, 1), "v_ms": round(v, 1), "lat": c1["lat"], "lon": c1["lon"],
                                     "time": c1["time"], "method": "nexrad_cell_tracking", "dt_s": dt_s, "cell_max_dbz": c1["max_dbz"]}
            else: k["notes"].append(f"cell tracking rejected (implausible {math.hypot(u, v):.0f} m/s / {math.hypot(dx, dy)/1000:.0f} km jump)")
    if not k["storm_motion"] and bunk:
        k["storm_motion"] = {"u_ms": bunk["u_ms"], "v_ms": bunk["v_ms"], "lat": bunk["lat"], "lon": bunk["lon"],
                             "time": bunk["time"], "method": "hrrr_bunkers_right_mover_USTM_VSTM_0-6km"}
    if not k["storm_motion"]: k["storm_motion"] = {"u_ms": None, "v_ms": None, "lat": None, "lon": None, "time": None, "method": None}
    cp = nexrad.find_couplet(scans[-1]) if scans else None
    if cp: k["couplet"] = cp | {"method": "max cyclonic azimuthal shear pair, lowest velocity sweep: Vrot=(Vmax-Vmin)/2, core_radius=half gate separation"}
    else:
        k["couplet"] = {"rotational_velocity_ms": None, "core_radius_m": None, "lat": None, "lon": None,
                        "time": scans[-1]["time"].isoformat() if scans else None, "method": "none_found (Vrot>=10 m/s, diameter<=10 km)"}
    return k

if __name__ == "__main__":
    main(); import sys; sys.stdout.flush(); os._exit(0)  # skip eccodes teardown double-free
