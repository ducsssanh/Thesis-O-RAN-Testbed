import json,sys,time,urllib.request
SUPI=sys.argv[1]
def api(b):
    r=urllib.request.Request("http://127.0.0.1:8090/v1/defense/tamper",data=json.dumps(b).encode(),headers={"Content-Type":"application/json"},method="POST")
    urllib.request.urlopen(r,timeout=5).read()
out=[]
for f in (.8,1.25,.33,2,.1,5,.8,1.25,.33,2):
    t0=time.time();api({"supi":SUPI,"factor":f});time.sleep(50);api({"supi":SUPI,"off":True});out.append([f,round(t0,3),round(time.time(),3)]);time.sleep(30)
print(json.dumps(out))
