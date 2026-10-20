import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score, precision_recall_curve
trap = getattr(np,"trapezoid",None) or np.trapz
def auc_trap(y,p):
    pr,rc,_=precision_recall_curve(y,p); return float(trap(pr[::-1], rc[::-1]))
for tag,path in [("leave-one-attack-out(DNS)","artifacts/ml/ncsrd/val_scores.npz"),
                 ("time-split","artifacts/ml/ncsrd-timesplit/val_scores.npz")]:
    d=np.load(path); p=d["p_attack"]; y=d["y"].astype(int); rank=d["rank"]
    n=len(y); pos=int(y.sum())
    print("====",tag,"===="); print(f"  n={n} pos={pos} prevalence={pos/n:.4%} ratio={(n-pos)/max(pos,1):.1f}:1")
    print(f"  AP={average_precision_score(y,p):.4f}  PR-AUC_trap={auc_trap(y,p):.4f}  ROC-AUC={roc_auc_score(y,p):.4f}")
    for thr in (0.5,0.7,0.9):
        pred=p>=thr; tp=int((pred&(y==1)).sum()); fp=int((pred&(y==0)).sum())
        print(f"  thr={thr}: recall={tp/max(pos,1):.4f} FPR={fp/max(n-pos,1):.4f} precision={tp/max(tp+fp,1):.4f} (TP={tp} FP={fp})")
    for score,name in [(rank,"rank=p*share"),(p,"p alone")]:
        order=np.argsort(-score)
        for k in (pos,100):
            topk=order[:k]; print(f"  P@{k} [{name}]={y[topk].mean():.4f} R@{k}={y[topk].sum()/max(pos,1):.4f}")
    print()
