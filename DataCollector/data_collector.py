import os
import time
import logging
import threading
from concurrent import futures
import requests
import mysql.connector
import grpc
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
import csv
from io import StringIO

import DataCollector_pb2 as pb2
import DataCollector_pb2_grpc as pb2_grpc

DATA_DB = {
	"host": os.getenv("DATA_DB_HOST", "datadb"),
	"port": int(os.getenv("DATA_DB_PORT", "3306")),
	"database": os.getenv("DATA_DB_NAME", "datadb"),
	"user": os.getenv("DATA_DB_USER", "root"),
	"password": os.getenv("DATA_DB_PASSWORD", "root"),
}

OPEN_SKY_USER = os.getenv("OPENSKY_USER", "")
OPEN_SKY_PASS = os.getenv("OPENSKY_PASS", "")
OPEN_SKY_TOKEN = os.getenv("OPEN_SKY_TOKEN", "")
AIRPORTS_SOURCE_URL = os.getenv("AIRPORTS_SOURCE_URL", "https://raw.githubusercontent.com/davidmegginson/ourairports-data/master/airports.csv")

REFRESH_INTERVAL_SECONDS = int(os.getenv("REFRESH_INTERVAL_SECONDS", "43200"))  # 12 hours default
GRPC_PORT = int(os.getenv("DATACOLLECTOR_GRPC_PORT", "50052"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def get_data_conn():
	return mysql.connector.connect(**DATA_DB)

def close_connection(conn, cur):
	try:
		cur.close()
	except Exception as e:
		logging.warning("Failed to close cursor: %s", e)
	try:
		conn.close()
	except Exception as e:
		logging.warning("Failed to close connection: %s", e)

def commit_and_close(conn, cur):
	try:
		conn.commit()
	except Exception as e:
		logging.warning("Failed to commit transaction: %s", e)
	close_connection(conn, cur)

def fetch_airports_for_email(email: str):
	conn = get_data_conn()
	cur = conn.cursor()
	cur.execute("SELECT airport_code FROM interests WHERE email=%s", (email,))
	rows = [r[0] for r in cur.fetchall()]
	close_connection(conn, cur)
	return rows

def fetch_all_airports():
	conn = get_data_conn()
	cur = conn.cursor()
	cur.execute("SELECT DISTINCT airport_code FROM interests")
	rows = [r[0] for r in cur.fetchall()]
	close_connection(conn, cur)
	return rows

def get_average_flights_for_airport(airport_code, days=7):
    """
    Compute the average number of daily flights for a specific airport over the past X days
    """
    conn = get_data_conn()
    cur = conn.cursor()
    
    # Calculate the timestamp for X days ago
    x_days_ago = int(time.time()) - (days * 24 * 3600)
    current_time = int(time.time())
    
    # ADD DEBUG LOGGING
    logging.info(f"🔍 Calculating average for {airport_code} over past {days} days")
    logging.info(f"   Time range: {x_days_ago} to {current_time}")
    logging.info(f"   Human readable: {datetime.fromtimestamp(x_days_ago)} to {datetime.fromtimestamp(current_time)}")
    
    cur.execute("""
        SELECT 
            DATE(FROM_UNIXTIME(departure_time)) AS flight_date, 
            COUNT(*) AS flight_count
        FROM flights 
        WHERE (departure_airport = %s OR arrival_airport = %s)
          AND departure_time >= %s
        GROUP BY flight_date
        ORDER BY flight_date DESC
    """, (airport_code, airport_code, x_days_ago))
    
    rows = cur.fetchall()
    close_connection(conn, cur)
    
    # ADD MORE DEBUG LOGGING
    logging.info(f"   Found {len(rows)} days with data for {airport_code}")
    for row in rows[:3]:  # Show first 3 days
        logging.info(f"      {row[0]}: {row[1]} flights")
    if len(rows) > 3:
        logging.info(f"      ... and {len(rows) - 3} more days")
    
    if not rows:
        logging.info(f"   ❌ No data found for {airport_code}")
        return 0.0
    
    # Calculate average
    total_flights = sum(row[1] for row in rows)
    average = total_flights / len(rows)
    
    logging.info(f"   📊 Total flights: {total_flights}, Days: {len(rows)}, Average: {average}")
    
    return round(average, 2)

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
	begin = int(time.time()) - 12*3600 #past 7 days
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
					(d.get('icao24'), d.get('callsign'), code, d.get('estArrivalAirport'), d.get('firstSeen'), d.get('lastSeen'))
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
					(a.get('icao24'), a.get('callsign'), a.get('estDepartureAirport'), code, a.get('firstSeen'), a.get('lastSeen'))
				)
				count += 1
			except Exception as e:
				logging.debug("Skip arrival %s: %s", a, e)
	commit_and_close(conn, cur)
	return count


class DataCollectorService(pb2_grpc.DataCollectorServiceServicer):
	def AddAirport(self, request, context):
		email = (request.email or '').strip()
		code = (request.code or '').strip().upper()
		if not email or not code:
			return pb2.GenericResponse(status=400, message='email and code required')
		try:
			conn = get_data_conn()
			cur = conn.cursor()
			cur.execute("SELECT 1 FROM interests WHERE email=%s AND airport_code=%s", (email, code))
			if cur.fetchone():
				close_connection(conn, cur)
				return pb2.GenericResponse(status=409, message='already exists')
			cur.execute("INSERT INTO interests (email, airport_code) VALUES (%s,%s)", (email, code))
			commit_and_close(conn, cur)
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
			conn = get_data_conn()
			cur = conn.cursor()
			cur.execute("DELETE FROM interests WHERE email=%s AND airport_code=%s", (email, code))
			affected = cur.rowcount
			commit_and_close(conn, cur)
			# Optional: purge flights for this airport if no other user is interested
			if affected == 0:
				return pb2.GenericResponse(status=404, message='not found')
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
		conn = get_data_conn()
		cur = conn.cursor()
		if airport_filter:
			cur.execute("SELECT icao24,callsign,departure_airport,arrival_airport,departure_time,arrival_time,flight_type FROM flights WHERE departure_airport=%s OR arrival_airport=%s ORDER BY last_refresh DESC LIMIT 500", (airport_filter, airport_filter))
		else:
			if not airports:
				close_connection(conn, cur)
				return pb2.FlightsResponse(flights=[])
			placeholders = ','.join(['%s']*len(airports))
			sql = f"SELECT icao24,callsign,departure_airport,arrival_airport,departure_time,arrival_time,flight_type FROM flights WHERE departure_airport IN ({placeholders}) OR arrival_airport IN ({placeholders}) ORDER BY last_refresh DESC LIMIT 500"
			cur.execute(sql, airports+airports)
		rows = cur.fetchall()
		close_connection(conn, cur)
		flights = [pb2.Flight(icao24=r[0] or '', callsign=r[1] or '', departure_airport=r[2] or '', arrival_airport=r[3] or '', departure_time=r[4] or 0, arrival_time=r[5] or 0, flight_type=r[6] or '') for r in rows]
		return pb2.FlightsResponse(flights=flights)

	def AverageFlightsPerDay(self, request, context):
		days = request.days if request.days > 0 else 7
		email = (request.email or '').strip()
		airports = fetch_airports_for_email(email) if email else fetch_all_airports()
		if not airports:
			return pb2.DaysRespone(average=0)
		total_avg = 0.0
		for code in airports:
			avg = get_average_flights_for_airport(code, days)
			total_avg += avg
		overall_avg = round(total_avg / len(airports), 2) if airports else 0.0
		return pb2.DaysRespone(average=overall_avg)

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

	# -------------------------------
	# Airport suggestions (autocomplete)
	# -------------------------------
	_AIRPORT_CACHE = {"ts": 0, "items": []}

	def _load_airports_index(force=False):
		now = time.time()
		if not force and _AIRPORT_CACHE["items"] and (now - _AIRPORT_CACHE["ts"]) < REFRESH_INTERVAL_SECONDS:
			return _AIRPORT_CACHE["items"]
		try:
			r = requests.get(AIRPORTS_SOURCE_URL, timeout=30)
			r.raise_for_status()
			text = r.text
			reader = csv.DictReader(StringIO(text))
			items = []
			for row in reader:
				name = (row.get('name') or '').strip()
				iata = (row.get('iata_code') or '').strip().upper()
				icao = (row.get('gps_code') or row.get('ident') or '').strip().upper()
				city = (row.get('municipality') or '').strip()
				country = (row.get('iso_country') or '').strip()
				if not (iata or icao):
					continue
				# Prefer ICAO as ident for our UI
				ident = icao or iata
				items.append({
					'ident': ident,
					'name': name,
					'iata': iata,
					'icao': icao,
					'city': city,
					'country': country,
				})
			# De-duplicate by ident keeping first occurrence
			seen = set()
			dedup = []
			for it in items:
				k = it['ident']
				if k in seen:
					continue
				seen.add(k)
				dedup.append(it)
			_AIRPORT_CACHE["items"] = dedup
			_AIRPORT_CACHE["ts"] = now
			return dedup
		except Exception as e:
			logging.warning("Failed to load airports index: %s", e)
			return _AIRPORT_CACHE["items"] or []

	def _suggest_airports(q: str, limit: int = 10):
		q = (q or '').strip().upper()
		if len(q) < 2:
			return []
		items = _load_airports_index()
		res = []
		for it in items:
			# Only ICAO prefix OR Name prefix matches (no substring matches)
			icao = (it.get('icao') or '').upper()
			name = (it.get('name') or '').upper()
			code_hits = icao.startswith(q)
			name_hit = name.startswith(q)
			if code_hits or name_hit:
				res.append(it)
				if len(res) >= limit:
					break
		return res

	@app.get('/api/airport_suggest')
	def api_airport_suggest():
		q = request.args.get('q', '').strip()
		items = _suggest_airports(q, limit=15)
		return jsonify({'items': items})

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
	
	@app.post('/api/average_flights_per_day')
	def api_average_flights_per_day():
		data = request.get_json(silent=True) or {}
		email = (data.get('email') or '').strip()
		days = int(data.get('days') or 7)
		svc = DataCollectorService()
		res = svc.AverageFlightsPerDay(type('Req', (), {'email': email, 'days': days})(), None)
		return jsonify({'average': res.average})

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

	#optional: airport suggestions API
	@app.post('/api/debug_data_range')
	def api_debug_data_range():
		"""Debug endpoint to check what data we actually have"""
		from datetime import datetime
		
		conn = get_data_conn()
		cur = conn.cursor()
		
		# Check overall date range
		cur.execute("""
			SELECT 
				MIN(departure_time) as earliest,
				MAX(departure_time) as latest,
				COUNT(*) as total_flights
			FROM flights
			WHERE departure_time IS NOT NULL
		""")
		
		overall = cur.fetchone()
		
		# Check recent data (last 7 days)
		seven_days_ago = int(time.time()) - (7 * 24 * 3600)
		cur.execute("""
			SELECT COUNT(*) as recent_flights
			FROM flights 
			WHERE departure_time >= %s
		""", (seven_days_ago,))
		
		recent = cur.fetchone()[0]
		
		# Check data by airport
		cur.execute("""
			SELECT departure_airport, COUNT(*) as count
			FROM flights 
			GROUP BY departure_airport
			ORDER BY count DESC
			LIMIT 10
		""")
		
		airports = cur.fetchall()
		
		close_connection(conn, cur)
		
		result = {
			'overall_date_range': {
				'earliest': datetime.fromtimestamp(overall[0]).isoformat() if overall[0] else None,
				'latest': datetime.fromtimestamp(overall[1]).isoformat() if overall[1] else None,
				'total_flights': overall[2]
			},
			'recent_data': {
				'last_7_days_flights': recent,
				'seven_days_ago_timestamp': seven_days_ago
			},
			'top_airports': [
				{'airport': airport[0], 'flights': airport[1]} for airport in airports
			]
		}
		
		return jsonify(result)

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
