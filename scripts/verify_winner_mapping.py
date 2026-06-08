"""Verify gamma outcomePrices vs clobTokenIds ordering against known truth."""
import csv, json, urllib.request

# Take a few cached markets and compare gamma's winner inference to _meta truth
truth = {}
for r in csv.DictReader(open("cache/trades/_meta.csv")):
    try:
        toks = json.loads(r["tokens"]) if r["tokens"].startswith("[") else r["tokens"].split("|")
    except Exception:
        toks = r["tokens"].split("|")
    truth[r["slug"]] = {"tokens": toks, "winner": r.get("winner_token")}

print(f"Cached markets: {len(truth)}")
print("Sample truth:")
for s, v in list(truth.items())[:3]:
    print(f"  {s}: tokens={v['tokens'][:1]}... winner={v['winner']}")

# Now query gamma for these slugs and compare
print("\nGamma comparison:")
checked = 0
agree_index0 = 0  # gamma's outcomePrices[0]>outcomePrices[1] => winner=tokens[0]
agree_index1 = 0  # opposite mapping
for slug, t in truth.items():
    if checked >= 15: break
    if not t["winner"]: continue
    try:
        req = urllib.request.Request(f"https://gamma-api.polymarket.com/events/slug/{slug}",
                                      headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        m = d["markets"][0]
        toks_raw = m.get("clobTokenIds")
        if isinstance(toks_raw, str): gamma_toks = json.loads(toks_raw)
        else: gamma_toks = toks_raw
        op = m.get("outcomePrices")
        if isinstance(op, str): op = json.loads(op)
        outcomes = m.get("outcomes")
        if isinstance(outcomes, str): outcomes = json.loads(outcomes)
        yes_p, no_p = float(op[0]), float(op[1])
        gamma_winner_idx0 = gamma_toks[0] if yes_p > no_p else gamma_toks[1]
        true_winner = t["winner"]
        match0 = gamma_winner_idx0 == true_winner
        if match0: agree_index0 += 1
        else: agree_index1 += 1
        print(f"  {slug}: outcomes={outcomes} op=[{yes_p},{no_p}] gamma_winner={'tok0' if yes_p>no_p else 'tok1'} match={match0}")
        checked += 1
    except Exception as e:
        print(f"  {slug}: ERR {e}")

print(f"\nAgree with mapping (op>0=>tok0): {agree_index0}/{checked}")
print(f"Disagree (would need op>0=>tok1): {agree_index1}/{checked}")
