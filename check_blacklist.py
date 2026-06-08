#!/usr/bin/env python3
"""Check performance of blacklisted leaders"""

import csv
from collections import defaultdict

# Load trades
leaders = defaultdict(lambda: {'trades': 0, 'pnl': 0.0})
with open('logs/shadow_exits.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        addr = row['leader_address']
        pnl_str = row.get('true_pnl', '').strip().replace('+', '')
        pnl = float(pnl_str) if pnl_str else 0.0
        leaders[addr]['trades'] += 1
        leaders[addr]['pnl'] += pnl

# Check blacklisted leaders
blacklist = [
    '0xb4b5c838eee748bc8873d7065235d2802bb6479a',
    '0xac6df77395095fd6a6f16e836ad845dd8cb0919a'
]

print('=' * 70)
print('  BLACKLISTED LEADERS - ACTUAL PERFORMANCE')
print('=' * 70)
print()

total_avoided_loss = 0.0
for addr in blacklist:
    short_addr = addr[:10]
    if addr in leaders:
        stats = leaders[addr]
        print(f'{short_addr}... : {stats["trades"]} trades, ${stats["pnl"]:.2f} P&L')
        total_avoided_loss += stats['pnl']
    else:
        print(f'{short_addr}... : NOT FOUND (never traded)')

print()
print(f'Total P&L avoided by blacklisting: ${total_avoided_loss:.2f}')
print()

if total_avoided_loss < 0:
    print(f'✅ CORRECT DECISION: Blacklisting saved ${abs(total_avoided_loss):.2f}')
elif total_avoided_loss > 0:
    print(f'❌ MISSED OPPORTUNITY: Blacklisting cost ${total_avoided_loss:.2f}')
else:
    print('⚪ NEUTRAL: No impact from blacklisting')

print('=' * 70)
