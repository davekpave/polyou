import os, difflib, sys
OLD = r'C:\Users\Dave\polyou_4\.venv\Lib\site-packages\py_clob_client'
NEW = r'C:\Users\Dave\polyou_4\_pcc_diff\unpacked_0346\py_clob_client'
# walk both, show files unique or differing
def all_files(root):
    out={}
    for dp,_,fs in os.walk(root):
        for f in fs:
            if f.endswith('.py'):
                rel=os.path.relpath(os.path.join(dp,f),root).replace('\\','/')
                out[rel]=open(os.path.join(dp,f),encoding='utf-8').read()
    return out
a=all_files(OLD); b=all_files(NEW)
print('Only in 0.31.0:', sorted(set(a)-set(b)))
print('Only in 0.34.6:', sorted(set(b)-set(a)))
print('Differing:')
for k in sorted(set(a)&set(b)):
    if a[k]!=b[k]:
        print('  *', k, '  (old', len(a[k].splitlines()),'new', len(b[k].splitlines()),')')

import re
# search for version/order_version in BOTH
for label,root in [('0.31.0',OLD),('0.34.6',NEW)]:
    print('\n--- search', label,'for order_version/OrderVersion/protocol_version ---')
    for dp,_,fs in os.walk(root):
        for f in fs:
            if not f.endswith('.py'): continue
            p=os.path.join(dp,f)
            for i,line in enumerate(open(p,encoding='utf-8'),1):
                if re.search(r'order_version|OrderVersion|protocol_version', line):
                    print(f'  {os.path.relpath(p,root)}:{i}: {line.rstrip()}')
