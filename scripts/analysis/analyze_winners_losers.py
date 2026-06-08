"""Analyze what separates winning trades from losing trades."""
import csv
from collections import defaultdict
from datetime import datetime

def parse_execution_log():
    """Parse execution_log.csv to get entry details."""
    trades = []
    with open('logs/execution_log.csv', 'r') as f:
        reader = csv.reader(f)
        next(reader, None)  # Skip header
        for row in reader:
            if len(row) < 10:
                continue
            try:
                timestamp = float(row[0])
                symbol = row[1]
                side = row[2]
                entry_price = float(row[4])  # snapshot_price
                quality = float(row[9])  # signal_quality from **phase
                
                trades.append({
                    'timestamp': timestamp,
                    'symbol': symbol,
                    'side': side,
                    'entry_price': entry_price,
                    'quality': quality,
                })
            except (ValueError, IndexError) as e:
                continue
    return trades

def parse_exit_log():
    """Parse exit_log.csv to get exit outcomes."""
    exits = []
    with open('logs/exit_log.csv', 'r') as f:
        reader = csv.reader(f)
        next(reader, None)  # Skip header
        for row in reader:
            if len(row) < 6:
                continue
            try:
                timestamp = float(row[0])
                reason = row[2]
                entry_price = float(row[3])
                exit_price = float(row[4])
                pnl = float(row[5])
                
                exits.append({
                    'timestamp': timestamp,
                    'reason': reason,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'won': pnl > 0
                })
            except (ValueError, IndexError) as e:
                continue
    return exits

def match_trades(entries, exits):
    """Match exits to entries by entry price and timestamp."""
    winners = []
    losers = []
    unmatched_exits = 0
    
    for exit_data in exits:
        # Find entry with matching entry_price within a 15-minute window
        best_match = None
        best_diff = float('inf')
        
        for entry_data in entries:
            # Check if entry price matches (within 1 cent)
            price_diff = abs(entry_data['entry_price'] - exit_data['entry_price'])
            if price_diff > 0.01:
                continue
            
            # Check if exit is after entry (within reasonable window)
            time_diff = exit_data['timestamp'] - entry_data['timestamp']
            if time_diff < 0 or time_diff > 1200:  # Must be 0-20 minutes
                continue
            
            # Best match is closest in time
            if time_diff < best_diff:
                best_diff = time_diff
                best_match = entry_data
        
        if best_match:
            combined = {**best_match, **exit_data}
            if exit_data['won']:
                winners.append(combined)
            else:
                losers.append(combined)
        else:
            unmatched_exits += 1
    
    return winners, losers, unmatched_exits

def analyze():
    """Main analysis function."""
    entries = parse_execution_log()
    exits = parse_exit_log()
    
    # Match entries to exits
    winners, losers, unmatched = match_trades(entries, exits)
    
    print(f"\n{'='*60}")
    print(f"TRADE ANALYSIS: Winners vs Losers")
    print(f"{'='*60}\n")
    
    total_entries = len(entries)
    total_exits = len(exits)
    total_matched = len(winners) + len(losers)
    
    print(f"Total entries: {total_entries}")
    print(f"Total exits: {total_exits}")
    print(f"Matched trades: {total_matched} ({total_matched/total_exits*100:.1f}% of exits)")
    print(f"Unmatched exits: {unmatched}")
    
    if total_matched == 0:
        print("\n❌ No trades matched! Cannot perform analysis.")
        return
    
    print(f"\n  Winners: {len(winners)} ({len(winners)/total_matched*100:.1f}%)")
    print(f"  Losers: {len(losers)} ({len(losers)/total_matched*100:.1f}%)")
    
    # Quality score analysis
    print(f"\n{'='*60}")
    print("QUALITY SCORE ANALYSIS")
    print(f"{'='*60}")
    
    winner_qualities = [t['quality'] for t in winners]
    loser_qualities = [t['quality'] for t in losers]
    
    print(f"\nWinners:")
    print(f"  Average quality: {sum(winner_qualities)/len(winner_qualities):.0f}")
    print(f"  Median quality: {sorted(winner_qualities)[len(winner_qualities)//2]:.0f}")
    print(f"  Min: {min(winner_qualities):.0f}, Max: {max(winner_qualities):.0f}")
    
    print(f"\nLosers:")
    print(f"  Average quality: {sum(loser_qualities)/len(loser_qualities):.0f}")
    print(f"  Median quality: {sorted(loser_qualities)[len(loser_qualities)//2]:.0f}")
    print(f"  Min: {min(loser_qualities):.0f}, Max: {max(loser_qualities):.0f}")
    
    # Quality brackets
    print(f"\nWin rate by quality bracket:")
    brackets = [
        (0, 500, "Ultra Low (<500)"),
        (500, 1000, "Low (500-1000)"),
        (1000, 2500, "Medium (1000-2500)"),
        (2500, 5000, "High (2500-5000)"),
        (5000, 100000, "Very High (>5000)")
    ]
    
    for min_q, max_q, label in brackets:
        w = len([t for t in winners if min_q <= t['quality'] < max_q])
        l = len([t for t in losers if min_q <= t['quality'] < max_q])
        total = w + l
        if total > 0:
            wr = w / total * 100
            print(f"  {label:25s}: {w}W-{l}L ({wr:.1f}%) [n={total}]")
    
    # Symbol analysis
    print(f"\n{'='*60}")
    print("SYMBOL ANALYSIS")
    print(f"{'='*60}")
    
    symbols = ['BTCUSD', 'ETHUSD', 'SOLUSD', 'XRPUSD']
    for symbol in symbols:
        w = len([t for t in winners if t['symbol'] == symbol])
        l = len([t for t in losers if t['symbol'] == symbol])
        total = w + l
        if total > 0:
            wr = w / total * 100
            avg_q_w = sum([t['quality'] for t in winners if t['symbol'] == symbol]) / w if w > 0 else 0
            avg_q_l = sum([t['quality'] for t in losers if t['symbol'] == symbol]) / l if l > 0 else 0
            print(f"\n{symbol}:")
            print(f"  {w}W-{l}L ({wr:.1f}%) [n={total}]")
            print(f"  Avg quality - Winners: {avg_q_w:.0f}, Losers: {avg_q_l:.0f}")
    
    # Side analysis (UP vs DOWN)
    print(f"\n{'='*60}")
    print("SIDE ANALYSIS (UP vs DOWN)")
    print(f"{'='*60}")
    
    for side in ['UP', 'DOWN']:
        w = len([t for t in winners if t['side'] == side])
        l = len([t for t in losers if t['side'] == side])
        total = w + l
        if total > 0:
            wr = w / total * 100
            avg_q_w = sum([t['quality'] for t in winners if t['side'] == side]) / w if w > 0 else 0
            avg_q_l = sum([t['quality'] for t in losers if t['side'] == side]) / l if l > 0 else 0
            print(f"\n{side}:")
            print(f"  {w}W-{l}L ({wr:.1f}%) [n={total}]")
            print(f"  Avg quality - Winners: {avg_q_w:.0f}, Losers: {avg_q_l:.0f}")
    
    # Entry price analysis
    print(f"\n{'='*60}")
    print("ENTRY PRICE ANALYSIS")
    print(f"{'='*60}")
    
    winner_prices = [t['entry_price'] for t in winners]
    loser_prices = [t['entry_price'] for t in losers]
    
    print(f"\nWinners:")
    print(f"  Average entry: ${sum(winner_prices)/len(winner_prices):.3f}")
    print(f"  Median entry: ${sorted(winner_prices)[len(winner_prices)//2]:.3f}")
    
    print(f"\nLosers:")
    print(f"  Average entry: ${sum(loser_prices)/len(loser_prices):.3f}")
    print(f"  Median entry: ${sorted(loser_prices)[len(loser_prices)//2]:.3f}")
    
    # Price brackets
    print(f"\nWin rate by entry price:")
    price_brackets = [
        (0, 0.20, "Very Low (<$0.20)"),
        (0.20, 0.35, "Low ($0.20-$0.35)"),
        (0.35, 0.50, "Mid ($0.35-$0.50)"),
        (0.50, 0.65, "High ($0.50-$0.65)"),
        (0.65, 1.0, "Very High (>$0.65)")
    ]
    
    for min_p, max_p, label in price_brackets:
        w = len([t for t in winners if min_p <= t['entry_price'] < max_p])
        l = len([t for t in losers if min_p <= t['entry_price'] < max_p])
        total = w + l
        if total > 0:
            wr = w / total * 100
            print(f"  {label:25s}: {w}W-{l}L ({wr:.1f}%) [n={total}]")
    
    # P&L distribution
    print(f"\n{'='*60}")
    print("P&L DISTRIBUTION")
    print(f"{'='*60}")
    
    winner_pnls = [t['pnl'] for t in winners]
    loser_pnls = [t['pnl'] for t in losers]
    
    print(f"\nWinners:")
    print(f"  Average P&L: ${sum(winner_pnls)/len(winner_pnls):.2f}")
    print(f"  Total: ${sum(winner_pnls):.2f}")
    
    print(f"\nLosers:")
    print(f"  Average P&L: ${sum(loser_pnls)/len(loser_pnls):.2f}")
    print(f"  Total: ${sum(loser_pnls):.2f}")
    
    print(f"\nNet P&L: ${sum(winner_pnls) + sum(loser_pnls):.2f}")
    
    # Key findings
    print(f"\n{'='*60}")
    print("KEY FINDINGS")
    print(f"{'='*60}\n")
    
    avg_q_winners = sum(winner_qualities) / len(winner_qualities)
    avg_q_losers = sum(loser_qualities) / len(loser_qualities)
    
    if avg_q_winners > avg_q_losers * 1.1:
        print(f"✓ Winners have {((avg_q_winners/avg_q_losers - 1) * 100):.0f}% higher quality scores")
    elif avg_q_losers > avg_q_winners * 1.1:
        print(f"✗ Losers have {((avg_q_losers/avg_q_winners - 1) * 100):.0f}% higher quality scores (PROBLEM!)")
    else:
        print(f"- Quality scores are similar between winners/losers (no strong edge)")
    
    # Find best performing bracket
    best_bracket = None
    best_wr = 0
    for min_q, max_q, label in brackets:
        w = len([t for t in winners if min_q <= t['quality'] < max_q])
        l = len([t for t in losers if min_q <= t['quality'] < max_q])
        total = w + l
        if total >= 10:  # Only consider brackets with 10+ trades
            wr = w / total * 100
            if wr > best_wr:
                best_wr = wr
                best_bracket = (label, w, l, wr)
    
    if best_bracket:
        print(f"✓ Best quality bracket: {best_bracket[0]} with {best_bracket[3]:.1f}% win rate")

if __name__ == "__main__":
    analyze()
