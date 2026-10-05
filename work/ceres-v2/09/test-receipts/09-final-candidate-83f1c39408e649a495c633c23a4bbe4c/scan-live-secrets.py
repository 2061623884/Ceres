import json,re,sys
from pathlib import Path
run=Path(sys.argv[1]); envfile=run/'cold-1'/'.env'
values={}
for line in envfile.read_text(encoding='utf-8-sig').splitlines():
 m=re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$',line)
 if m:
  v=m.group(2).strip()
  if len(v)>=2 and v[0]==v[-1] and v[0] in "\"'":v=v[1:-1]
  if m.group(1).endswith('_KEY') or m.group(1).endswith('_TOKEN') or m.group(1).endswith('_SECRET'):
   values[m.group(1)]=v
files=[run/'live-memory-effective.stdout.raw.txt',run/'live-memory-effective.stderr.raw.txt',run/'live-journey.stdout.raw.txt',run/'live-journey.stderr.raw.txt']
results=[]
for p in files:
 b=p.read_bytes() if p.exists() else b''
 text=b.decode('utf-8',errors='replace')
 key_matches=[k for k,v in values.items() if v and len(v)>=6 and v.encode('utf-8') in b]
 results.append({'file':str(p),'exists':p.exists(),'bytes':len(b),'credentialFieldNamesMatched':key_matches,'bearerTokenPatternPresent':bool(re.search(r'(?i)Bearer\s+[A-Za-z0-9._~+/=-]{8,}',text)),'authorizationHeaderPresent':bool(re.search(r'(?i)authorization\s*[:=]',text))})
out={'credentialFieldNamesScanned':sorted(values.keys()),'results':results,'anyKeyMaterialMatch':any(r['credentialFieldNamesMatched'] for r in results)}
(run/'live-secret-scan.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))
