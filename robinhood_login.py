import os
import sys
import json
import robin_stocks.robinhood as r

username = os.getenv("ROBINHOOD_USERNAME")
if not username:
    print("❌ Error: ROBINHOOD_USERNAME environment variable is not set.", file=sys.stderr)
    print("Please export it first: export ROBINHOOD_USERNAME='your_email@gmail.com'", file=sys.stderr)
    sys.exit(1)

print("Forcing text/email authentication code workflow...")
# Passing an empty string here bypasses the push notification deadlock
login = r.login(username=username, mfa_code="")

# Process the flat format returned in your console output
if isinstance(login, dict) and "access_token" in login:
    token_data = {
        "access_token": login.get("access_token"),
        "expires_in": login.get("expires_in"),
        "token_type": login.get("token_type"),
        "scope": login.get("scope"),
        "refresh_token": login.get("refresh_token"),
        "user_uuid": login.get("user_uuid")
    }
    
    output_filename = "robinhood_token.json"
    with open(output_filename, "w") as f:
        json.dump(token_data, f, indent=4)
        
    print(f"\n✅ Success! Token data written directly to {output_filename}")
else:
    print("\n❌ Login failed or returned an unexpected format:", login_result)
