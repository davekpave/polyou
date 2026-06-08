import difflib, os, sys, re
OLD = r'C:\Users\Dave\polyou_4\.venv\Lib\site-packages\py_clob_client'
NEW = r'C:\Users\Dave\polyou_4\_pcc_diff\unpacked_0346\py_clob_client'

def read(p):
    try:
        with open(p,'r',encoding='utf-8') as f: return f.read().splitlines(keepends=True)
    except FileNotFoundError:
        return []

files = [
    'client.py','clob_types.py','order_builder/builder.py',
    'order_builder/constants.py','signer.py','signing/eip712.py',
]
for rel in files:
    a = read(os.path.join(OLD, rel))
    b = read(os.path.join(NEW, rel))
    print(f'\n===== DIFF {rel}  (old_lines={len(a)} new_lines={len(b)}) =====')
    diff = list(difflib.unified_diff(a, b, fromfile='0.31.0/'+rel, tofile='0.34.6/'+rel, n=2))
    if not diff:
        print('(no diff or missing)')
    else:
        sys.stdout.writelines(diff[:300])
