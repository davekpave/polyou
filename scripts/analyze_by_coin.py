#!/usr/bin/env python3
"""Analyze bot performance by cryptocurrency symbol."""

import csv
from collections import defaultdict

SHADOW_EXITS_CSV = "logs/shadow_exits.csv"

def main():
    trades_by_symbol = defaultdict(list)  # symbol -> list of pnl values
    
    with open(SHADOW_EXITS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row.get("symbol", "")
            if not symbol:
                continue
            
            try:
                pnl = float(row.get("true_pnl", "0") or "0")
                trades_by_symbol[symbol].append(pnl)
            except (ValueError, TypeError):
                continue
    
    print("=" * 80)
    print("  CRYPTOCURRENCY PERFORMANCE ANALYSIS")
    print("=" * 80)
    print()
    
    # Sort by total P&L descending
    symbols_sorted = sorted(trades_by_symbol.items(), 
                           key=lambda x: sum(x[1]), 
                           reverse=True)
    
    print(f"{'Symbol':<10} {'Trades':<8} {'Total P&L':<12} {'Avg/Trade':<12} {'Win Rate':<10} {'Best Trade':<12} {'Worst Trade'}")
    print("-" * 80)
    
    total_all_trades = 0
    total_all_pnl = 0.0
    
    for symbol, trades in symbols_sorted:
        total_pnl = sum(trades)
        avg_per_trade = total_pnl / len(trades) if trades else 0
        wins = sum(1 for pnl in trades if pnl > 0)
        win_rate = (wins / len(trades) * 100) if trades else 0
        best_trade = max(trades) if trades else 0
        worst_trade = min(trades) if trades else 0
        
        print(f"{symbol:<10} {len(trades):<8} ${total_pnl:>9.2f}    ${avg_per_trade:>8.4f}    {win_rate:>5.1f}%     ${best_trade:>8.2f}     ${worst_trade:>8.2f}")
        
        total_all_trades += len(trades)
        total_all_pnl += total_pnl
    
    print("-" * 80)
    print(f"{'TOTAL':<10} {total_all_trades:<8} ${total_all_pnl:>9.2f}    ${total_all_pnl/total_all_trades:>8.4f}    {'-':<5}     {'-':<12} {'-'}")
    print()
    
    print("=" * 80)
    print("  KEY INSIGHTS")
    print("=" * 80)
    print()
    
    if symbols_sorted:
        best_symbol, best_trades = symbols_sorted[0]
        best_pnl = sum(best_trades)
        best_avg = best_pnl / len(best_trades)
        
        worst_symbol, worst_trades = symbols_sorted[-1]
        worst_pnl = sum(worst_trades)
        worst_avg = worst_pnl / len(worst_trades)
        
        print(f"Best Performer: {best_symbol}")
        print(f"  Total P&L:     ${best_pnl:.2f}")
        print(f"  Avg per Trade: ${best_avg:.4f}")
        print(f"  Trades:        {len(best_trades)}")
        print()
        
        print(f"Worst Performer: {worst_symbol}")
        print(f"  Total P&L:     ${worst_pnl:.2f}")
        print(f"  Avg per Trade: ${worst_avg:.4f}")
        print(f"  Trades:        {len(worst_trades)}")
        print()
        
        # Find most profitable per trade
        best_per_trade_symbol = max(symbols_sorted, 
                                    key=lambda x: sum(x[1])/len(x[1]) if x[1] else 0)
        symbol_name, symbol_trades = best_per_trade_symbol
        avg_pnl = sum(symbol_trades) / len(symbol_trades)
        
        if symbol_name != best_symbol:
            print(f"Best $/Trade: {symbol_name} (${avg_pnl:.4f} per trade)")
            print()
    
    print("=" * 80)

if __name__ == "__main__":
    main()
