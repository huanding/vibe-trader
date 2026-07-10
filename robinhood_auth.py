import os
import json
import requests

class RobinhoodAuth:
    """
    Handles secure loading of Robinhood credentials from disk state and 
    manages automatic token rotation state loops for GitHub workflow environments.
    """
    def __init__(self):
        self.account_number = os.getenv("ROBINHOOD_ACCOUNT_NUMBER")
        self.client_id = os.getenv("ROBINHOOD_CLIENT_ID")
        self.token_file = "robinhood_token.json"
        
        self.access_token = None
        self.refresh_token = None
        
        self._validate_initial_state()
        self._load_token_file()

    def _validate_initial_state(self):
        """Ensures fundamental environment configurations are available."""
        if not self.account_number or not self.client_id:
            raise RuntimeError("Security Exception: Missing required account configuration environment variables.")

    def _load_token_file(self):
        """Loads active token states decrypted onto the disk by the runner."""
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, "r") as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token")
                    self.refresh_token = data.get("refresh_token")
            except Exception as e:
                print(f"File System Warning: Failed to parse state JSON: {e}")

    def _write_token_file(self):
        """Flushes newly rotated tokens back to disk for artifact compression."""
        data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token
        }
        with open(self.token_file, "w") as f:
            json.dump(data, f, indent=2)
        print("💾 State tracking: Saved updated tokens to local workspace.")

    def get_headers(self) -> dict:
        """Constructs headers using the verified token pool."""
        if not self.access_token:
            self.refresh_access_token()
            if not self.access_token:
                raise RuntimeError("Fatal Exception: Missing valid authorization tokens.")
                
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def refresh_access_token(self) -> str:
        """Communicates with Robinhood Auth Authority to rotate the session tokens."""
        if not self.refresh_token:
            print("Rotation Error: Missing active REFRESH_TOKEN state.")
            return None

        print("🔄 Attempting automatic session rotation via Robinhood Auth Authority...")
        oauth_url = "https://api.robinhood.com/oauth2/token/"
        
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        try:
            response = requests.post(oauth_url, data=payload, headers=headers)
            if response.status_code == 200:
                token_metadata = response.json()
                self.access_token = token_metadata.get("access_token")
                self.refresh_token = token_metadata.get("refresh_token") # Capture the new rotation grant!
                
                # Instantly write back to file system so the workflow picks it up
                self._write_token_file()
                print("✨ Rotation Success! New active tokens issued and written.")
                return self.access_token
            else:
                print(f"❌ OAuth Server rejected refresh: Status {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Failed to communicate with token authority: {e}")
            return None