def main():
    # Initialize Auth Context Layer
    try:
        auth = RobinhoodAuth()
    except RuntimeError as e:
        print(f"Authentication Setup Failure: {e}")
        sys.exit(1)

    # Initialize Components (6.0% Drawdown Threshold)
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
            print("Preparing Market Sell Order...")
            
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
            print("🔥 DRAWDOWN TRIGGERED (6.0%+)! Ordering market entry...")
            
            # --- BUY ORDER: MARKET ORDER (Dollar-based entry) ---
            order_arguments = {
                "account_number": auth.account_number,
                "symbol": SYMBOL,
                "side": "buy",
                "type": "market",
                "time_in_force": "gfd",
                "dollar_amount": "1.00"
            }
        else:
            print("No buy signal triggered. Current drawdown has not hit the 6.0% threshold.")

    # 4. Route Order to Execution Layer
    if order_arguments:
        # Dynamic Market Calendar Execution Guard
        if not is_market_open():
            print("🛑 Order signal generated, but execution skipped because the market is closed.")
            return

        success = trader.execute_order(order_arguments)
        if success:
            print("✅ Order placed successfully.")
        else:
            print("❌ Order placement failed.")
            sys.exit(1)