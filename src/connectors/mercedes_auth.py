import os
import json
import time
import logging
from requests_oauthlib import OAuth2Session

logger = logging.getLogger(__name__)

TOKEN_FILE = "data/mercedes_token.json"
# Redirect URI must match what you set in Mercedes Developer Portal
# For local access via IP: http://100.100.118.62:5000/api/mercedes/callback
REDIRECT_URI = "http://100.100.118.62:5000/api/mercedes/callback"

# Scope: We need 'mb:vehicle:status:general' and 'mb:vehicle:status:ev'
SCOPE = "mb:vehicle:status:general mb:vehicle:status:ev offline_access"

class MercedesClient:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = self._load_token()
        
    def _load_token(self):
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return None

    def _save_token(self, token):
        self.token = token
        with open(TOKEN_FILE, 'w') as f:
            json.dump(token, f)

    def get_auth_url(self):
        """
        Returns the URL the user needs to visit to log in.
        """
        oauth = OAuth2Session(self.client_id, redirect_uri=REDIRECT_URI, scope=SCOPE)
        authorization_url, state = oauth.authorization_url(
            "https://id.mercedes-benz.com/as/authorization.oauth2"
        )
        return authorization_url

    def fetch_token(self, code):
        """
        Exchanges the code (from callback) for a real token.
        """
        oauth = OAuth2Session(self.client_id, redirect_uri=REDIRECT_URI)
        token = oauth.fetch_token(
            "https://id.mercedes-benz.com/as/token.oauth2",
            code=code,
            client_secret=self.client_secret,
            include_client_id=True
        )
        self._save_token(token)
        return token

    def get_session(self):
        """
        Returns a requests session that handles token refresh automatically.
        """
        if not self.token:
            return None

        extra = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
        }

        def token_saver(token):
            self._save_token(token)

        client = OAuth2Session(
            self.client_id,
            token=self.token,
            auto_refresh_url="https://id.mercedes-benz.com/as/token.oauth2",
            auto_refresh_kwargs=extra,
            token_updater=token_saver
        )
        return client

    def get_status(self, vin):
        client = self.get_session()
        if not client:
            return None
        
        try:
            # Fetch EV status (SoC, Range)
            # API Endpoint: https://api.mercedes-benz.com/vehicle_status/v1/vehicles/{vin}/containers/evstatus
            url = f"https://api.mercedes-benz.com/vehicle_status/v1/vehicles/{vin}/containers/evstatus"
            r = client.get(url)
            
            if r.status_code == 403:
                logger.error("Mercedes API 403: Check if product is active in console.")
                return None
                
            r.raise_for_status()
            data = r.json()
            
            # Parse the complex response structure
            # "soc": {"value": 45, ...}
            soc = 0
            range_km = 0
            
            for key, item in data.items():
                if key == "soc":
                    soc = item.get("value", 0)
                if key == "rangeelectric":
                    range_km = item.get("value", 0)

            # To get "plugged in" we might need another container or assume based on charging status
            # Often in "evstatus": "chargingstatus": 0 (No), 1 (Yes) or similar? 
            # Actually it's usually "chargingactive" or we can check "soc" timestamp?
            # Let's assume plugged in if we get data for now, or improve later.
            
            return {
                "soc": soc,
                "range_km": range_km,
                "plugged_in": True # TODO: Check specific plugged status field
            }

        except Exception as e:
            logger.error(f"Mercedes API Error: {e}")
            return None
