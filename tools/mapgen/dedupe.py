#!/usr/bin/env python3
"""Removes from a road set the pieces audit.py flags as duplicate or spike (a duplicate can be the only bridge between two groups: run
connect.py unir/ligar/limpar/grupos AFTER this).  python dedupe.py in.json out.json  (in.json: {"vias":[{"c","p","w","n","z"}]}, p = x,y,x,y...)"""
import json
import sys

import audit as A

d=json.load(open(sys.argv[1],encoding='utf-8'))
f,pcs,n,nl,size=A.audit(d)
idx=[i for i,v in enumerate(d['vias']) if v['c'] in A.ROAD]
drop=set()
for kind in ('duplicate','spike'):
    for k,_ in f[kind]: drop.add(idx[k])
print('dropping',len(drop))
d['vias']=[v for i,v in enumerate(d['vias']) if i not in drop]
json.dump(d,open(sys.argv[2],'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
