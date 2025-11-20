#!/usr/bin/env python3
"""
OpenSky API Tester - Local development tool (not containerized)
Tests OpenSky API endpoints with OAuth token authentication.

Run locally:
  python opensky_tester.py --client-id YOUR_ID --client-secret YOUR_SECRET
  
Or set env vars:
  OPEN_SKY_CLIENT_ID=YOUR_ID OPEN_SKY_CLIENT_SECRET=YOUR_SECRET python opensky_tester.py
"""
import os
import sys
import json
import argparse
import requests
import time


def get_opensky_token(client_id, client_secret):
    """Generate OpenSky OAuth token"""
    if not client_id or not client_secret:
        print("❌ ERROR: OpenSky credentials not provided")
        print("Please set:")
        print("  OPEN_SKY_CLIENT_ID=your_client_id")
        print("  OPEN_SKY_CLIENT_SECRET=your_client_secret")
        return None
    
    url = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret
    }
    
    try:
        print("🔄 Requesting token from OpenSky...")
        response = requests.post(url, headers=headers, data=data, timeout=30)
        response.raise_for_status()
        
        token_data = response.json()
        access_token = token_data.get("access_token")
        token_type = token_data.get("token_type")
        expires_in = token_data.get("expires_in")
        
        print("✅ Token generated successfully!")
        print(f"   Token Type: {token_type}")
        print(f"   Expires in: {expires_in} seconds")
        print(f"   Access Token: {access_token[:50]}...")
        
        return access_token
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to get OpenSky token: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"   Status Code: {e.response.status_code}")
            print(f"   Response: {e.response.text}")
        return None


def test_flights_api(token):
    """Test the flights API with the token"""
    print("\n" + "="*50)
    print("🛫 TESTING FLIGHTS API")
    print("="*50)
    
    endpoints = [
        {
            "name": "Departures (Milan Malpensa)",
            "url": "https://opensky-network.org/api/flights/departure",
            "params": {"airport": "LIMC", "begin": 1719849600, "end": 1719860400}
        },
        {
            "name": "Arrivals (Frankfurt)",
            "url": "https://opensky-network.org/api/flights/arrival", 
            "params": {"airport": "EDDF", "begin": 1719849600, "end": 1719860400}
        },
        {
            "name": "All States (Real-time)",
            "url": "https://opensky-network.org/api/states/all",
            "params": {}
        }
    ]
    
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    for endpoint in endpoints:
        print(f"\n🔍 Testing: {endpoint['name']}")
        print(f"   URL: {endpoint['url']}")
        
        try:
            response = requests.get(
                endpoint['url'], 
                params=endpoint['params'],
                headers=headers,
                timeout=30
            )
            
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    print(f"   ✅ Success! Found {len(data)} flights")
                    if data:
                        print(f"   Sample: {json.dumps(data[0], indent=6)}")
                elif isinstance(data, dict) and 'states' in data:
                    states = data['states'] or []
                    print(f"   ✅ Success! Found {len(states)} aircraft states")
                    if states:
                        print(f"   Sample aircraft: {states[0][1]} (ICAO24: {states[0][0]})")
                else:
                    print(f"   ✅ Success! Data: {data}")
            else:
                print(f"   ❌ Failed: {response.reason}")
                if response.text:
                    print(f"   Details: {response.text[:200]}...")
                    
        except Exception as e:
            print(f"   ❌ Error: {e}")


def test_airport_flights(token, airport_code):
    """Test getting flights for a specific airport"""
    print(f"\n🏢 Testing flights for airport: {airport_code}")
    
    end = int(time.time())
    begin = end - 3 * 3600
    
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    # Test departures
    dep_url = "https://opensky-network.org/api/flights/departure"
    dep_params = {"airport": airport_code, "begin": begin, "end": end}
    
    try:
        print(f"   📤 Departures from {airport_code}...")
        dep_response = requests.get(dep_url, params=dep_params, headers=headers, timeout=30)
        
        if dep_response.status_code == 200:
            departures = dep_response.json()
            print(f"   ✅ Found {len(departures)} departures")
            for flight in departures[:3]:
                callsign = flight.get('callsign', 'N/A').strip()
                est_arrival = flight.get('estArrivalAirport', 'N/A')
                print(f"      ✈️ {callsign} → {est_arrival}")
        else:
            print(f"   ❌ Departures failed: {dep_response.status_code} - {dep_response.reason}")
            
    except Exception as e:
        print(f"   ❌ Departures error: {e}")
    
    # Test arrivals
    arr_url = "https://opensky-network.org/api/flights/arrival"
    arr_params = {"airport": airport_code, "begin": begin, "end": end}
    
    try:
        print(f"   📥 Arrivals to {airport_code}...")
        arr_response = requests.get(arr_url, params=arr_params, headers=headers, timeout=30)
        
        if arr_response.status_code == 200:
            arrivals = arr_response.json()
            print(f"   ✅ Found {len(arrivals)} arrivals") 
            for flight in arrivals[:3]:
                callsign = flight.get('callsign', 'N/A').strip()
                est_departure = flight.get('estDepartureAirport', 'N/A')
                print(f"      ✈️ {est_departure} → {callsign}")
        else:
            print(f"   ❌ Arrivals failed: {arr_response.status_code} - {arr_response.reason}")
            
    except Exception as e:
        print(f"   ❌ Arrivals error: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="OpenSky API Tester - Test OAuth token generation and API endpoints"
    )
    parser.add_argument('--client-id', help='OpenSky Client ID (or OPEN_SKY_CLIENT_ID env var)')
    parser.add_argument('--client-secret', help='OpenSky Client Secret (or OPEN_SKY_CLIENT_SECRET env var)')
    parser.add_argument('--airports', nargs='+', default=['LIMC', 'EDDF', 'KJFK', 'LHR'],
                       help='Airport codes to test (default: LIMC EDDF KJFK LHR)')
    
    args = parser.parse_args()
    
    client_id = args.client_id or os.getenv("OPEN_SKY_CLIENT_ID", "")
    client_secret = args.client_secret or os.getenv("OPEN_SKY_CLIENT_SECRET", "")
    
    print("🚀 OpenSky API Token Tester")
    print("="*50)
    
    token = get_opensky_token(client_id, client_secret)
    
    if token:
        test_flights_api(token)
        for airport in args.airports:
            test_airport_flights(token, airport)
    else:
        print("\n❌ Cannot proceed without valid token")
        sys.exit(1)


if __name__ == "__main__":
    main()
