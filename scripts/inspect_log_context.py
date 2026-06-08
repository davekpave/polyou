import sys
with open('logs/bot.log', encoding='utf-8', errors='ignore') as f:
    L = f.readlines()
ft_idx = None
for i in range(len(L)-1, -1, -1):
    if 'FINAL TRADE' in L[i]:
        ft_idx = i; break
print('FINAL TRADE at line', ft_idx)
for j in range(max(0, ft_idx-50), ft_idx+5):
    print(L[j].rstrip())
