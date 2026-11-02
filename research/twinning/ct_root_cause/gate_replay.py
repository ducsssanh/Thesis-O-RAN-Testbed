"""Offline replay of the live gate (c_t_w over W seconds, EWMA 0.1, mask below 0.85, unmask above 0.90, per node) on benign P4 TTI
runs: KPM of UE1 scaled by a factor, in every second or one second in three. Scaling KPM only, as the gate reads UL rate. Usage: gate_replay.py <run>..."""
import json,sys,numpy as np
EPS,BETA=1000,57;SUP=("imsi-001010123456780","imsi-001010123456781")
def load(r):
    by={}
    for l in open(r+"/defense/features.jsonl"):
        x=json.loads(l);by.setdefault(x["supi"],{})[round(x["at_ms"]/1000)]=(x["rate_ul_kbps"]*125,max(x["prof_ul_kbps"]*125-BETA*x["prof_ul_pps"],0))
    return by
def run(by,W,f,every):
    secs=sorted(set(by[SUP[0]])&set(by[SUP[1]]));t,m=1.0,False;tot=mk=0;first=None;gs=0
    scale=lambda s:f if s%every==0 else 1
    for s in secs:
        for sup,tam in ((SUP[0],True),(SUP[1],False)):
            kk=[by[sup][j][0]*(scale(j) if tam else 1) for j in range(s-W+1,s+1) if j in by[sup]];cc=[by[sup][j][1] for j in range(s-W+1,s+1) if j in by[sup]]
            k,c=sum(kk),sum(cc);e=EPS*max(len(kk),1);cur=by[sup][s]
            if (cur[0]>0 or cur[1]>0) and (k>=e or c>=e):
                t+=.1*((abs(np.log((k+e)/(c+e)))<=.2)-t);m=t<.9 if m else t<.85
                if tam:
                    tot+=1;mk+=m
                    if m and first is None:first=gs
                    gs+=1
    return mk,tot
print("masked share of UE1 gate seconds, sum over runs")
R=[load(r) for r in sys.argv[1:]]
for W in (1,3):
    row=[]
    for f,ev,n in ((1,1,"benign"),(.8,1,"x0.8"),(1.25,1,"x1.25"),(.33,1,"x0.33"),(2,1,"x2"),(.8,3,"x0.8 1/3"),(1.25,3,"x1.25 1/3"),(.33,3,"x0.33 1/3"),(2,3,"x2 1/3")):
        a=[run(b,W,f,ev) for b in R];row.append("%s %.1f%%"%(n,100*sum(x[0] for x in a)/max(sum(x[1] for x in a),1)))
    print("W=%d: "%W+"  ".join(row),"(gate secs",sum(run(b,W,1,1)[1] for b in R),")")
