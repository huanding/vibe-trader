import os
import requests

class RobinhoodAuth:
    """
    Handles secure loading of Robinhood credentials from environment variables
    and manages automatic token rotation loops.
    """
    def __init__(self):
        self.account_number = os.getenv("ROBINHOOD_ACCOUNT_NUMBER")
        self.access_token = os.getenv("ROBINHOOD_ACCESS_TOKEN")
        self.refresh_token = os.getenv("ROBINHOOD_REFRESH_TOKEN")
        self.client_id = os.getenv("ROBINHOOD_CLIENT_ID")
        
        self._validate_initial_state()

    def _validate_initial_state(self):
        """Ensures fundamental routing requirements are met."""
        if not self.account_number:
            raise RuntimeError("Security Exception: ROBINHOOD_ACCOUNT_NUMBER environment variable is missing.")

    def get_headers(self) -> dict:
        """Constructs request headers using the active access token."""
        if not self.access_token:
            self.refresh_access_token()
            if not self.access_token:
                raise RuntimeError("Fatal Exception: Missing valid authorization to poll broker endpoints.")
                
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def refresh_access_token(self) -> str:
        """Communicates with Robinhood Auth Authority to rotate the active session token."""
        if not self.refresh_token:
            print("Rotation Error: Cannot refresh token. ROBINHOOD_REFRESH_TOKEN is not set.")
            return None
        if not self.client_id:
            print("Rotation Error: Cannot refresh token. ROBINHOOD_CLIENT_ID is not set.")
            return None

        print("Attempting automatic session rotation via Robinhood Auth Authority...")
        oauth_url = "https://api.robinhood.com/oauth2/token/"
        
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            response = requests.post(oauth_url, data=payload, headers=headers)
            if response.status_code == 200:
                token_metadata = response.json()
                self.access_token = token_metadata.get("access_token")
                print("Rotation Success! New active bearer token issued.")
                return self.access_token
            else:
                print(f"OAuth Server rejected refresh: Status {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Failed to communicate with token authority: {e}")
            return None