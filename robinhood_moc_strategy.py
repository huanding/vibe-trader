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
        now_pt = now_utc.tz_convert("America/Los_Angeles").strftime("%I:%M %p PT")
        print(f"⏰ Market Closed (Current Time: {now_pt}): {today_str} is a weekend or official exchange holiday.")
        return False
        
    # 2. Check if current UTC timestamp falls within today's market_open & market_close
    market_open = schedule.iloc[0]["market_open"]
    market_close = schedule.iloc[0]["market_close"]
    
    if not (market_open <= now_utc <= market_close):
        now_pt = now_utc.tz_convert("America/Los_Angeles").strftime("%I:%M %p PT")
        open_pt = market_open.tz_convert("America/Los_Angeles").strftime("%I:%M %p PT")
        close_pt = market_close.tz_convert("America/Los_Angeles").strftime("%I:%M %p PT")
        
        print(f"⏰ Market Closed (Current Time: {now_pt}): Today's session is {open_pt} - {close_pt}.")
        return False

    return True

def main():
    # Initialize Auth Context Layer
    try:
        auth = RobinhoodAuth()
    except RuntimeError as e:
        print(f"Authentication Setup Failure: {e}")
        sys.exit(1)

    # Initialize Components (Updated drawdown_threshold to 6.0%)
    analyzer = TickerAnalyzer(symbol=SYMBOL, drawdown_threshold=6.0, target_gain_threshold=10.0)
    trader = RobinhoodTrader(auth_instance=auth)

    # 1. Update Ingestion Layers
    if not analyzer.update_market_data():
        print("Aborting execution due to bad market analytics metrics extraction.")
        sys.exit(1)

    # 2. Extract Portfolio States
    open_lots = trader.fetch_open_stock_lots(symbol=SYMBOL)
    if open_lots is None:  # Ensure trader returns None on auth error
        print("❌ Authentication failed when fetching portfolio. Aborting strategy run.")
        sys.exit(1)

    # 3. Check for Active Asset Target Flags
    has_holdings = len(open_lots) > 0
    order_arguments = None

    if has_holdings:
        target_lot_data = analyzer.evaluate_tax_lots(open_lots)
        
        if target_lot_data:
            print(f"\n🎯 TARGET HIT! Chosen Lot Gain: {target_lot_data['gain_pct']:.2f}%")
            print("Executing Sell Order as Market Order...")
            
            # --- SELL ORDER: MARKET ORDER ---
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
            # --- BUY ORDER: LIMIT ORDER (+0.5% BUFFER) ---
            current_price = analyzer.current_price
            limit_price = round(current_price * 1.002, 2)
            
            # Convert $1.00 allocation to share quantity
            target_quantity = round(1.00 / limit_price, 6)

            print("🔥 DRAWDOWN TRIGGERED (6.0%+)! Ordering limit entry...")
            print(f"Setting Limit Buy Price: ${limit_price} (+0.2% above ${current_price}) | Qty: {target_quantity}")
            
            order_arguments = {
                "account_number": auth.account_number,
                "symbol": SYMBOL,
                "side": "buy",
                "type": "limit",
                "limit_price": str(limit_price),
                "time_in_force": "gfd",
                "quantity": str(target_quantity)
            }
        else:
            print(f"No buy signal triggered. Current drawdown has not hit the 6.0% threshold.")

    # 4. Route Order to Execution Layer
    if order_arguments:
        order_type = order_arguments.get("type")
        market_open = is_market_open()

        # Market orders require an open market; Limit orders can be queued for open.
        if not market_open:
            if order_type == "market":
                print("🛑 Market order generated, but execution skipped because the exchange is closed.")
                return
            else:
                print("🌙 Exchange is closed. Submitting Limit Order to be queued for next Market Open...")

        success = trader.execute_order(order_arguments)
        if success:
            print("✅ Order placed successfully.")
        else:
            print("❌ Order placement failed.")
            sys.exit(1)

if __name__ == "__main__":
    main()