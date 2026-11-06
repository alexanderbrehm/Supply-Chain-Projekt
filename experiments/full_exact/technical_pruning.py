"""Valid technical pruning of warehouse candidates for fixed depot 379."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scm.data import WEEKS_PER_YEAR, load_data
from scm.routing import feasible
OUT=Path(__file__).resolve().parent
DEPOT=379

def main():
    data=load_data("Projektdateien")
    raw=json.loads((ROOT/"results/milp_640.json").read_text())
    candidates=[int(w) for w in raw["candidates"]]
    p=data.params
    excluded=[]; keep=[]
    for w in candidates:
        if w==DEPOT:
            keep.append(w); continue
        reach=[i for i in data.stores if feasible(data,w,[i])]
        if not reach:
            excluded.append({"warehouse":w,"reason":"no reachable store"}); continue
        max_margin=sum(max(0.0,data.margin(i)) for i in reach)
        truck=WEEKS_PER_YEAR*p["lkw_lieferungen_pro_woche_pro_zwischenlager"]*(
            p["lkw_fixkosten_pro_fahrt"]+p["lkw_kosten_pro_km"]*2*data.d(DEPOT,w))
        min_d=min(data.d(w,i) for i in reach)
        min_transport=WEEKS_PER_YEAR*3*(p["transporter_fixkosten_pro_route"]+p["transporter_kosten_pro_km"]*2*min_d)
        lb=data.satellite_cost(w)+truck+min_transport
        if max_margin <= lb+1e-9:
            excluded.append({"warehouse":w,"reason":"profitability bound","max_margin":max_margin,"lower_bound":lb})
        else:
            keep.append(w)
    depot_keep=[]; depot_excluded=[]
    for d in data.region_ids:
        d=int(d)
        reach=[i for i in data.stores if feasible(data,d,[i])]
        if not reach:
            depot_excluded.append({"depot":d,"reason":"no reachable store"}); continue
        max_margin=sum(max(0.0,data.margin(i)) for i in reach)
        min_d=min(data.d(d,i) for i in reach)
        lower_bound=data.depot_cost(d)+WEEKS_PER_YEAR*3*(
            p["transporter_fixkosten_pro_route"]
            +p["transporter_kosten_pro_km"]*2*min_d)
        if max_margin <= lower_bound+1e-9:
            depot_excluded.append({"depot":d,"reason":"profitability bound","max_margin":max_margin,"lower_bound":lower_bound})
        else:
            depot_keep.append(d)
    payload={"depot":DEPOT,"warehouse_candidates":{"n_start":len(candidates),"n_keep":len(keep),"n_excluded":len(excluded),"excluded":excluded,"candidates":sorted(keep)},
             "depot_candidates":{"n_start":len(data.region_ids),"n_keep":len(depot_keep),"n_excluded":len(depot_excluded),"excluded":depot_excluded,"candidates":sorted(depot_keep)}}
    (OUT/"technical_pruning.json").write_text(json.dumps(payload,indent=2))
    print(json.dumps({"warehouse_start":len(candidates),"warehouse_keep":len(keep),"warehouse_excluded":len(excluded),"depot_start":len(data.region_ids),"depot_keep":len(depot_keep),"depot_excluded":len(depot_excluded)},indent=2))
    print("warehouse excluded",[(e["warehouse"],e["reason"]) for e in excluded])
    print("depot excluded count",len(depot_excluded))

if __name__=="__main__": main()
