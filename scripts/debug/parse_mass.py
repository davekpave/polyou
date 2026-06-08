import json
with open(r'c:\Users\Dave\AppData\Roaming\Code\User\workspaceStorage\4910a670ac02a895e5d695dc75828b16\GitHub.copilot-chat\chat-session-resources\babc8161-fa4c-4bc0-ba3f-e290485dff2a\call_MHxGOWkwM3FhTllIT2lzQ1dCSVk__vscode-1776151713626\content.txt', 'r') as f:
    text = f.read().replace("'",'"').replace('True', 'true').replace('False','false').replace('None','null')
    # text is a rough python repr, lets evaluate it safely
    import ast
    f.seek(0)
    val = ast.literal_eval(f.read())
    events = val
    for e in events:
        for m in e.get('markets',[]):
            if '93752370469853593428275514344712256378857739183343977594575260876189010991162' in str(m.get('clobTokenIds')):
                print('MATCHED SLUG:', m.get('slug'))
                print('CLOSED:', m.get('closed'))
                print('WINNER:', m.get('outcomePrices'))
                print('OUTCOMES:', m.get('outcomes'))
