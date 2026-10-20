import numpy as np
from sklearn.metrics import average_precision_score
for tag,wz,vz in [("DNS-held-out","artifacts/ml/ncsrd/windows.npz","artifacts/ml/ncsrd/val_scores.npz"),
                  ("time-split","artifacts/ml/ncsrd-timesplit/windows.npz","artifacts/ml/ncsrd-timesplit/val_scores.npz")]:
    w=np.load(wz,allow_pickle=True); v=np.load(vz)
    share=w["share_val"].astype(float); yv=w["y_val"].astype(int)
    p=v["p_attack"]; y=v["y"].astype(int)
    assert len(share)==len(p) and (yv==y).all(), "order mismatch!"
    rank=p*share; pos=int(y.sum())
    def pk(s,k):
        o=np.argsort(-s); return y[o[:k]].mean()
    print(f"==== {tag} (pos={pos}, n={len(y)}) ====  [order check OK]")
    print(f"  true share: attackers mean={share[y==1].mean():.4f} median={np.median(share[y==1]):.4f} | benign mean={share[y==0].mean():.4f}")
    print(f"  AP[p]={average_precision_score(y,p):.4f}  AP[share]={average_precision_score(y,share):.4f}  AP[rank=p*share]={average_precision_score(y,rank):.4f}")
    print(f"  P@pos : p={pk(p,pos):.4f}  share={pk(share,pos):.4f}  rank={pk(rank,pos):.4f}")
    print(f"  P@100 : p={pk(p,100):.4f}  share={pk(share,100):.4f}  rank={pk(rank,100):.4f}")
