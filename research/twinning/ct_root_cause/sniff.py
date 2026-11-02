import socket,struct,time,json,sys,collections
T=float(sys.argv[1]);s=socket.socket(socket.AF_PACKET,socket.SOCK_DGRAM,socket.htons(3));s.bind(("oaitun_ue1",0));s.settimeout(.5)
try: s.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1<<24)
except Exception: pass
end=time.time()+T;C=collections.Counter();B=collections.Counter();E=[]
while time.time()<end:
    try:d,a=s.recvfrom(65535)
    except socket.timeout:continue
    if a[2]!=4 or len(d)<20:   # outgoing only
        continue
    pr=d[9];L=(d[2]<<8)|d[3];ip=d[0]&15;k=str(pr)
    if pr==1:
        t,c=d[ip*4],d[ip*4+1];k="icmp%d/%d"%(t,c)
        inner=d[ip*4+8:]
        if len(E)<40:E.append((round(time.time(),3),t,c,L,socket.inet_ntoa(d[16:20]),inner[9] if len(inner)>9 else None,socket.inet_ntoa(inner[12:16]) if len(inner)>15 else None,socket.inet_ntoa(inner[16:20]) if len(inner)>19 else None,((inner[(inner[0]&15)*4+2]<<8)|inner[(inner[0]&15)*4+3]) if len(inner)>(inner[0]&15)*4+3 else None))
    elif pr==17: k="udp"
    elif pr==6: k="tcp"
    C[k]+=1;B[k]+=L
print(json.dumps({"pkts":C,"bytes":B,"icmp":E}))
