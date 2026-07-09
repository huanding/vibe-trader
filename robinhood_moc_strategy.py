import os
import json
import requests
import yfinance as yf
from robinhood_auth import RobinhoodAuth # <-- Import the new manager class

# Strategy Configuration
SYMBOL = "SPY"
GATEWAY_URL = "https://agent.robinhood.com/mcp/trading"

# --- STEP 1: INITIALIZE AUTH MANAGEMENT ---
try:
    auth = RobinhoodAuth()
except RuntimeError as e:
    print(e)
    exit(1)

# --- STEP 2: FETCH MARKET DATA VIA YFINANCE ---
print(f"Fetching market data for {SYMBOL}...")
ticker = yf.Ticker(SYMBOL)
info = ticker.info

current_price = info.get("currentPrice") or info.get("regularMarketPrice")
high_52week = info.get("fiftyTwoWeekHigh")

if not current_price or not high_52week:
    print("Error: Could not retrieve pricing data from yfinance.")
    exit(1)

drawdown = ((high_52week - current_price) / high_52week) * 100
print(f"{SYMBOL} Current Price: ${current_price:.2f}")
print(f"{SYMBOL} 52-Week High: ${high_52week:.2f}")
print(f"Current Drawdown: {drawdown:.2f}%")

# --- STEP 3: CHECK ROBINHOOD HOLDINGS WITH EXPIRED CAPTURE ---
positions_payload = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
        "name": "get_equity_positions",
        "arguments": {"account_number": auth.account_number}
    },
    "id": 1
}

print("\nChecking live portfolio positions...")
try:
    headers = auth.get_headers()
    pos_response = requests.post(GATEWAY_URL, json=positions_payload, headers=headers)
except RuntimeError as e:
    print(e)
    exit(1)

# Mid-transit expiry mitigation loop
if pos_response.status_code == 401:
    print("Warning: Access token expired or rejected (401). Retrying with token rotation...")
    if auth.refresh_access_token():
        headers = auth.get_headers()
        pos_response = requests.post(GATEWAY_URL, json=positions_payload, headers=headers)

if pos_response.status_code != 200:
    print(f"API Error fetching positions: Status {pos_response.status_code}")
    exit(1)

# --- STEP 4: DATA PARSING ---
try:
    raw_text = pos_response.text
    if raw_text.startswith("event:"):
        data_line = [line for line in raw_text.splitlines() if line.startswith("data:")][0]
        inner_json = json.loads(data_line.replace("data: ", ""))
    else:
        inner_json = json.loads(raw_text)

    content_str = inner_json["result"]["content"][0]["text"]
    portfolio_data = json.loads(content_str)
    positions = portfolio_data.get("data", {}).get("positions", [])
except Exception as e:
    print(f"Data Parser Warning: Assuming empty portfolio positions list. Detail: {e}")
    positions = []

# --- STEP 5: EVALUATE STRATEGY LOGIC STATE MACHINE ---
active_position = next((p for p in positions if p.get("symbol") == SYMBOL), None)
order_payload = None

if active_position:
    avg_buy_price = float(active_position["average_buy_price"])
    shares_available = float(active_position.get("shares_available_for_sells", 0))
    current_profit_pct = ((current_price - avg_buy_price) / avg_buy_price) * 100
    
    print(f"\n>>> STATE: HOLDING POSITION")
    print(f"Cost Basis: ${avg_buy_price:.2f} | Current Gain: {current_profit_pct:.2f}%")
    
    if current_profit_pct >= 10.0:
        print("🎯 TARGET HIT! Preparing to take 10% profit.")
        if shares_available > 0:
            order_payload = {
                "name": "place_equity_order",
                "arguments": {
                    "account_number": auth.account_number,
                    "symbol": SYMBOL,
                    "side": "sell",
                    "type": "market",
                    "time_in_force": "gtd",
                    "quantity": str(shares_available)
                }
            }
        else:
            print("Error: Profit target hit but shares are unconfirmed or pending settlement.")
    else:
        print("Holding position. Waiting for asset appreciation to reach +10.00%.")

else:
    print(f"\n>>> STATE: FLAT CASH")
    DRAWDOWN_THRESHOLD = 2.0
    if drawdown >= DRAWDOWN_THRESHOLD:
        print("🔥 DRAWDOWN TRIGGERED! Ordering fractional entry...")
        order_payload = {
            "name": "place_equity_order",
            "arguments": {
                "account_number": auth.account_number,
                "symbol": SYMBOL,
                "side": "buy",
                "type": "market",
                "time_in_force": "gtd",
                "dollar_amount": "1.00"
            }
        }
    else:
        print(f"No buy signal triggered. S&P 500 premium remains outside the {DRAWDOWN_THRESHOLD}% threshold.")

# --- STEP 6: EXECUTE ROUTED TRADING ORDER ---
if order_payload:
    trade_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": order_payload,
        "id": 2
    }
    
    print(f"\nSubmitting trade execution request via tool: {order_payload['name']}...")
    trade_response = requests.post(GATEWAY_URL, json=trade_payload, headers=headers)
    
    print(f"Gateway HTTP Status Code: {trade_response.status_code}")
    if trade_response.text:
        print("--- Order Gateway Stream Output ---")
        print(trade_response.text)