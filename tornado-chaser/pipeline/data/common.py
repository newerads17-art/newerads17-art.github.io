"""Shared helpers: public S3 listing over HTTPS (no keys), colormaps, output dir."""
import os, re, json, datetime as dt, requests
import numpy as np
from PIL import Image

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
UA = {"User-Agent": "tornado-sim-data/0.1 (dale-team)"}
S = requests.Session(); S.headers.update(UA)

def utcnow():
    return dt.datetime.now(dt.timezone.utc)

def s3_list(bucket, prefix):
    keys, token = [], None
    while True:
        p = {"list-type": "2", "prefix": prefix}
        if token: p["continuation-token"] = token
        r = S.get(f"https://{bucket}.s3.amazonaws.com/", params=p, timeout=60); r.raise_for_status()
        keys += re.findall(r"<Key>([^<]+)</Key>", r.text)
        m = re.search(r"<NextContinuationToken>([^<]+)<", r.text)
        if not m: return keys
        token = m.group(1)

def s3_get(bucket, key, rng=None):
    h = {"Range": f"bytes={rng[0]}-{'' if rng[1] is None else rng[1]}"} if rng else {}
    r = S.get(f"https://{bucket}.s3.amazonaws.com/{key}", headers=h, timeout=180); r.raise_for_status()
    return r.content

# NWS-like reflectivity colormap (dBZ thresholds -> RGBA)
REF_STOPS = [(5,(4,233,231)),(10,(1,159,244)),(15,(3,0,244)),(20,(2,253,2)),(25,(1,197,1)),(30,(0,142,0)),
             (35,(253,248,2)),(40,(229,188,0)),(45,(253,149,0)),(50,(253,0,0)),(55,(212,0,0)),(60,(188,0,0)),
             (65,(248,0,253)),(70,(152,84,198)),(75,(253,253,253))]

def ref_rgba(dbz):
    dbz = np.asarray(dbz, float); out = np.zeros(dbz.shape + (4,), np.uint8)
    for th, c in REF_STOPS:
        m = np.isfinite(dbz) & (dbz >= th); out[m, :3] = c; out[m, 3] = 220
    return out

def vel_rgba(v, vmax=40.0):
    v = np.asarray(v, float); out = np.zeros(v.shape + (4,), np.uint8)
    m = np.isfinite(v); t = np.nan_to_num(np.clip(v / vmax, -1, 1))
    g = (np.clip(-t, 0, 1) * 255).astype(np.uint8); r = (np.clip(t, 0, 1) * 255).astype(np.uint8)
    out[..., 0] = r; out[..., 1] = g; out[..., 2] = 40; out[..., 3] = np.where(m, 220, 0)
    return out  # green = inbound (toward radar), red = outbound

def save_png(rgba, path):
    os.makedirs(os.path.dirname(path), exist_ok=True); Image.fromarray(rgba, "RGBA").save(path, optimize=True)

def dump(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: json.dump(obj, f, separators=(",", ":"), default=str)
