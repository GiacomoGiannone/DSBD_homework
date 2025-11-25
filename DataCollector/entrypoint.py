#!/usr/bin/env python3
"""
Entrypoint with token generation - simplified
"""
import os
import sys
import json
import requests

def get_token(client_id, client_secret):
    """Generate OpenSky token if credentials are available"""
    if not client_id or not client_secret:
        return None
    
    try:
        response = requests.post(
            "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret
            },
            timeout=10
        )
        if response.status_code == 200:
            return response.json().get("access_token")
    except:
        pass
    return None

def main():
    # Load credentials
    cred_path = '/credentials/credentials.json'
    if os.path.exists(cred_path):
        with open(cred_path) as f:
            creds = json.load(f)
        
        client_id = creds.get('clientId')
        client_secret = creds.get('clientSecret')
        
        if client_id and client_secret:
            os.environ['OPEN_SKY_CLIENT_ID'] = client_id
            os.environ['OPEN_SKY_CLIENT_SECRET'] = client_secret
            
            # Generate token
            token = get_token(client_id, client_secret)
            if token:
                os.environ['OPEN_SKY_TOKEN'] = token
                print("✅ Generated OpenSky token")
    
    # Start app
    os.execvp(sys.executable, [sys.executable, '/app/data_collector.py'])

if __name__ == '__main__':
    main()