"""Extract and validate a depot solution file."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scm.data import load_data
from scm.io import network_to_dict
from scm.network import Network, evaluate
from scm.routes_pool import generate_pool
from scm.routing import tsp_exact, two_opt
from experiments.full_exact.run_depot import frontier

def read_solution(path):
    vals={}; inc=False
    for line in Path(path).read_text().splitlines():
        if line.startswith("# Columns"): inc=True; continue
        if line.startswith("# Rows"): break
        if inc and line.strip():
            p=line.split()
            if len(p)==2: vals[p[0]]=float(p[1])
    return vals

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--depot",type=int,required=True)
    ap.add_argument("--solution",required=True); ap.add_argument("--out",required=True)
    args=ap.parse_args()
    data=load_data("Projektdateien")
    cands=frontier(data,args.depot)
    pool=generate_pool(data,cands,pair_threshold_km=100.0,verbose=False)
    vals=read_solution(args.solution)
    frac=[k for k,v in vals.items() if k.startswith(("y_","z_","a_","lam_")) and abs(v-round(v))>1e-6]
    if frac: raise SystemExit(f"{len(frac)} fractional columns")
    stores={i for i in data.stores if vals.get(f"y_{i}",0)>0.5}
    sats={w for w in cands if w!=args.depot and vals.get(f"z_{w}",0)>0.5}
    ass={}
    for i in stores:
        ws=[w for w in cands if vals.get(f"a_{i}_{w}",0)>0.5]
        if len(ws)!=1: raise SystemExit(f"store {i} assignments {ws}")
        ass[i]=ws[0]
    routes={w:[] for w in {args.depot}|sats}
    for idx,r in enumerate(pool):
        mult=int(round(vals.get(f"lam_{idx}",0)))
        if mult<=0: continue
        order=tsp_exact(data,r.warehouse,list(r.stores)) if len(r.stores)<=13 else two_opt(data,r.warehouse,list(r.stores))
        for _ in range(mult): routes[r.warehouse].append(list(order))
    net=Network(depot=args.depot,satellites=sats,stores=stores,assignment=ass,routes=routes)
    res=evaluate(data,net)
    print("depot",args.depot,"profit",res["profit"],"stores",len(stores),"sats",sorted(sats),"trips",sum(len(v) for v in routes.values()))
    Path(args.out).write_text(json.dumps({"depot":args.depot,"network":network_to_dict(net),"breakdown":res},indent=2))

if __name__=="__main__": main()
