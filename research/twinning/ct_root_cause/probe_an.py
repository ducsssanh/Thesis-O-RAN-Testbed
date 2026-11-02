import json,sys,numpy as np
sp=sys.argv[1]
S=json.load(open(sp+'/probe_send.json'));M={}
for l in open(sp+'/probe_feat.jsonl'):
    try:x=json.loads(l)
    except: continue
    if x['supi']=='imsi-001010123456780':
        M[round(x['at_ms']/1000)]=(x['rate_ul_kbps']*125,x['prof_ul_kbps']*125)
print('sends',len(S),'seconds',len(M))
ROWS=[]
for t,f,a in S:
    k={L:M.get(L,(0,0))[0] for L in range(t-1,t+3)}
    c={L:M.get(L,(0,0))[1] for L in range(t-1,t+3)}
    ROWS.append((f,t,max(k,key=k.get)-t if max(k.values())>500 else None,max(c,key=c.get)-t if max(c.values())>500 else None,round(max(k.values())),round(max(c.values())),round(sum(k.values())),round(sum(c.values()))))
ROWS.sort(key=lambda x:(x[0],x[1]))
print('phase_ms: KPM label-t | core label-t  | agree?')
for p in sorted(set(r[0] for r in ROWS)):
    r=[x for x in ROWS if x[0]==p]
    print('%6.0f  K %s  C %s'%(p*1000,[x[2] for x in r],[x[3] for x in r]))
K=[(r[0],r[2]) for r in ROWS if r[2] is not None];C=[(r[0],r[3]) for r in ROWS if r[3] is not None]
print('counted',len(K),len(C))
for name,R in (('KPM',K),('core',C)):
    a=np.array(R,float)
    # boundary: best phase b so that phase<b -> label L0, phase>=b -> L0+1
    v=np.unique(a[:,1]);print(name,'labels',dict(zip(*np.unique(a[:,1],return_counts=True))))
    best=min(((np.sum((a[:,0]<b)&(a[:,1]!=v[0]))+np.sum((a[:,0]>=b)&(a[:,1]!=v[-1]))),b) for b in np.arange(-.2,.21,.005))
    print('  best split phase %.0f ms, misplaced %d of %d'%(best[1]*1000,best[0],len(a)))
    near=a[(a[:,0]>=best[1]-.03)&(a[:,0]<=best[1]+.03)]
    print('  around split',[(round(p*1000),int(l)) for p,l in sorted(map(tuple,near))][:40])
dis=[r for r in ROWS if r[2] is not None and r[3] is not None and r[2]!=r[3]]
print('sends where KPM and core chose different seconds:',len(dis),'of',len(ROWS),[(round(r[0]*1000),r[2],r[3]) for r in dis])
