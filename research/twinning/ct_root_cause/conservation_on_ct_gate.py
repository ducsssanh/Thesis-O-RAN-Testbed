"""Byte-conservation gate replayed on the live ct_gate rows (honest and real tamper through the xApp). Parameters fixed before this
test: W 30 s, theta0 5000 B, L 0.2 s, rho 0.02; a tighter set is shown too. Prints violations and time from tamper start to first violation."""
import numpy as np
SEG=[("hide x0.33","780",1793603012.01),("hide x0.1","780",1793603052.45),("hide x0.8","780",1793603092.87),("frame x2","781",1793603133.29),("frame x5","781",1793603173.71),("frame x1.25","781",1793603214.1)]
R={"780":[],"781":[]}
for l in open("research/twinning/ct_root_cause/ct_gate_all_rows.txt"):
    a=l.split();R[a[0]].append([int(a[1])/1000]+[float(x) for x in a[2:]])
for u in R: R[u]=np.array(sorted(R[u]))
def viol(k,c,W,th,L,rho):
    o=np.zeros(len(k),bool)
    for i in range(len(k)):
        if k[i]==0 and c[i]==0: continue
        a=max(0,i-W+1);D=(c[a:i+1]-k[a:i+1]).sum();S=c[a:i+1].sum()
        o[i]=abs(D)>th+L*max(c[i],c[i-1] if i else 0)+rho*S
    return o
t_h=SEG[0][2]
for W,th,L,rho in ((30,5000,.2,.02),(30,3000,.1,.01)):
    print("W %d theta0 %d L %.1f rho %.2f"%(W,th,L,rho))
    for u,v in R.items():
        t,k,p,n,ct=v[:,0],v[:,1],v[:,2],v[:,3],v[:,4];c=np.maximum(p-57*n,0)
        o=viol(k,c,W,th,L,rho);h=t<t_h;a=((k>0)|(c>0))
        g=((k>=1000)|(p>=1000))
        print("  UE%s honest: active %d, conservation violations %d | same seconds, 1 s c_t outside +-0.2: %d of %d | max |D| %d B"%(u,(h&a).sum(),(o&h).sum(),((abs(ct)>.2)&g&h).sum(),(g&h).sum(),np.abs(np.cumsum((c-k)*h)).max()))
    for name,u,ts in SEG:
        v=R[u];t,k,p,n=v[:,0],v[:,1],v[:,2],v[:,3];c=np.maximum(p-57*n,0)
        o=viol(k,c,W,th,L,rho);m=(t>=ts)&(t<ts+30)
        idx=np.flatnonzero(o&m);act=((k>0)|(c>0))&m
        if idx.size:
            lat=t[idx[0]]-ts;hid=abs((c-k)[(t>=ts)&(t<=t[idx[0]])].sum())
            print("    %-12s first violation after %.0f s, net bytes by then %d, violating share of active seconds %.0f%%"%(name,lat,hid,100*(o&act).sum()/max(act.sum(),1)))
        else: print("    %-12s no violation"%name)

print("Clean latency: KPM set equal to core before each tamper start, so earlier tamper does not stay in the window")
for W,th,L,rho in ((30,5000,.2,.02),(30,3000,.1,.01)):
    print("W %d theta0 %d L %.1f rho %.2f"%(W,th,L,rho))
    for name,u,ts in SEG:
        v=R[u];t,k,p,n=v[:,0],v[:,1].copy(),v[:,2],v[:,3];c=np.maximum(p-57*n,0)
        k[t<ts]=c[t<ts]
        o=viol(k,c,W,th,L,rho);m=(t>=ts)&(t<ts+30);idx=np.flatnonzero(o&m)
        if idx.size:
            e=t[idx[0]];print("    %-12s first violation after %.0f s, |core-KPM| by then %d B"%(name,e-ts,abs((c-k)[(t>=ts)&(t<=e)].sum())))
        else: print("    %-12s no violation"%name)
