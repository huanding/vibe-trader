import os
import sys
import json
import argparse
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
    strategy_match: bool = Field(description="True if ALL multi-conditional criteria for a BUY or SELL are triggered.")
    reasoning: str = Field(description="Detailed execution justification mapping RSI, drawdown/run-up, and the 90%/110% volume thresholds.")

def calculate_wilder_rsi(series, period=14):
    """Computes RSI using Wilder's Smoothing Average (RMA) to match charting platforms."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    
    avg_gain = avg_gain.copy()
    avg_loss = avg_loss.copy()
    
    for i in range(period, len(series)):
        avg_gain.iloc[i] = (avg_gain.iloc[i-1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i-1] * (period - 1) + loss.iloc[i]) / period
        
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))

def fetch_market_analytics(ticker: str, period_rsi: int = 14) -> dict:
    """
    Fetches unadjusted historical daily data and computes:
    Wilder RSI, 52-Week High/Low, Run-up, Drawdown, Volume % of SMA20, SMA, and VWSMA stacks.
    """
    print(f"📈 Downloading unadjusted historical market data arrays for {ticker}...")
    
    ticker_obj = yf.Ticker(ticker)
    df = ticker_obj.history(period="2y", auto_adjust=False)
    if df.empty:
        raise ValueError(f"Could not retrieve historical data for {ticker}")
        
    close_series = df['Close'].squeeze()
    high_series = df['High'].squeeze()
    low_series = df['Low'].squeeze()
    volume_series = df['Volume'].squeeze()
    
    rsi_series = calculate_wilder_rsi(close_series, period_rsi)
    current_rsi = float(rsi_series.iloc[-1])
    
    tail_1y_high = high_series.tail(252)
    tail_1y_low = low_series.tail(252)
    
    high_52w = float(tail_1y_high.max())
    low_52w = float(tail_1y_low.min())
    latest_close = float(close_series.iloc[-1])
    
    run_up_pct = ((latest_close - low_52w) / low_52w) * 100
    drawdown_pct = ((latest_close - high_52w) / high_52w) * 100
    
    latest_volume = int(volume_series.iloc[-1])
    volume_sma20 = float(volume_series.rolling(window=20).mean().iloc[-1])
    volume_pct_of_sma20 = (latest_volume / volume_sma20) * 100
    
    # Simple Moving Average Stack Calculation
    sma5 = float(close_series.rolling(window=5).mean().iloc[-1])
    sma20 = float(close_series.rolling(window=20).mean().iloc[-1])
    sma50 = float(close_series.rolling(window=50).mean().iloc[-1])
    sma100 = float(close_series.rolling(window=100).mean().iloc[-1])
    sma200 = float(close_series.rolling(window=200).mean().iloc[-1])
    
    # Volume-Weighted Simple Moving Average (VWSMA) Stack Calculation
    vp = close_series * volume_series
    vwsma5 = float(vp.rolling(window=5).sum().iloc[-1] / volume_series.rolling(window=5).sum().iloc[-1])
    vwsma20 = float(vp.rolling(window=20).sum().iloc[-1] / volume_series.rolling(window=20).sum().iloc[-1])
    vwsma50 = float(vp.rolling(window=50).sum().iloc[-1] / volume_series.rolling(window=50).sum().iloc[-1])
    vwsma100 = float(vp.rolling(window=100).sum().iloc[-1] / volume_series.rolling(window=100).sum().iloc[-1])
    vwsma200 = float(vp.rolling(window=200).sum().iloc[-1] / volume_series.rolling(window=200).sum().iloc[-1])
    
    return {
        "latest_close": latest_close,
        "rsi_14_daily": round(current_rsi, 2),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "run_up_pct": round(run_up_pct, 2),
        "drawdown_pct": round(drawdown_pct, 2),
        "latest_volume": latest_volume,
        "volume_sma20": round(volume_sma20, 2),
        "volume_pct_of_sma20": round(volume_pct_of_sma20, 2),
        "sma5": round(sma5, 2), "vwsma5": round(vwsma5, 2),
        "sma20": round(sma20, 2), "vwsma20": round(vwsma20, 2),
        "sma50": round(sma50, 2), "vwsma50": round(vwsma50, 2),
        "sma100": round(sma100, 2), "vwsma100": round(vwsma100, 2),
        "sma200": round(sma200, 2), "vwsma200": round(vwsma200, 2)
    }

def run_rsi_strategy(ticker: str, selected_model: str):
    # 2. Authenticate and bootstrap robin_stocks session state
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

    print(f"📡 Pulling live account telemetry from Robinhood...")
    try:
        profile = rh.profiles.load_account_profile()
        account_data = profile[0] if isinstance(profile, list) else profile
        buying_power = float(account_data.get('buying_power', account_data.get('cash', 0.0)))
        
        analytics = fetch_market_analytics(ticker, period_rsi=14)
        current_price = analytics["latest_close"]
        
        strategy_context = {
            "target_ticker": ticker,
            "current_price": current_price,
            "available_buying_power": buying_power,
            "rsi_14_daily": analytics["rsi_14_daily"],
            "high_52w": analytics["high_52w"],
            "low_52w": analytics["low_52w"],
            "run_up_from_52w_low_pct": analytics["run_up_pct"],
            "drawdown_from_52w_high_pct": analytics["drawdown_pct"],
            "latest_volume": analytics["latest_volume"],
            "volume_sma20": analytics["volume_sma20"],
            "volume_pct_of_sma20": analytics["volume_pct_of_sma20"],
            "moving_averages": {
                "sma5": analytics["sma5"], "vwsma5": analytics["vwsma5"],
                "sma20": analytics["sma20"], "vwsma20": analytics["vwsma20"],
                "sma50": analytics["sma50"], "vwsma50": analytics["vwsma50"],
                "sma100": analytics["sma100"], "vwsma100": analytics["vwsma100"],
                "sma200": analytics["sma200"], "vwsma200": analytics["vwsma200"]
            },
            "strategy_rules": {
                "buy_thresholds": {
                    "rsi_condition": "RSI < 50",
                    "drawdown_condition": "drawdown_from_52w_high_pct < -10%",
                    "volume_condition": "volume_pct_of_sma20 < 90%"
                },
                "sell_thresholds": {
                    "rsi_condition": "RSI > 70",
                    "run_up_condition": "run_up_from_52w_low_pct > 30%",
                    "volume_condition": "volume_pct_of_sma20 > 110%"
                },
                "fallback": "Otherwise HOLD"
            }
        }
        
    except Exception as e:
        print(f"❌ Failed to build strategy context data: {e}", file=sys.stderr)
        return

    # 3. Connect to selected Gemini Model
    print(f"🧠 Piping analytics matrix into engine...")
    api_key = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY"))
    if not api_key:
        print("❌ Error: Missing API keys in environment.", file=sys.stderr)
        return

    client = genai.Client(api_key=api_key)
    
    system_instruction = (
        "You are an automated algorithmic risk supervisor running strict execution profiles.\n"
        "Your actions are hard-coded to a strict sequence of logical gates:\n\n"
        "GATE 1 (BUY SIGNALS):\n"
        "To return 'BUY', ALL three of these metrics must be true simultaneously:\n"
        "- rsi_14_daily must be LESS THAN 50\n"
        "- drawdown_from_52w_high_pct must be LESS THAN -10\n"
        "- volume_pct_of_sma20 must be LESS THAN 90\n\n"
        "GATE 2 (SELL SIGNALS):\n"
        "To return 'SELL', ALL three of these metrics must be true simultaneously:\n"
        "- rsi_14_daily must be GREATER THAN 70\n"
        "- run_up_from_52w_low_pct must be GREATER THAN 30\n"
        "- volume_pct_of_sma20 must be GREATER THAN 110\n\n"
        "GATE 3 (FALLBACK):\n"
        "If either the BUY block or the SELL block fails to meet ALL their respective conditions, your action MUST be 'HOLD'."
    )

    prompt = f"Evaluate this strategy payload and return the formal order metadata:\n{json.dumps(strategy_context, indent=2)}"

    try:
        response = client.models.generate_content(
            model=selected_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=StrategyDecision,
                temperature=0.0,
            ),
        )
        
        decision = json.loads(response.text)
        current_rsi = strategy_context['rsi_14_daily']
        ma = strategy_context['moving_averages']
        
        # 4. Streamlined Conditional Output Presentation
        print("\n================ 🏹 STRATEGY ENGINE EVALUATION ================")
        print(f"📊 ASSET UNDER INSPECTION:  {ticker.upper()}")
        print(f"💵 DAILY CLOSING PRICE:     ${strategy_context['current_price']:.2f}")
        print(f"⏱️  DAILY RSI (14):          {current_rsi}")
        
        print("-------------------- MOVING AVERAGES [SMA | VWSMA] ------")
        if current_rsi >= 50:
            print(f"🔹 5-DAY:                  ${ma['sma5']:.2f}  |  ${ma['vwsma5']:.2f}")
            print(f"🔹 20-DAY:                 ${ma['sma20']:.2f}  |  ${ma['vwsma20']:.2f}")
        
        print(f"🔹 50-DAY:                 ${ma['sma50']:.2f}  |  ${ma['vwsma50']:.2f}")
        
        if current_rsi < 50:
            print(f"🔹 100-DAY:                ${ma['sma100']:.2f}  |  ${ma['vwsma100']:.2f}")
            print(f"🔹 200-DAY:                ${ma['sma200']:.2f}  |  ${ma['vwsma200']:.2f}")
            
        print("-------------------- 52-WEEK METRICS --------------------")
        print(f"📅 52-WEEK RANGE:           [${strategy_context['low_52w']:.2f} - ${strategy_context['high_52w']:.2f}]")
        print(f"📈 RUN-UP FROM LOW:         {strategy_context['run_up_from_52w_low_pct']}%")
        print(f"📉 DRAWDOWN FROM HIGH:      {strategy_context['drawdown_from_52w_high_pct']}%")
        print("-------------------- VOLUME METRICS ---------------------")
        print(f"📊 LATEST SESSION VOLUME:   {strategy_context['latest_volume']:,}")
        print(f"🌊 VOLUME SMA (20-DAY):    {strategy_context['volume_sma20']:,}")
        print(f"⚡ VOLUME % OF SMA (20):    {strategy_context['volume_pct_of_sma20']}%")
        print("------------------- ENGINE ALGO VECTOR ------------------")
        print(f"🤖 TARGET SIGNAL VECTOR:    {decision.get('action')}")
        print(f"📝 SYSTEM RATIONALE:        {decision.get('reasoning')}")
        print("===============================================================")
        
        return decision

    except Exception as e:
        print(f"❌ Strategy pipeline execution failure: {e}", file=sys.stderr)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemini Clean Terminal Matrix Engine Configuration")
    parser.add_argument("ticker", nargs="?", default="SPY", help="Stock ticker symbol (default: SPY)")
    parser.add_argument(
        "--model", 
        choices=["3.5-flash", "3.1-flash-lite"], 
        default="3.5-flash", 
        help="Select model processor tier (default: 3.5-flash)"
    )
    args = parser.parse_args()
    
    model_map = {
        "3.5-flash": "gemini-3.5-flash",
        "3.1-flash-lite": "gemini-3.1-flash-lite"
    }
    
    run_rsi_strategy(args.ticker, model_map[args.model])