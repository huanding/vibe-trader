import os
import json
import robin_stocks.robinhood as rh

def get_accounts():
    token_path = os.path.join(os.path.dirname(__file__), "robinhood_token.json")
    
    if not os.path.exists(token_path):
        print(f"❌ Missing token file at: {token_path}")
        return

    # Extract raw bearer token
    token_data = json.load(open(token_path))
    token = token_data.get("access_token") if isinstance(token_data, dict) else token_data

    # Inject token directly into robin_stocks session state
    rh.helper.set_login_state(True)
    rh.helper.SESSION.headers["Authorization"] = f"Bearer {token}"

    try:
        profiles = rh.profiles.load_account_profile()
        print("\n================ ROBINHOOD ACCOUNTS ================")
        if isinstance(profiles, dict):
            print(f"🔹 Account ID: {profiles.get('account_number')} | Type: {profiles.get('type').upper()}")
        elif isinstance(profiles, list):
            for idx, acc in enumerate(profiles, 1):
                print(f"{idx:02d}. Account ID: {acc.get('account_number')} | Type: {acc.get('type').upper()}")
        print("====================================================")
    except Exception as e:
        print(f"❌ Failed to fetch profiles: {e}")

if __name__ == "__main__":
    get_accounts()