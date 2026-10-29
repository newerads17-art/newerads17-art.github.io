# tornado-sim data layer (Kara)

Free public NOAA/NWS/IEM sources only, no API keys.

## Run
```
cd /workspace/tornado-sim && python3 -m venv .venv && . .venv/bin/activate && pip install -r data/requirements.txt
python -m data.fetch --site KTLX                         # live; bbox defaults to radar ±2.5° lon / ±2° lat
python -m data.fetch --site KTLX --bbox -99 34 -96 37 --no-hrrr
python -m data.fetch --site KTLX --time 201305202022     # NEXRAD replay (Moore 2013); alerts/MRMS/HRRR stay live
```
Writes `data/out/`. Each source runs independently; a failure is recorded in the manifest as `status:"error"` and the rest still run.

## Sources
| key | source | output |
|---|---|---|
| nws_alerts | api.weather.gov/alerts/active (Tornado/Svr Tstm warnings+watches, Tornado Emergency), bbox-filtered | `alerts.geojson` |
| storm_reports | IEM LSR GeoJSON (tornado, funnel, hail, wind), last N h | `lsr.geojson` |
| mrms | s3://noaa-mrms-pds CONUS/MergedReflectivityQCComposite_00.50 (latest), cropped | `mrms_ref.png` (0.01° grid, north-up) |
| nexrad_level2 | s3://unidata-nexrad-level2, lowest REF and VEL sweeps, decoded with MetPy | `nexrad_ref.png`, `nexrad_vel.png` (0.01° lat/lon grid, 230 km), `nexrad_*_points.json` |
| hrrr | s3://noaa-hrrr-bdp-pds wrfsfcf00 via .idx byte ranges | `hrrr.json` |

## manifest.json
```
{version, generated (ISO UTC), replay_time, site, bbox:{west,south,east,north},
 sources:{
  nws_alerts:{status, geojson, count}, storm_reports:{status, geojson, count},
  mrms:{status, source, time, png, units:"dBZ", bounds:{west,south,east,north}, shape:[rows,cols], max_dbz},
  nexrad_level2:{status, site, source, time, radar:{lat,lon},
     products:{ref|vel:{png, points, n_points, bounds, elevation_deg, units}}},
  hrrr:{status, json, source, valid, fields:[...], shape}},
 kinematics:{storm_motion, couplet, notes:[]},
 files:{name: bytes}}
```
PNG images are equirectangular (linear lat/lon) with the given bounds, north at the top. Reflectivity uses NWS-style colors; velocity is green = toward the radar and red = away (±40 m/s scale).

`nexrad_*_points.json` = `{fields:["lat","lon","dBZ"|"m/s"], threshold, points:[[lat,lon,value],...]}` (every 2nd ray/gate, |value| ≥ threshold).

`hrrr.json` = `{source, valid, lat:[[..]], lon:[[..]], shape, grid_stride_km:9, fields:{u10,v10 (m/s), cape (J/kg), srh03 (m²/s²), ustm,vstm (Bunkers right-mover m/s)}}`

`alerts.geojson` features have properties {id,event,severity,headline,areaDesc,sent,onset,expires,senderName,parameters{tornadoDetection,maxHailSize,maxWindGust,eventMotionDescription}}.

### kinematics (for physics)
```
storm_motion:{u_ms, v_ms, lat, lon, time (ISO UTC), method, [dt_s, cell_max_dbz]}
couplet:{rotational_velocity_ms, vmax_ms, vmin_ms, core_radius_m, lat, lon, time, range_km, azimuth_deg,
         elevation_deg, classification ("weak rotation"|"mesocyclone"|"TVS-like"), method}
```
- **Storm motion** `method:"nexrad_cell_tracking"`: displacement of the reflectivity-weighted centroid of the strongest core (≥45 dBZ, ≥30 gates, within 20 km of the peak) between the last two volume scans. It is rejected if the cell is below 35 dBZ, moves faster than 40 m/s, or jumps more than 15 km. Fallback `method:"hrrr_bunkers_right_mover_USTM_VSTM_0-6km"`: HRRR's USTM/VSTM at the bbox center. If neither is available, every field is null and `method` is null.
- **Couplet**: on the lowest velocity sweep within 100 km, find the strongest pair with inbound (V<0) at the smaller azimuth and outbound (V>0) 1 to 4° clockwise, in the same range gate. The pair must persist over 3 consecutive range gates and sit within ~2 km of ≥30 dBZ echo. `Vrot=(Vmax−Vmin)/2`, `core_radius = half the arc distance between the two gates`. It requires Vrot ≥ 10 m/s and diameter ≤ 10 km. Otherwise all values are null and `method` starts with `none_found`.
- u = east and v = north, in m/s.

## Browser module `data/index.js`
Registered in `../modules.json` as `"data":"data/index.js"`. It reads `out/` relative to itself and exports `getAlerts()`, `getRadarFrames({lat,lon})`, `getStorms()`, and `getRotation()` per INTERFACES.md (times in epoch ms). It falls back to `fallback/data.js` when out/ is missing or the point is outside coverage.
`getRotation()` returns `{time, stormMotion:{u,v}, rotationalVelocity, coreRadius, lat, lon, motionMethod, couplet:boolean}`.

## Known gaps
- No velocity dealiasing, so Vrot is capped near Nyquist (~26–28 m/s). For Moore 2013 it finds the right location but underestimates strength.
- Only one NEXRAD frame plus one MRMS frame per run. Re-run on a schedule to animate.
- LSR/alerts are snapshots taken at run time. NEXRAD Level III isn't implemented, and Level II is used instead.
