import ipaddress, json, os, pathlib, urllib.parse
out=pathlib.Path('work/ceres-v3/03/timeout-diagnosis').resolve()
proxy_names=('HTTP_PROXY','http_proxy','HTTPS_PROXY','https_proxy','ALL_PROXY','all_proxy')
proxy_summary={}
for name in proxy_names:
    value=os.environ.get(name)
    if not value:
        proxy_summary[name]={'set':False}
        continue
    parsed=urllib.parse.urlsplit(value if '://' in value else 'http://'+value)
    proxy_summary[name]={'set':True,'scheme':parsed.scheme,'host':parsed.hostname,'port':parsed.port,'credentials_present':parsed.username is not None or parsed.password is not None}
no_proxy=','.join(os.environ.get(n,'') for n in ('NO_PROXY','no_proxy')).split(',')
entries=[p.strip().lower() for p in no_proxy if p.strip()]
def bypasses_loopback():
    for p in entries:
        if p=='*' or p in ('localhost','127.0.0.1','::1'):
            return True
        try:
            if ipaddress.ip_address('127.0.0.1') in ipaddress.ip_network(p,strict=False):
                return True
        except ValueError:
            pass
    return False
record={'event':'proxy_environment_redacted_inspection','proxy_variables':proxy_summary,'no_proxy_set':bool(entries),'no_proxy_entry_count':len(entries),'bypasses_127_0_0_1':bypasses_loopback(),'raw_proxy_values_recorded':False}
(out/'proxy-environment.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps(record,indent=2))
