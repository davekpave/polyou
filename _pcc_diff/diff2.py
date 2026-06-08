import difflib, os, sys
OLD = r'C:\Users\Dave\polyou_4\.venv\Lib\site-packages\py_clob_client'
NEW = r'C:\Users\Dave\polyou_4\_pcc_diff\unpacked_0346\py_clob_client'
for rel in ['http_helpers/helpers.py','utilities.py','endpoints.py']:
    a=open(os.path.join(OLD,rel),encoding='utf-8').read().splitlines(keepends=True)
    b=open(os.path.join(NEW,rel),encoding='utf-8').read().splitlines(keepends=True)
    print(f'\n===== {rel} =====')
    sys.stdout.writelines(list(difflib.unified_diff(a,b,fromfile='0.31.0/'+rel,tofile='0.34.6/'+rel,n=2))[:200])
