import yfinance as yf

class TickerAnalyzer:
    def __init__(self, symbol: str, drawdown_threshold: float = 2.0, target_gain_threshold: float = 10.0):
        self.symbol = symbol.upper()
        self.drawdown_threshold = drawdown_threshold
        self.target_gain_threshold = target_gain_threshold
        self.current_price = None
        self.high_52week = None
        self.drawdown = None

    def update_market_data(self) -> bool:
        """Fetches fresh market data via yfinance."""
        print(f"Fetching market data for {self.symbol}...")
        try:
            ticker = yf.Ticker(self.symbol)
            info = ticker.info
            self.current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            self.high_52week = info.get("fiftyTwoWeekHigh")
            
            if not self.current_price or not self.high_52week:
                return False
                
            self.drawdown = ((self.high_52week - self.current_price) / self.high_52week) * 100
            print(f"{self.symbol} Price: ${self.current_price:.2f} | 52W High: ${self.high_52week:.2f} | Drawdown: {self.drawdown:.2f}%")
            return True
        except Exception as e:
            print(f"Error fetching data from yfinance: {e}")
            return False

    def evaluate_tax_lots(self, open_lots: list) -> dict:
        """
        Filters and evaluates open stock lots for target gains.
        Returns the lot structure with the lowest qualifying gain or None.
        """
        matching_lots = [lot for lot in open_lots if lot.get("symbol") == self.symbol]
        if not matching_lots:
            print(f"No active tax lots found for {self.symbol}.")
            return None

        print(f"\nEvaluating {len(matching_lots)} active tax lots for {self.symbol}...")
        qualifying_lots = []
        
        for idx, lot in enumerate(matching_lots):
            cost_basis = float(lot["cost_basis_per_share"])
            quantity = float(lot["quantity"])
            lot_gain_pct = ((self.current_price - cost_basis) / cost_basis) * 100
            
            print(f"  • Lot #{idx+1}: Qty: {quantity} | Basis: ${cost_basis:.2f} | Gain: {lot_gain_pct:.2f}%")
            
            if lot_gain_pct >= self.target_gain_threshold:
                qualifying_lots.append({
                    "lot": lot,
                    "gain_pct": lot_gain_pct,
                    "quantity": quantity
                })

        if qualifying_lots:
            # Sort ascending by gain_pct to isolate the lowest matching lot
            qualifying_lots.sort(key=lambda x: x["gain_pct"])
            return qualifying_lots[0]
            
        return None

    def should_trigger_buy(self) -> bool:
        """Evaluates macro buy logic if flat cash."""
        if self.drawdown is not None and self.drawdown >= self.drawdown_threshold:
            return True
        return False