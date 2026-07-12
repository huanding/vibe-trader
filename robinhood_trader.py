import json
import requests

class RobinhoodTrader:
    def __init__(self, auth_instance, gateway_url: str = "https://agent.robinhood.com/mcp/trading"):
        self.auth = auth_instance
        self.gateway_url = gateway_url

    def _post_with_retry(self, payload: dict) -> requests.Response:
        """Internal helper handling connection posts and access token rotation cascades."""
        headers = self.auth.get_headers()
        response = requests.post(self.gateway_url, json=payload, headers=headers)
        
        if response.status_code == 401:
            print("Warning: Access token expired (401). Retrying with token rotation...")
            if self.auth.refresh_access_token():
                headers = self.auth.get_headers()
                response = requests.post(self.gateway_url, json=payload, headers=headers)
                
        return response

    def fetch_open_stock_lots(self) -> list:
        """Queries the MCP node for structural asset tax lots."""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "get_equity_tax_lots",
                "arguments": {"account_number": self.auth.account_number}
            },
            "id": 1
        }
        
        print("\nChecking live portfolio tax lots...")
        response = self._post_with_retry(payload)
        
        if response.status_code != 200:
            print(f"API Error fetching positions: Status {response.status_code}")
            return []
        print("DEBUG RAW RESPONSE:", response.text)    
        try:
            raw_text = response.text
            if raw_text.startswith("event:"):
                data_line = [line for line in raw_text.splitlines() if line.startswith("data:")][0]
                inner_json = json.loads(data_line.replace("data: ", ""))
            else:
                inner_json = json.loads(raw_text)

            content_str = inner_json["result"]["content"][0]["text"]
            portfolio_data = json.loads(content_str)
            return portfolio_data.get("data", {}).get("open_stock_lots", [])
        except Exception as e:
            print(f"Data Parser Warning: Could not parse lots cleanly. Detail: {e}")
            return []

    def execute_order(self, order_args: dict) -> bool:
        """Pipes a structured execution order payload directly to execution gates."""
        trade_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "place_equity_order",
                "arguments": order_args
            },
            "id": 2
        }
        
        print(f"\nSubmitting trade execution request via tool: place_equity_order...")
        response = self._post_with_retry(trade_payload)
        
        print(f"Gateway HTTP Status Code: {response.status_code}")
        if response.text:
            print("--- Order Gateway Stream Output ---")
            print(response.text)
            
        return response.status_code == 200