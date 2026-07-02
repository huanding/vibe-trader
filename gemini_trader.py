import os
import sys
import json
import numpy as np
import yfinance as yf
import robin_stocks.robinhood as rh
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# 1. Define the rigid decision schema
class StrategyDecision(BaseModel):
    action: str = Field(description="Must be strictly one of: 'BUY', 'SELL', or 'HOLD'")
    confidence_score: float = Field(description="Confidence rating from 0.0 (low) to 1.0 (high)")
    quantity: int = Field(description="Recommended shares to trade based on cash limits and strategy rules. 0 if HOLD.")
    strategy_match: bool = Field(description="True if RSI thresholds (<40 or >60) are definitively triggered.")
    reasoning: str = Field(description="Clear execution justification specifying current RSI status.")

def calculate_rsi(ticker: str, period: int = 14) -> float:
    """Fetches historical daily prices and computes the current rolling RSI."""
    print(f"📈 Downloading historical daily chart arrays for {ticker}...")
    # Fetch 3 months of data to guarantee an accurate rolling 14-day context window
    df = yf.download(ticker, period="3mo", progress=False)
    if df.empty:
        raise ValueError(f"Could not retrieve historical data for {ticker}")
        
    # Extract closing prices cleanly
    close = df['Close'].squeeze()
    
    # Compute price deltas
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    # Calculate Relative Strength (RS) and RSI
    rs = gain / (loss + 1e-10) # Avoid division by zero
    rsi_series = 100 - (100 / (1 + rs))
    
    # Return the latest closed value
    return float(rsi_series.iloc[-1])

def run_rsi_strategy(ticker: str = "SPY"):
    # 2. Extract local token and bootstrap robin_stocks
    token_path = os.path.join(os.path.dirname(__file__), "robinhood_token.json")
    if not os.path.exists(token_path):
        print(f"❌ Missing token file at: {token_path}", file=sys.stderr)
        return

    try:
        token_data = json.load(open(token_path))
        token = token_data.get("access_token") if isinstance(token_data, dict) else token_data
    except Exception as e:
        print(f"❌ Error parsing token JSON: {e}", file=sys.stderr)
        return
    
    rh.helper.set_login_state(True)
    rh.helper.SESSION.headers["Authorization"] = f"Bearer {token}"

    print(f"📡 Pulling live telemetry for {ticker} from Robinhood...")
    try:
        # Fetch the comprehensive account profile for available cash
        profile = rh.profiles.load_account_profile()
        account_data = profile[0] if isinstance(profile, list) else profile
        buying_power = float(account_data.get('buying_power', account_data.get('cash', 0.0)))

        # Pull real-time quote snapshot
        quote = rh.stocks.get_stock_quote_by_symbol(ticker)
        current_price = float(quote.get('last_trade_price', 0.0)) if quote else 0.0
        
        # Calculate 14-Day daily RSI
        current_rsi = calculate_rsi(ticker, period=14)
        
        # Merge structural indicators into the intelligence matrix
        strategy_context = {
            "target_ticker": ticker,
            "current_price": current_price,
            "available_buying_power": buying_power,
            "rsi_14_daily": round(current_rsi, 2),
            "strategy_rules": {
                "buy_threshold": "RSI < 40",
                "sell_threshold": "RSI > 60",
                "hold_condition": "RSI between 40 and 60"
            }
        }
        
    except Exception as e:
        print(f"❌ Failed to build strategy context data: {e}", file=sys.stderr)
        return

    # 3. Connect to the specified Gemini 3.5 Flash Model Core
    print("🧠 Piping analytics matrix into Gemini 3.5 Flash reasoning layer...")
    api_key = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY"))
    if not api_key:
        print("❌ Error: Missing API keys in environment.", file=sys.stderr)
        return

    client = genai.Client(api_key=api_key)
    
    system_instruction = (
        "You are an automated algorithmic risk supervisor running strict execution profiles.\n"
        "Your actions are hard-coded to technical parameters:\n"
        "- If rsi_14_daily < 40, your action must be BUY.\n"
        "- If rsi_14_daily > 60, your action must be SELL.\n"
        "- Otherwise, your action must be HOLD.\n\n"
        "Calculate the appropriate trade quantity based on available_buying_power and current_price. "
        "Never recommend a BUY if the cash cost exceeds available buying power limits."
    )

    prompt = f"Evaluate this strategy payload and return the formal order metadata:\n{json.dumps(strategy_context, indent=2)}"

    try:
        response = client.models.generate_content(
            model='gemini-3.5-flash', # Target model update
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=StrategyDecision,
                temperature=0.0, # Complete deterministic focus for systematic indicators
            ),
        )
        
        # 4. Process final structured output vector
        decision = json.loads(response.text)
        
        print("\n================ 🏹 STRATEGY ENGINE EVALUATION ================")
        print(f"📊 ASSET UNDER INSPECTION: {ticker}")
        print(f"📈 CURRENT DAILY RSI:      {strategy_context['rsi_14_daily']}")
        print(f"💵 AVAILABLE CASH:         ${strategy_context['available_buying_power']:,}")
        print("---------------------------------------------------------------")
        print(f"🤖 TARGET SIGNAL VECTOR:   {decision.get('action')}")
        print(f"📦 RECOMMENDED SHARES:     {decision.get('quantity')}")
        print(f"🎯 CONFIDENCE WEIGHT:      {decision.get('confidence_score') * 100:.1f}%")
        print(f"📝 SYSTEM RATIONALE:       {decision.get('reasoning')}")
        print("===============================================================")
        
        return decision

    except Exception as e:
        print(f"❌ Strategy pipeline execution failure: {e}", file=sys.stderr)

if __name__ == "__main__":
    run_rsi_strategy("SPY")