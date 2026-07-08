import os
import json
import requests
import yfinance as yf

# Strategy Configuration
SYMBOL = "SPY"
GATEWAY_URL = "https://agent.robinhood.com/mcp/trading"


# --- STEP 1: SECURELY EXTRACT ENVIRONMENT STRINGS ---
ACCOUNT_NUMBER = os.getenv("ROBINHOOD_ACCOUNT_NUMBER")
ACCESS_TOKEN = os.getenv("ROBINHOOD_ACCESS_TOKEN")
REFRESH_TOKEN = os.getenv("ROBINHOOD_REFRESH_TOKEN")

if not ACCOUNT_NUMBER:
    print("Security Exception: ROBINHOOD_ACCOUNT_NUMBER environment variable is missing.")
    exit(1)


# --- STEP 2: DEFINE OAUTH TOKEN ROTATION BACKUP ---
def refresh_access_token():
    if not REFRESH_TOKEN:
        print("Rotation Error: Cannot refresh token. ROBINHOOD_REFRESH_TOKEN is not set.")
        return None

    print("Attempting automatic session rotation via Robinhood Auth Authority...")
    
    # Robinhood API OAuth2 Token endpoint
    oauth_url = "https://api.robinhood.com/oauth2/token/"
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": "c825b4ab-1407-4e6e-8214-e4f691234567" # Fallback public standard client ID if needed
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    try:
        response = requests.post(oauth_url, data=payload, headers=headers)
        if response.status_code == 200:
            token_metadata = response.json()
            new_token = token_metadata.get("access_token")
            print("Rotation Success! New active bearer token issued.")
            return new_token
        else:
            print(f"OAuth Server rejected refresh: Status {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Failed to communicate with token authority: {e}")
        return None


# --- STEP 3: FETCH MARKET DATA VIA YFINANCE ---
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


# --- STEP 4: CHECK ROBINHOOD HOLDINGS WITH EXPIRED CAPTURE ---
if not ACCESS_TOKEN:
    ACCESS_TOKEN = refresh_access_token()
    if not ACCESS_TOKEN:
        print("Fatal exception: Missing valid authorization to poll broker endpoints.")
        exit(1)

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

positions_payload = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
        "name": "get_equity_positions",
        "arguments": {"account_number": ACCOUNT_NUMBER}
    },
    "id": 1
}

print("\nChecking live portfolio positions...")
pos_response = requests.post(GATEWAY_URL, json=positions_payload, headers=headers)

# If our access token expired mid-transit, catch it and refresh immediately
if pos_response.status_code == 401:
    print("Warning: Access token expired or rejected (401). Retrying with token rotation...")
    ACCESS_TOKEN = refresh_access_token()
    if ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"
        pos_response = requests.post(GATEWAY_URL, json=positions_payload, headers=headers)

if pos_response.status_code != 200:
    print(f"API Error fetching positions: Status {pos_response.status_code}")
    exit(1)

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
    # State: POSITION OPEN -> Track profit target
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
                    "account_number": ACCOUNT_NUMBER,
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
    # State: FLAT CASH -> Track market entry drawdown
    print(f"\n>>> STATE: FLAT CASH")
    DRAWDOWN_TRESHOLD = 2.0
    if drawdown >= DRAWDOWN_TRESHOLD:
        print("🔥 DRAWDOWN TRIGGERED! Ordering fractional entry...")
        order_payload = {
            "name": "place_equity_order",
            "arguments": {
                "account_number": ACCOUNT_NUMBER,
                "symbol": SYMBOL,
                "side": "buy",
                "type": "market",
                "time_in_force": "gtd",
                "dollar_amount": "1.00"
            }
        }
    else:
        print(f"No buy signal triggered. S&P 500 premium remains outside the {DRAWDOWN_TRESHOLD}% threshold.")


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