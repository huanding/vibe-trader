import sys
import pandas as pd
import pandas_market_calendars as mcal
from robinhood_auth import RobinhoodAuth
from ticker_analyzer import TickerAnalyzer
from robinhood_trader import RobinhoodTrader

SYMBOL = "QQQ"

def is_market_open() -> bool:
    """
    Dynamically checks if the NYSE regular trading session is open right now.
    Prints status and schedule in Pacific Time.
    """
    nyse = mcal.get_calendar("NYSE")
    now_utc = pd.Timestamp.now(tz="UTC")
    
    # Get today's schedule bounds
    today_str = now_utc.tz_convert("America/Los_Angeles").strftime("%Y-%m-%d")
    schedule = nyse.schedule(start_date=today_str, end_date=today_str)
    
    # 1. Holiday or Weekend Check
    if schedule.empty:
        print(f"⏰ Market Closed: {today_str} is a weekend or official exchange holiday.")
        return False
        
    # 2. Check if current UTC timestamp falls within today's market_open & market_close
    market_open = schedule.iloc[0]["market_open"]
    market_close = schedule.iloc[0]["market_close"]
    
    if not (market_open <= now_utc <= market_close):
        open_pt = market_open.tz_convert("America/Los_Angeles").strftime("%I:%M %p PT")
        close_pt = market_close.tz_convert("America/Los_Angeles").strftime("%I:%M %p PT")
        print(f"⏰ Market Closed: Today's session is {open_pt} - {close_pt}.")
        return False

    return True

def main():
    # Initialize Auth Context Layer
    try:
        auth = RobinhoodAuth()
    except RuntimeError as e:
        print(f"Authentication Setup Failure: {e}")
        sys.exit(1)

    # Initialize Components
    analyzer = TickerAnalyzer(symbol=SYMBOL, drawdown_threshold=5.0, target_gain_threshold=10.0)
    trader = RobinhoodTrader(auth_instance=auth)

    # 1. Update Ingestion Layers
    if not analyzer.update_market_data():
        print("Aborting execution due to bad market analytics metrics extraction.")
        sys.exit(1)

    # 2. Extract Portfolio States
    open_lots = trader.fetch_open_stock_lots(symbol=SYMBOL)
    if open_lots is None:  # Ensure trader returns None on auth error rather than []
        print("❌ Authentication failed when fetching portfolio. Aborting strategy run.")
        sys.exit(1)

    # 3. Check for Active Asset Target Flags
    has_holdings = len(open_lots) > 0
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
            print("No buy signal triggered. Asset premium matches target limits.")

    # 4. Route Order to Execution Layer
    if order_arguments:
        # Dynamic Market Calendar Execution Guard
        if not is_market_open():
            print("🛑 Order signal generated, but execution skipped because the exchange is closed.")
            return

        success = trader.execute_order(order_arguments)
        if success:
            print("✅ Order placed successfully.")
        else:
            print("❌ Order placement failed.")
            sys.exit(1)

if __name__ == "__main__":
    main()