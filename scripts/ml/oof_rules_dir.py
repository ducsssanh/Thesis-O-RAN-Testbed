import sys, glob, pickle, numpy as np, runpy
sys.argv=["eval_block_rules.py","--data","artifacts/clf/mimic/episodes31_m.pkl,artifacts/clf/mimic/episodes31_l2_m.pkl","x=y:z"]
src=open("scripts/ml/eval_block_rules.py").read().split('print("budget')[0]
ns={}; exec(compile(src,"ebr","exec"),ns)
EP,RULES,pick,stat,first,outcome,active,fa=ns["EP"],ns["RULES"],ns["pick"],ns["stat"],ns["first"],ns["outcome"],ns["active"],ns["fa"]
for rule in (__import__("os").environ.get("RULES") or ",".join(RULES)).split(","):
    det=[];L2=[];F=[];und=[]
    for f in sorted(glob.glob(__import__("os").environ["MODEL_DIR"]+"/fold*_seed*/scores.pkl")):
        S=pickle.load(open(f,"rb")); th,prior,_=pick(S["oof"],rule,0.5)
        R=[]
        for k,v in S["oof"].items():
            e=EP[k]
            if e["other_evasion"]=="L3": continue
            ac=active(e["scen"]["honest"]); R.append(outcome(e,first(stat(v["honest"],ac,rule,prior),th),ac))
        A=[o for o in R if o["attack"]]; det.append(np.mean([o["det"] for o in A])); L2.append(np.mean([o["det"] for o in A if o["ev"]=="L2"]))
        F.append(fa(R)); und.append(np.mean([o["undet_act"] for o in A]))
    print("%-7s OOF block det %.1f%%  L2 %.1f%%  FA %.2f  undetected active s %.1f"%(rule,100*np.mean(det),100*np.mean(L2),np.mean(F),np.mean(und)))
