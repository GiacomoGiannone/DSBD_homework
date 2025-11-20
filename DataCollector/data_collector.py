import os
import time
import logging
import threading
import json
from concurrent import futures
import requests
import mysql.connector
import grpc
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import re
import csv
from io import StringIO

import DataCollector_pb2 as pb2
import DataCollector_pb2_grpc as pb2_grpc

USER_DB = {
	"host": os.getenv("USER_DB_HOST", "userdb"),
	"port": int(os.getenv("USER_DB_PORT", "3306")),
	"database": os.getenv("USER_DB_NAME", "userdb"),
	"user": os.getenv("USER_DB_USER", "root"),
	"password": os.getenv("USER_DB_PASSWORD", "root"),
}

DATA_DB = {
	"host": os.getenv("DATA_DB_HOST", "datadb"),
	"port": int(os.getenv("DATA_DB_PORT", "3306")),
	"database": os.getenv("DATA_DB_NAME", "datadb"),
	"user": os.getenv("DATA_DB_USER", "root"),
	"password": os.getenv("DATA_DB_PASSWORD", "root"),
}

OPEN_SKY_USER = os.getenv("OPENSKY_USER", "")
OPEN_SKY_PASS = os.getenv("OPENSKY_PASS", "")
OPEN_SKY_CLIENT_ID = os.getenv("OPEN_SKY_CLIENT_ID", "")
OPEN_SKY_CLIENT_SECRET = os.getenv("OPEN_SKY_CLIENT_SECRET", "")
OPEN_SKY_TOKEN = os.getenv("OPEN_SKY_TOKEN", "")
AIRPORTS_SOURCE_URL = os.getenv("AIRPORTS_SOURCE_URL", "https://raw.githubusercontent.com/davidmegginson/ourairports-data/master/airports.csv")

REFRESH_INTERVAL_SECONDS = int(os.getenv("REFRESH_INTERVAL_SECONDS", str(12*3600)))
GRPC_PORT = int(os.getenv("DATACOLLECTOR_GRPC_PORT", "50052"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def get_opensky_oauth_token(client_id: str, client_secret: str):
	"""Generate OpenSky OAuth token from client credentials."""
	if not client_id or not client_secret:
		return None
	try:
		url = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
		headers = {"Content-Type": "application/x-www-form-urlencoded"}
		data = {
			"grant_type": "client_credentials",
			"client_id": client_id,
			"client_secret": client_secret
		}
		response = requests.post(url, headers=headers, data=data, timeout=10)
		if response.status_code == 200:
			token_data = response.json()
			access_token = token_data.get("access_token")
			expires_in = token_data.get("expires_in")
			if access_token:
				logging.info(f"OpenSky OAuth token generated (expires in {expires_in}s)")
				return access_token
		else:
			logging.warning(f"OpenSky OAuth response failed: {response.status_code}")
		return None
	except Exception as e:
		logging.warning(f"Failed to fetch OpenSky OAuth token: {e}")
		return None


def get_user_conn():
	return mysql.connector.connect(**USER_DB)


def get_data_conn():
	return mysql.connector.connect(**DATA_DB)


def fetch_airports_for_email(email: str):
	conn = get_user_conn()
	cur = conn.cursor()
	cur.execute("SELECT airport_code FROM interests WHERE email=%s", (email,))
	rows = [r[0] for r in cur.fetchall()]
	cur.close(); conn.close()
	return rows


def fetch_all_airports():
	conn = get_user_conn()
	cur = conn.cursor()
	cur.execute("SELECT DISTINCT airport_code FROM interests")
	rows = [r[0] for r in cur.fetchall()]
	cur.close(); conn.close()
	return rows


def opensky_get(url, params):
	"""Make authenticated request to OpenSky API using OAuth token or basic auth."""
	headers = {}
	auth = None
	
	# Priority: OAuth token (if available) > Basic auth (user/pass) > No auth
	if OPEN_SKY_TOKEN:
		headers["Authorization"] = f"Bearer {OPEN_SKY_TOKEN}"
	elif OPEN_SKY_USER and OPEN_SKY_PASS:
		auth = (OPEN_SKY_USER, OPEN_SKY_PASS)
	
	try:
		r = requests.get(url, params=params, headers=headers, auth=auth, timeout=30)
		if r.status_code == 200:
			return r.json()
		logging.warning("OpenSky %s %s -> %s", url, params, r.status_code)
	except Exception as e:
		logging.warning("OpenSky request failed: %s", e)
	return []


def refresh_flights(airports):
	begin = int(time.time()) - 12*3600
	end = int(time.time())
	count = 0
	conn = get_data_conn()
	cur = conn.cursor()
	for code in airports:
		dep_url = "https://opensky-network.org/api/flights/departure"
		arr_url = "https://opensky-network.org/api/flights/arrival"
		departures = opensky_get(dep_url, {"airport": code, "begin": begin, "end": end}) or []
		arrivals = opensky_get(arr_url, {"airport": code, "begin": begin, "end": end}) or []
		for d in departures:
			try:
				cur.execute(
					"""
					INSERT INTO flights (icao24, callsign, departure_airport, arrival_airport, departure_time, arrival_time, flight_type)
					VALUES (%s,%s,%s,%s,%s,%s,'DEPARTURE')
					ON DUPLICATE KEY UPDATE callsign=VALUES(callsign), arrival_airport=VALUES(arrival_airport), arrival_time=VALUES(arrival_time)
					""",
					(d.get('icao24'), d.get('callsign'), d.get('airport'), d.get('estArrivalAirport'), d.get('firstSeen'), d.get('lastSeen'))
				)
				count += 1
			except Exception as e:
				logging.debug("Skip departure %s: %s", d, e)
		for a in arrivals:
			try:
				cur.execute(
					"""
					INSERT INTO flights (icao24, callsign, departure_airport, arrival_airport, departure_time, arrival_time, flight_type)
					VALUES (%s,%s,%s,%s,%s,%s,'ARRIVAL')
					ON DUPLICATE KEY UPDATE callsign=VALUES(callsign), departure_airport=VALUES(departure_airport), departure_time=VALUES(departure_time)
					""",
					(a.get('icao24'), a.get('callsign'), a.get('estDepartureAirport'), a.get('airport'), a.get('firstSeen'), a.get('lastSeen'))
				)
				count += 1
			except Exception as e:
				logging.debug("Skip arrival %s: %s", a, e)
	conn.commit(); cur.close(); conn.close()
	return count


class DataCollectorService(pb2_grpc.DataCollectorServiceServicer):
	def AddAirport(self, request, context):
		email = (request.email or '').strip()
		code = (request.code or '').strip().upper()
		if not email or not code:
			return pb2.GenericResponse(status=400, message='email and code required')
		# Basic validation: 3-10 alphanumerics (ICAO/IATA simplified)
		if not re.fullmatch(r'[A-Z0-9]{3,10}', code):
			return pb2.GenericResponse(status=400, message='invalid airport code (expected 3-10 A-Z/0-9)')
		try:
			conn = get_user_conn(); cur = conn.cursor()
			cur.execute("SELECT 1 FROM interests WHERE email=%s AND airport_code=%s", (email, code))
			if cur.fetchone():
				cur.close(); conn.close()
				return pb2.GenericResponse(status=409, message='already exists')
			cur.execute("INSERT INTO interests (email, airport_code) VALUES (%s,%s)", (email, code))
			conn.commit(); cur.close(); conn.close()
			# Immediate refresh for this airport to populate flights
			try:
				refreshed = refresh_flights([code])
				return pb2.GenericResponse(status=201, message=f'added; refreshed {refreshed} flights')
			except Exception as e:
				logging.warning("Immediate refresh failed for %s: %s", code, e)
				return pb2.GenericResponse(status=201, message='added; refresh deferred')
		except Exception as e:
			logging.exception("AddAirport failed")
			return pb2.GenericResponse(status=500, message=str(e))

	def RemoveAirport(self, request, context):
		email = (request.email or '').strip()
		code = (request.code or '').strip().upper()
		if not email or not code:
			return pb2.GenericResponse(status=400, message='email and code required')
		try:
			conn = get_user_conn(); cur = conn.cursor()
			cur.execute("DELETE FROM interests WHERE email=%s AND airport_code=%s", (email, code))
			affected = cur.rowcount
			conn.commit(); cur.close(); conn.close()
			if affected == 0:
				return pb2.GenericResponse(status=404, message='not found')
			# Optionally purge flights for this airport (global data) if requested via env
			if os.getenv('PURGE_ON_REMOVE', 'false').lower() in ('1','true','yes','y'):
				try:
					dconn = get_data_conn(); dcur = dconn.cursor()
					dcur.execute("DELETE FROM flights WHERE departure_airport=%s OR arrival_airport=%s", (code, code))
					purged = dcur.rowcount
					dconn.commit(); dcur.close(); dconn.close()
					return pb2.GenericResponse(status=200, message=f'removed; purged {purged} flights')
				except Exception as e:
					logging.warning("Purge on remove failed for %s: %s", code, e)
					return pb2.GenericResponse(status=200, message='removed; purge failed')
			return pb2.GenericResponse(status=200, message='removed')
		except Exception as e:
			logging.exception("RemoveAirport failed")
			return pb2.GenericResponse(status=500, message=str(e))

	def ListAirports(self, request, context):
		email = (request.email or '').strip()
		if not email:
			return pb2.AirportListResponse(codes=[])
		codes = fetch_airports_for_email(email)
		return pb2.AirportListResponse(codes=codes)

	def RefreshFlights(self, request, context):
		email = (request.email or '').strip()
		airports = fetch_airports_for_email(email) if email else fetch_all_airports()
		if not airports:
			return pb2.RefreshResponse(refreshed_count=0, message='no airports')
		count = refresh_flights(airports)
		return pb2.RefreshResponse(refreshed_count=count, message='ok')

	def ListFlights(self, request, context):
		email = (request.email or '').strip()
		airport_filter = (request.airport or '').strip().upper()
		airports = fetch_airports_for_email(email) if email else fetch_all_airports()
		if airport_filter and airport_filter not in airports:
			return pb2.FlightsResponse(flights=[])
		conn = get_data_conn(); cur = conn.cursor()
		if airport_filter:
			cur.execute("SELECT icao24,callsign,departure_airport,arrival_airport,departure_time,arrival_time,flight_type FROM flights WHERE departure_airport=%s OR arrival_airport=%s ORDER BY last_refresh DESC LIMIT 500", (airport_filter, airport_filter))
		else:
			if not airports:
				cur.close(); conn.close(); return pb2.FlightsResponse(flights=[])
			placeholders = ','.join(['%s']*len(airports))
			sql = f"SELECT icao24,callsign,departure_airport,arrival_airport,departure_time,arrival_time,flight_type FROM flights WHERE departure_airport IN ({placeholders}) OR arrival_airport IN ({placeholders}) ORDER BY last_refresh DESC LIMIT 500"
			cur.execute(sql, airports+airports)
		rows = cur.fetchall(); cur.close(); conn.close()
		flights = [pb2.Flight(icao24=r[0] or '', callsign=r[1] or '', departure_airport=r[2] or '', arrival_airport=r[3] or '', departure_time=r[4] or 0, arrival_time=r[5] or 0, flight_type=r[6] or '') for r in rows]
		return pb2.FlightsResponse(flights=flights)


def periodic_loop():
	while True:
		try:
			airports = fetch_all_airports()
			if airports:
				refresh_flights(airports)
		except Exception as e:
			logging.error("Periodic refresh failed: %s", e)
		time.sleep(REFRESH_INTERVAL_SECONDS)


def serve():
	server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
	pb2_grpc.add_DataCollectorServiceServicer_to_server(DataCollectorService(), server)
	server.add_insecure_port(f"[::]:{GRPC_PORT}")
	server.start()
	logging.info("DataCollector gRPC listening on %s", GRPC_PORT)
	server.wait_for_termination()


if __name__ == '__main__':
	# Start periodic refresh thread
	t = threading.Thread(target=periodic_loop, daemon=True)
	t.start()

	# Minimal REST API for browser testing
	app = Flask(__name__)
	CORS(app)  # allow calls from user-manager (8081)

	@app.post('/api/add_airport')
	def api_add_airport():
		data = request.get_json(silent=True) or {}
		email = (data.get('email') or '').strip()
		code = (data.get('code') or '').strip().upper()
		svc = DataCollectorService()
		res = svc.AddAirport(type('Req', (), {'email': email, 'code': code})(), None)
		return jsonify({'status': res.status, 'message': res.message}), (201 if res.status == 201 else 200 if res.status == 200 else 400 if res.status == 400 else 404 if res.status == 404 else 409 if res.status == 409 else 500)

	@app.post('/api/remove_airport')
	def api_remove_airport():
		data = request.get_json(silent=True) or {}
		email = (data.get('email') or '').strip()
		code = (data.get('code') or '').strip().upper()
		svc = DataCollectorService()
		res = svc.RemoveAirport(type('Req', (), {'email': email, 'code': code})(), None)
		return jsonify({'status': res.status, 'message': res.message}), (200 if res.status in (200,404,409) else 400 if res.status == 400 else 500)

	@app.post('/api/list_airports')
	def api_list_airports():
		data = request.get_json(silent=True) or {}
		email = (data.get('email') or '').strip()
		svc = DataCollectorService()
		res = svc.ListAirports(type('Req', (), {'email': email})(), None)
		return jsonify({'codes': list(res.codes)})

	@app.post('/api/refresh')
	def api_refresh():
		data = request.get_json(silent=True) or {}
		email = (data.get('email') or '').strip()
		svc = DataCollectorService()
		res = svc.RefreshFlights(type('Req', (), {'email': email})(), None)
		return jsonify({'refreshed_count': res.refreshed_count, 'message': res.message})

	@app.post('/api/list_flights')
	def api_list_flights():
		data = request.get_json(silent=True) or {}
		email = (data.get('email') or '').strip()
		airport = (data.get('airport') or '').strip().upper()
		svc = DataCollectorService()
		res = svc.ListFlights(type('Req', (), {'email': email, 'airport': airport})(), None)
		flights = [
			{
				'icao24': f.icao24,
				'callsign': f.callsign,
				'departure_airport': f.departure_airport,
				'arrival_airport': f.arrival_airport,
				'departure_time': f.departure_time,
				'arrival_time': f.arrival_time,
				'flight_type': f.flight_type,
			} for f in res.flights
		]
		return jsonify({'flights': flights})

	# --- Airport suggestions cache & API ---
	_airports_cache = { 'loaded': False, 'rows': [], 'ts': 0 }
	_cache_lock = threading.Lock()

	def _load_airports_if_needed(force: bool = False):
		with _cache_lock:
			if _airports_cache['loaded'] and not force:
				return
			try:
				logging.info("Loading airports dataset from %s", AIRPORTS_SOURCE_URL)
				r = requests.get(AIRPORTS_SOURCE_URL, timeout=30)
				r.raise_for_status()
				text = r.text
				rows = []
				reader = csv.DictReader(StringIO(text))
				for row in reader:
					ident = (row.get('ident') or '').strip().upper()
					iata = (row.get('iata_code') or '').strip().upper()
					name = (row.get('name') or '').strip()
					city = (row.get('municipality') or '').strip()
					country = (row.get('iso_country') or '').strip()
					atype = (row.get('type') or '').strip()
					# filter reasonable airports and ident format (3-10 alnum)
					if atype not in ('large_airport', 'medium_airport', 'small_airport'):
						continue
					if not ident or not re.fullmatch(r'[A-Z0-9]{3,10}', ident):
						continue
					rows.append({ 'ident': ident, 'iata': iata, 'name': name, 'city': city, 'country': country })
				_airports_cache['rows'] = rows
				_airports_cache['loaded'] = True
				_airports_cache['ts'] = time.time()
				logging.info("Loaded %d airports for suggestions", len(rows))
			except Exception as e:
				logging.warning("Failed loading airports dataset: %s", e)
				# provide minimal fallback
				_airports_cache['rows'] = [
					{ 'ident': 'LIMC', 'iata': 'MXP', 'name': 'Milano Malpensa', 'city': 'Milan', 'country': 'IT' },
					{ 'ident': 'LIRF', 'iata': 'FCO', 'name': 'Roma Fiumicino', 'city': 'Rome', 'country': 'IT' },
					{ 'ident': 'EGLL', 'iata': 'LHR', 'name': 'London Heathrow', 'city': 'London', 'country': 'GB' },
				]
				_airports_cache['loaded'] = True
				_airports_cache['ts'] = time.time()

	@app.get('/api/airport_suggest')
	def api_airport_suggest():
		q = (request.args.get('q') or '').strip()
		if not _airports_cache['loaded']:
			_load_airports_if_needed()
		if not q:
			return jsonify({ 'items': [] })
		q_up = q.upper()
		items = []
		for row in _airports_cache['rows']:
			ident = row['ident']
			iata = row['iata']
			name = row['name']
			city = row['city']
			country = row['country']
			if ident.startswith(q_up) or (iata and iata.startswith(q_up)) or (q.lower() in name.lower()):
				items.append({ 'ident': ident, 'iata': iata, 'name': name, 'city': city, 'country': country })
				if len(items) >= 10:
					break
		return jsonify({ 'items': items })

	@app.get('/data_test')
	def data_test_page():
		# Serve relocated HTML tester
		resp = send_from_directory(os.path.dirname(__file__), 'data_test.html')
		resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
		resp.headers['Pragma'] = 'no-cache'
		resp.headers['Expires'] = '0'
		return resp

	# Run REST in its own thread so gRPC can also run (optional)
	http_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8082), daemon=True)
	http_thread.start()

	# Start gRPC server (blocking)
	serve()
