import socket,time,json,random
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);p=b'x'*972
ph=[x/1000 for x in range(-200,205,5)]*3
random.Random(7).shuffle(ph)
t=int(time.time())+3;out=[]
for f in ph:
    t+=3
    T=t+f
    while time.time()<T-0.002: time.sleep(0.001)
    while time.time()<T: pass
    a=time.time()
    for _ in range(3): s.sendto(p,("172.30.26.10",5999))
    out.append((t,f,round(a,4)))
print(json.dumps(out))
