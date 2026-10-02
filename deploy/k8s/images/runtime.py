#!/usr/bin/env python3
"""In-pod configuration, subscriber bootstrap and PFCP capture. Never print secrets."""
import json, os, pathlib, re, shutil, signal, subprocess, sys, time
import yaml

def lab():
    return json.loads(pathlib.Path('/input/lab.json').read_text())

def prepare(nf):
    cfg = lab()
    out = pathlib.Path('/config'); out.mkdir(exist_ok=True)
    for p in pathlib.Path('/input').iterdir():
        if p.is_file(): shutil.copyfile(p, out/p.name)
    if nf == 'nr-ue':
        s = (out/'ue.conf').read_text()
        for key, pattern in [('IMSI',r'\d{15}'),('KEY',r'[0-9a-fA-F]{32}'),('OPC',r'[0-9a-fA-F]{32}')]:
            value=os.environ[key]
            if not re.fullmatch(pattern,value): raise ValueError('Invalid SIM field: '+key)
            s=s.replace('__'+key+'__',value)
        (out/'ue.conf').write_text(s)
    elif nf == 'flexric':
        (out/'flexric.conf').write_text('[NEAR-RIC]\nNEAR_RIC_IP = '+cfg['networks']['e2']['addresses']['flexric']+'\n[XAPP]\nDB_NAME = unused\nDB_DIR = /tmp/\n')
    elif nf != 'gnb':
        c=yaml.safe_load((out/'config.yaml').read_text())
        c['database']['password']=os.environ['DB_PASSWORD']
        c['nfs'][nf]['host']=os.environ['POD_IP']
        (out/'config.yaml').write_text(yaml.safe_dump(c,sort_keys=False))
    if nf == 'upf':
        subprocess.run(['sysctl','-w','net.ipv4.ip_forward=1'],check=True)
        subprocess.run(['ip','rule','add','from',cfg['ueSubnet'],'table','5000'],check=True)
        subprocess.run(['ip','route','replace','default','via',cfg['networks']['n6']['addresses']['dn'],'dev','n6','table','5000'],check=True)
    for p in out.iterdir():
        if p.is_file():p.chmod(0o600)

def seed():
    import pymysql
    cfg=lab()
    conn=None
    for _ in range(60):
        try:
            conn=pymysql.connect(host='oai-lab-db',user='root',password=os.environ['DB_ROOT_PASSWORD'],database='oai_db',autocommit=False)
            break
        except pymysql.OperationalError:time.sleep(2)
    if conn is None:raise RuntimeError('Database did not become ready')
    cur=conn.cursor()
    cur.execute('SELECT GET_LOCK(%s,30)',('oai-lab-seed',))
    if cur.fetchone()[0]!=1:raise RuntimeError('Cannot acquire subscriber lock')
    try:
        cur.execute('SHOW TABLES'); tables={r[0] for r in cur.fetchall()}
        if not tables:
            for statement in pathlib.Path('/input/schema.sql').read_text().split(';'):
                if statement.strip():cur.execute(statement)
        elif not {'AuthenticationSubscription','SessionManagementSubscriptionData','AccessAndMobilitySubscriptionData'} <= tables:
            raise RuntimeError('Incomplete database schema; manual recovery required')
        imsi=os.environ['IMSI']; key=os.environ['KEY']; opc=os.environ['OPC']
        if not re.fullmatch(r'\d{15}',imsi) or not all(re.fullmatch(r'[0-9a-fA-F]{32}',x) for x in (key,opc)):
            raise ValueError('Invalid subscriber secret')
        sqn=json.dumps({'sqn':'000000000020','sqnScheme':'NON_TIME_BASED','lastIndexes':{'ausf':0}})
        cur.execute('''INSERT INTO AuthenticationSubscription
          (ueid,authenticationMethod,encPermanentKey,protectionParameterId,sequenceNumber,authenticationManagementField,algorithmId,encOpcKey,supi)
          VALUES (%s,'5G_AKA',%s,%s,%s,'8000','milenage',%s,%s)
          ON DUPLICATE KEY UPDATE encPermanentKey=VALUES(encPermanentKey),encOpcKey=VALUES(encOpcKey),protectionParameterId=VALUES(protectionParameterId)''',(imsi,key,key,sqn,opc,imsi))
        snssai={'sst':cfg['slice']['sst'],'sd':cfg['slice']['sd']}
        dnn={cfg['slice']['dnn']:{'pduSessionTypes':{'defaultSessionType':'IPV4','allowedSessionTypes':['IPV4']},'sscModes':{'defaultSscMode':'SSC_MODE_1','allowedSscModes':['SSC_MODE_1']},'5gQosProfile':{'5qi':9,'priorityLevel':90,'arp':{'priorityLevel':8,'preemptCap':'NOT_PREEMPT','preemptVuln':'PREEMPTABLE'}},'sessionAmbr':{'downlink':'1000 Mbps','uplink':'1000 Mbps'}}}
        plmn=cfg['plmn']['mcc']+cfg['plmn']['mnc']
        cur.execute('''INSERT INTO SessionManagementSubscriptionData (ueid,servingPlmnid,singleNssai,dnnConfigurations) VALUES (%s,%s,%s,%s)
          ON DUPLICATE KEY UPDATE dnnConfigurations=VALUES(dnnConfigurations)''',(imsi,plmn,json.dumps(snssai),json.dumps(dnn)))
        cur.execute('''INSERT INTO AccessAndMobilitySubscriptionData (ueid,servingPlmnid,nssai) VALUES (%s,%s,%s)
          ON DUPLICATE KEY UPDATE nssai=VALUES(nssai)''',(imsi,plmn,json.dumps({'defaultSingleNssais':[snssai]})))
        conn.commit();print('Subscriber synchronized; authentication sequence preserved')
    finally:
        cur.execute('SELECT RELEASE_LOCK(%s)',('oai-lab-seed',));conn.close()

def capture():
    root=pathlib.Path('/artifacts'); root.mkdir(exist_ok=True)
    request=root/'capture-request.json'; proc=None; active=None
    def stop(*_):
        nonlocal proc
        if proc is not None:
            if proc.poll() is None:proc.send_signal(signal.SIGINT)
            proc.wait(timeout=15);proc=None
    signal.signal(signal.SIGTERM,lambda *_:(stop(),sys.exit(0)))
    while True:
        if request.exists():
            wanted=json.loads(request.read_text())['run_id']
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',wanted):raise ValueError('Invalid run ID')
            if wanted!=active:
                stop();active=wanted
                d=root/'runs'/wanted;d.mkdir(parents=True,exist_ok=True)
                # A restarted sidecar must honor an already completed capture.
                # Otherwise tcpdump drops privileges and cannot reopen its old
                # 0644 output, causing a permanent CrashLoopBackOff.
                if (d/'capture.stop').exists():
                    (d/'capture.done').touch()
                else:
                    (d/'capture.ready').unlink(missing_ok=True)
                    (d/'capture.done').unlink(missing_ok=True)
                    (d/'pfcp.pcap').unlink(missing_ok=True)
                    proc=subprocess.Popen(['tcpdump','-U','-n','-i','n4','udp port 8805','-w',str(d/'pfcp.pcap')])
                    time.sleep(1)
                    if proc.poll() is not None:raise RuntimeError('PFCP capture failed')
                    (d/'capture.ready').touch()
        if proc and (root/'runs'/active/'capture.stop').exists():
            stop();(root/'runs'/active/'capture.done').touch()
        if proc and proc.poll() is not None:raise RuntimeError('PFCP capture exited unexpectedly')
        time.sleep(.5)

if __name__=='__main__':
    try:
        {'prepare':lambda:prepare(sys.argv[2]),'seed':seed,'capture':capture}[sys.argv[1]]()
    except Exception as e:
        # No exception repr from database APIs: it could include credentials/SQL.
        print('Runtime operation failed: '+type(e).__name__,file=sys.stderr);sys.exit(1)
