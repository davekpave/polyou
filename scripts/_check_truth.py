import json, csv
slug = 'btc-updown-15m-1777973400'
trades = json.load(open(f'cache/trades/{slug}.json'))
for r in csv.DictReader(open('cache/trades/_meta.csv')):
    if r['slug'] == slug:
        toks = r['tokens'].split(',')
        cache_winner = r['winner_token']
        break
ws = int(slug.rsplit('-', 1)[1]); we = ws + 900
gw_map = {r['slug']: r['gamma_winner'] for r in csv.DictReader(open('cache/trades/_meta_gamma_winners.csv'))}
gamma_winner = gw_map[slug]
print('Tokens:', toks)
which = lambda x: 'tok0' if x == toks[0] else 'tok1'
print(f'Cache winner: {cache_winner[:20]}... ({which(cache_winner)})')
print(f'Gamma winner: {gamma_winner[:20]}... ({which(gamma_winner)})')
print()
for tok in toks:
    last = sorted([t for t in trades if str(t['asset']) == tok and we-120 <= int(t['timestamp']) <= we+30],
                  key=lambda x: int(x['timestamp']))
    print(f'Token {tok[:20]}... ({which(tok)}) last ~2min trades:')
    for t in last[-8:]:
        rel = int(t['timestamp']) - ws
        print(f'  ts={rel:+5d}s side={t["side"]} px={t["price"]} sz={t["size"]}')
    print()
