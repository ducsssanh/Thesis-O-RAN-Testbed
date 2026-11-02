import json,time,urllib.request
SUPI="imsi-001010123456780"
def api(b):
    r=urllib.request.Request("http://127.0.0.1:8090/v1/defense/tamper",data=json.dumps(b).encode(),headers={"Content-Type":"application/json"},method="POST")
    urllib.request.urlopen(r,timeout=5).read()
SEG=[("const",.1,1),("const",.33,1),("const",.8,1),("const",1.25,1),("const",2,1),("const",5,1),("every3",.8,3),("every3",.33,3)]
out=[]
for name,f,every in SEG:
    t0=time.time();k=0
    if every==1:
        api({"supi":SUPI,"factor":f}); time.sleep(65)
    else:
        while time.time()-t0<65:
            # tamper one whole second out of every 3, switched mid-second
            s=int(time.time())
            if s%every==0: api({"supi":SUPI,"factor":f})
            else: api({"supi":SUPI,"off":True})
            time.sleep(max(0,int(time.time())+1.5-time.time()) if False else 1-(time.time()%1)+.02)
    api({"supi":SUPI,"off":True})
    out.append([name,f,round(t0,3),round(time.time(),3)])
    time.sleep(15)
print(json.dumps(out))
