import json
import logging
import os
import time
import uuid
import requests
import base64
import hashlib
import string
import random

logger = logging.getLogger(__name__)

CLIENT_ID = "4377386a-6232-4623-95d5-9d665c723326" 
REDIRECT_URI = "https://active-directory-v2.mercedes-benz.com/auth-callback"
SCOPE = "openid email profile ciam:email ciam:phone offline_access"
AUTH_URL = "https://id.mercedes-benz.com/as/authorization.oauth2"
TOKEN_URL = "https://id.mercedes-benz.com/as/token.oauth2"

class MercedesTokenClient:
    def __init__(self, token_path="data/mercedes_token.json"):
        self.token_path = token_path
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MercedesMe/2.13.0 (com.daimler.mm.android; Android 11)",
            "X-SessionId": str(uuid.uuid4()),
            "Accept-Language": "en-US"
        })

    def _generate_code_verifier(self):
        chars = string.ascii_uppercase + string.ascii_lowercase + string.digits + "-._~")
        return "".join(random.choice(chars) for _ in range(128))

    def _generate_code_challenge(self, verifier):
        digest = hashlib.sha256(verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def start_login_flow(self, email):
        self.code_verifier = self._generate_code_verifier()
        code_challenge = self._generate_code_challenge(self.code_verifier)
        
        params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "login"
        }
        
        r = self.session.get(AUTH_URL, params=params)
        if r.status_code != 200:
            logger.error(f"Failed to init auth: {r.status_code}")
            return False

        print("\n=== VIKTIGT: MANUELL INLOGGNING ===")
        print("1. Öppna denna länk i din webbläsare (Inkognito):")
        print(r.url)
        print("2. Logga in.")
        print("3. När du skickas vidare till en vit sida, KOPIERA HELA URL:en.")
        return True

    def exchange_code(self, url_with_code):
        try:
            if "code=" not in url_with_code:
                print("Ingen kod hittades i URLen.")
                return False
            
            code = url_with_code.split("code=")[1].split("&")[0]
            
            if not hasattr(self, 'code_verifier'):
                print("Session avbruten. Starta om scriptet.")
                return False

            data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "code_verifier": self.code_verifier
            }
            
            r = self.session.post(TOKEN_URL, data=data)
            r.raise_for_status()
            token = r.json()
            
            token['expires_at'] = time.time() + token['expires_in']
            self._save_token(token)
            print("Token sparad!")
            return True
            
        except Exception as e:
            print(f"Fel vid token-byte: {e}")
            return False

    def refresh_token(self):
        token = self._load_token()
        if not token or 'refresh_token' not in token:
            return False
            
        data = {
            "grant_type": "refresh_token",
            "refresh_token": token['refresh_token'],
            "client_id": CLIENT_ID
        }
        
        try:
            r = self.session.post(TOKEN_URL, data=data)
            r.raise_for_status()
            new_token = r.json()
            new_token['expires_at'] = time.time() + new_token['expires_in']
            if 'refresh_token' not in new_token:
                new_token['refresh_token'] = token['refresh_token']
                
            self._save_token(new_token)
            return True
        except Exception as e:
            logger.error(f"Refresh failed: {e}")
            return False

    def _save_token(self, token):
        os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
        with open(self.token_path, 'w') as f:
            json.dump(token, f)

    def _load_token(self):
        if os.path.exists(self.token_path):
            try:
                with open(self.token_path, 'r') as f:
                    return json.load(f)
            except:
                pass
        return None

    def get_valid_token(self):
        token = self._load_token()
        if not token: return None
        
        if time.time() > token.get('expires_at', 0) - 60:
            if self.refresh_token():
                token = self._load_token()
            else:
                return None
        return token['access_token']
