import sys
import os
# Add src to path so we can import the connector
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from connectors.mercedes_api.token_client import MercedesTokenClient

def main():
    print("========================================")
    print("   Mercedes Me - Setup (App Mode)       ")
    print("========================================")
    print("Detta script hjälper dig att logga in genom att simulera mobilappen.")
    print("Du behöver din telefon/dator till hands.")
    print("")
    
    client = MercedesTokenClient()
    
    print("Steg 1: Initierar inloggning...")
    # Step 1 generates the URL
    client.start_login_flow("ignored") # Email not strictly needed for URL gen
    
    print("")
    url = input("Klistra in den långa URL:en här (den som börjar med https://active-directory...): ")
    
    if client.exchange_code(url.strip()):
        print("\n✅ KLART! Din token är sparad.")
        print("Systemet kommer nu kunna hämta status automatiskt.")
    else:
        print("\n❌ Misslyckades. Försök igen.")

if __name__ == "__main__":
    main()

