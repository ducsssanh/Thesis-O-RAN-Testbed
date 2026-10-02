import json,sys
d=json.load(open(sys.argv[1]))
rows=[]
for e in d:
    f=e["formatted"]; k=f["key"]; far=f["value"]["far"]; aa=far["apply_action"]
    ohc=far["forwarding_parameters"]["outer_header_creation"]
    rows.append({"seid":k["seid"],"pdr":k["pdr_id"],"far":far["far_id"]["far_id"],
                 "drop":int(aa["drop"],16),"forw":int(aa["forw"],16),
                 "ohc_desc":ohc["description"],"ohc_teid":hex(ohc.get("teid",0))})
rows.sort(key=lambda r:(r["seid"],r["pdr"]))
print(json.dumps(rows))
