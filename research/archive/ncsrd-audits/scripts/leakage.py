import numpy as np
d=np.load("artifacts/ml/ncsrd/windows.npz", allow_pickle=True)
imtr,imva=d["imeisv_train"],d["imeisv_val"]
ttr,tva=d["t_train"],d["t_val"]; antr,anva=d["an_train"],d["an_val"]
print("TRAIN windows",len(ttr),"VAL windows",len(tva))
print("unique UEs train",len(set(imtr.tolist())),"val",len(set(imva.tolist())),
      "shared",len(set(imtr.tolist())&set(imva.tolist())))
# overlapping-window leakage: a val window's last-step time within 5 steps (~26s) of a train window of the SAME UE
# count benign val windows whose UE also has a train window within +-5*5.14s
W_SEC=5*5.14
tr_by_ue={}
import collections
for ue,t in zip(imtr.tolist(),ttr.tolist()): tr_by_ue.setdefault(ue,[]).append(t)
for ue in tr_by_ue: tr_by_ue[ue]=np.sort(np.array(tr_by_ue[ue]))
near=0; tot=0
for ue,t in zip(imva.tolist(),tva.tolist()):
    arr=tr_by_ue.get(ue)
    if arr is None: continue
    tot+=1
    i=np.searchsorted(arr,t)
    lo=arr[max(i-1,0)]; hi=arr[min(i,len(arr)-1)]
    if min(abs(t-lo),abs(hi-t))<=W_SEC: near+=1
print(f"val windows whose UE appears in train: {tot}/{len(tva)}")
print(f"val windows within {W_SEC:.0f}s of a same-UE train window (overlap-leak candidates): {near}")
print("val attack composition:", {int(k):int((anva==k).sum()) for k in np.unique(anva)})
print("train attack composition:", {int(k):int((antr==k).sum()) for k in np.unique(antr)})
