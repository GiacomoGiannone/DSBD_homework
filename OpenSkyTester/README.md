# OpenSky API Tester
Local Python tool for testing OpenSky API integration and token generation.

## Setup
```powershell
# Install dependencies
pip install requests

# Create credentials.json with your OpenSky OAuth credentials
# See credentials.example.json for format
```

## Usage

### Option 1: Command-line arguments
```powershell
python opensky_tester.py --client-id YOUR_ID --client-secret YOUR_SECRET
```

### Option 2: Environment variables
```powershell
$env:OPEN_SKY_CLIENT_ID = "YOUR_ID"
$env:OPEN_SKY_CLIENT_SECRET = "YOUR_SECRET"
python opensky_tester.py
```

### Option 3: Test specific airports
```powershell
python opensky_tester.py --client-id YOUR_ID --client-secret YOUR_SECRET --airports KJFK EGLL LFPG
```

## What it tests
- ✅ OAuth token generation from client credentials
- ✅ Flights API (departures and arrivals)
- ✅ States API (real-time aircraft positions)
- ✅ Multiple airports simultaneously

## Output
- Token validity and expiration
- Number of flights found for each airport
- Sample flight data (callsign, route)
- Real-time aircraft state vectors
