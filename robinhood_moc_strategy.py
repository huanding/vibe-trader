import sys
from robinhood_auth import RobinhoodAuth
from ticker_analyzer import TickerAnalyzer
from robinhood_trader import RobinhoodTrader

SYMBOL = "SPY"

def main():
    # Initialize Auth Context Layer
    try:
        auth = RobinhoodAuth()
    except RuntimeError as e:
        print(f"Authentication Setup Failure: {e}")
        sys.exit(1)

    # Initialize Components
    analyzer = TickerAnalyzer(symbol=SYMBOL, drawdown_threshold=2.0, target_gain_threshold=10.0)
    trader = RobinhoodTrader(auth_instance=auth)

    # 1. Update Ingestion Layers
    if not analyzer.update_market_data():
        print("Aborting execution due to bad market analytics metrics extraction.")
        sys.exit(1)

    # 2. Extract Portfolio States
    open_lots = trader.fetch_open_stock_lots(symbol=SYMBOL)
    
    # 3. Check for Active Asset Target Flags
    has_holdings = any(lot.get("symbol") == SYMBOL for lot in open_lots)
    order_arguments = None

    if has_holdings:
        target_lot_data = analyzer.evaluate_tax_lots(open_lots)
        
        if target_lot_data:
            print(f"\n🎯 TARGET HIT! Chosen Lot Gain: {target_lot_data['gain_pct']:.2f}%")
            order_arguments = {
                "account_number": auth.account_number,
                "symbol": SYMBOL,
                "side": "sell",
                "type": "market",
                "time_in_force": "gfd",
                "quantity": str(target_lot_data["quantity"])
            }
        else:
            print("\n>>> STATE: HOLDING. No individual tax lots meet execution thresholds.")
            
    else:
        print(f"\n>>> STATE: FLAT CASH (No holdings in {SYMBOL})")
        if analyzer.should_trigger_buy():
            print("🔥 DRAWDOWN TRIGGERED! Ordering fractional entry...")
            order_arguments = {
                "account_number": auth.account_number,
                "symbol": SYMBOL,
                "side": "buy",
                "type": "market",
                "time_in_force": "gfd",
                "dollar_amount": "1.00"
            }
        else:
            print(f"No buy signal triggered. Asset premium matches target limits.")

    # 4. Route Order to Execution Layer
    if order_arguments:
        trader.execute_order(order_arguments)

if __name__ == "__main__":
    main()