"""Convert data/out (Kara's data.fetch output) into ../live.json for the hosted game."""
import json,base64,os,sys
def rot(m):
    k=m.get('kinematics',{});sm=k.get('storm_motion') or {};cp=k.get('couplet') or {}
    from datetime import datetime
    ms=lambda s: int(datetime.fromisoformat(s).timestamp()*1000) if s else None
    return {'time':ms(cp.get('time') or sm.get('time')),'stormMotion':{'u':sm.get('u_ms'),'v':sm.get('v_ms')},
      'rotationalVelocity':cp.get('rotational_velocity_ms'),'coreRadius':cp.get('core_radius_m'),
      'lat':cp.get('lat') if cp.get('lat') is not None else sm.get('lat'),'lon':cp.get('lon') if cp.get('lon') is not None else sm.get('lon'),
      'motionMethod':sm.get('method'),'couplet':cp.get('lat') is not None,'classification':cp.get('classification')}
def emb(d):
    m=json.load(open(f'{d}/manifest.json'));nx=m['sources']['nexrad_level2'];ref=nx['products']['ref']
    png='data:image/png;base64,'+base64.b64encode(open(f"{d}/{ref['png']}",'rb').read()).decode()
    from datetime import datetime
    al=[]
    try:
        for f in json.load(open(f'{d}/alerts.geojson'))['features']:
            p=f['properties'];al.append({'event':p['event'],'area':p['areaDesc'],'expires':p.get('expires'),'rk':0 if 'Tornado' in p['event'] else 1})
    except Exception: pass
    storms=[]
    try:
        for f in json.load(open(f'{d}/lsr.geojson'))['features']: storms.append(f['properties'])
    except Exception: pass
    return {'site':m['site'],'site_lat':nx['radar']['lat'],'site_lon':nx['radar']['lon'],'generated':m['generated'],
      'rotation':rot(m),'alerts':al,'storms':storms,
      'radar':{'png':png,'bounds':ref['bounds'],'time':int(datetime.fromisoformat(nx['time']).timestamp()*1000),'source':f"NEXRAD {m['site']} 0.5° reflectivity"}}

if __name__=='__main__':
    src=sys.argv[1] if len(sys.argv)>1 else 'data/out'; dst=sys.argv[2] if len(sys.argv)>2 else '../live.json'
    e=emb(src); json.dump(e,open(dst,'w'),separators=(',',':'))
    print('wrote',dst,os.path.getsize(dst),'bytes; rotation',e['rotation'])
