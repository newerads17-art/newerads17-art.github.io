"""NWS active warnings (api.weather.gov) + local storm reports (IEM LSR GeoJSON)."""
import datetime as dt
from .common import S, dump, utcnow
EVENTS = ["Tornado Warning", "Severe Thunderstorm Warning", "Tornado Watch", "Severe Thunderstorm Watch", "Tornado Emergency"]

def _in_bbox(geom, bbox):
    if not bbox or not geom: return True
    w, s, e, n = bbox
    def pts(c):
        if isinstance(c[0], (int, float)): yield c
        else:
            for x in c: yield from pts(x)
    return any(w <= p[0] <= e and s <= p[1] <= n for p in pts(geom["coordinates"]))

def fetch_alerts(path, bbox=None):
    r = S.get("https://api.weather.gov/alerts/active", params={"event": ",".join(EVENTS)},
              headers={"Accept": "application/geo+json"}, timeout=60); r.raise_for_status()
    feats = []
    for f in r.json().get("features", []):
        if bbox and f.get("geometry") and not _in_bbox(f["geometry"], bbox): continue
        p = f["properties"]
        feats.append({"type": "Feature", "geometry": f.get("geometry"), "properties": {k: p.get(k) for k in
            ("id", "event", "severity", "headline", "areaDesc", "sent", "onset", "expires", "senderName")} |
            {"parameters": {k: p.get("parameters", {}).get(k) for k in ("tornadoDetection", "maxHailSize", "maxWindGust", "eventMotionDescription")}}})
    dump({"type": "FeatureCollection", "fetched": utcnow().isoformat(), "features": feats}, path)
    return len(feats)

def fetch_lsr(path, hours=24, bbox=None):
    end = utcnow(); start = end - dt.timedelta(hours=hours)
    f = "%Y-%m-%dT%H:%MZ"
    r = S.get("https://mesonet.agron.iastate.edu/geojson/lsr.geojson",
              params={"sts": start.strftime(f), "ets": end.strftime(f), "wfos": ""}, timeout=60); r.raise_for_status()
    keep = {"TORNADO", "FUNNEL CLOUD", "HAIL", "TSTM WND DMG", "TSTM WND GST", "NON-TSTM WND DMG", "WALL CLOUD"}
    feats = [x for x in r.json().get("features", []) if str(x["properties"].get("typetext", "")).upper() in keep
             and _in_bbox(x["geometry"], bbox)]
    dump({"type": "FeatureCollection", "fetched": end.isoformat(), "window_hours": hours, "features": feats}, path)
    return len(feats)
