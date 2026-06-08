import re
for label,p in [('0.31.0',r'C:\Users\Dave\polyou_4\.venv\Lib\site-packages\py_clob_client\clob_types.py'),
                ('0.34.6',r'C:\Users\Dave\polyou_4\_pcc_diff\unpacked_0346\py_clob_client\clob_types.py')]:
    src=open(p,encoding='utf-8').read()
    print(f'\n--- {label} OrderArgs / OrderType / BalanceAllowanceParams / RoundConfig / AssetType ---')
    for m in re.finditer(r'class (OrderArgs|OrderType|BalanceAllowanceParams|RoundConfig|AssetType)\b.*?(?=\nclass |\Z)', src, re.S):
        print(m.group(0).rstrip()[:600])
        print('---')
# create_order signatures
import re
for label,p in [('0.31.0',r'C:\Users\Dave\polyou_4\.venv\Lib\site-packages\py_clob_client\client.py'),
                ('0.34.6',r'C:\Users\Dave\polyou_4\_pcc_diff\unpacked_0346\py_clob_client\client.py')]:
    src=open(p,encoding='utf-8').read()
    print(f'\n=== {label} create_order/post_order/create_and_post_order/create_or_derive ===')
    for m in re.finditer(r'def (create_order|post_order|create_and_post_order|create_or_derive_api_creds|set_api_creds|__init__)\([^)]*\):', src):
        print(' ', m.group(0))
