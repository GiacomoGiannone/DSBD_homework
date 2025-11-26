import os
import time
import logging
import types
from concurrent import futures

import grpc
import mysql.connector
from flask import Flask, request, jsonify, send_from_directory
import bcrypt

import UserService_pb2 as pb2
import UserService_pb2_grpc as pb2_grpc
import hashlib


DB_CONFIG = {
	"host": os.getenv("DB_HOST", "localhost"),
	"port": int(os.getenv("DB_PORT", "3306")),
	"database": os.getenv("DB_NAME", "userdb"),
	"user": os.getenv("DB_USER", "root"),
	"password": os.getenv("DB_PASSWORD", "root"),
}

GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))
HTTP_PORT = int(os.getenv("HTTP_PORT", "8081"))


def get_connection():
	return mysql.connector.connect(**DB_CONFIG)

def close_connection(conn, cur):
	try:
		cur.close()
	except Exception as e:
		logging.warning("Failed to close cursor: %s", e)
	try:
		conn.close()
	except Exception as e:
		logging.warning("Failed to close connection: %s", e)

def close_connection_with_rollback(conn, cur):
	try:
		conn.rollback()
	except Exception as e:
		logging.warning("Failed to rollback connection: %s", e)
	close_connection(conn, cur)

def wait_for_db(max_wait_seconds: int = 5):
	deadline = time.time() + max_wait_seconds
	last_err = None
	while time.time() < deadline:
		try:
			conn = get_connection()
			conn.close()
			return
		except Exception as e:
			last_err = e
			time.sleep(1)
	raise RuntimeError(f"DB not ready after {max_wait_seconds}s: {last_err}")

def hash_password(plain: str) -> str:
	salt = bcrypt.gensalt(rounds=12)
	hashed = bcrypt.hashpw(plain.encode("utf-8"), salt)
	return hashed.decode("utf-8")

def verify_password(plain: str, stored_hash: str) -> bool:
	try:
		return bcrypt.checkpw(plain.encode("utf-8"), stored_hash.encode("utf-8"))
	except Exception:
		return False
	
def get_request_attributes(request):
	username = (getattr(request, "username", "") or "").strip()
	password = getattr(request, "password", "") or ""
	email = (getattr(request, "email", "") or "").strip()
	operation = (getattr(request, "operation", "") or "").strip()
	return username, password, email, operation

def compute_request_id(email: str, username: str, operation: str, ts_iso: str) -> str:
    raw = f"{email}|{username}|{operation}|{ts_iso}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

class UserService(pb2_grpc.UserServiceServicer):
	def AddUser(self, request, context):
		username, password, email, operation = get_request_attributes(request)
		# Require all fields (server will generate request_id from hash)
		if not email or not username or not password:
			return pb2.userResponse(status=400, message="email, username and password are required")
		# Operation is optional here; default to AddUser if missing
		if not operation:
			operation = 'AddUser'
		pwd_hash = hash_password(password)

		try:
			conn = get_connection() 
			cur = conn.cursor()
			# Generate ts and request_id; then insert into request_log
			ts_iso = time.strftime("%Y-%m-%d %H:%M:%S")
			request_id = compute_request_id(email, username, operation, ts_iso)
			# We'll insert initial log with a placeholder message; then update it after successful op
			try:
				cur.execute("INSERT INTO request_log (request_id, operation, ts, message, status_code) VALUES (%s,%s,%s,%s,%s)", (request_id, operation, ts_iso, "processing", None))
			except Exception as e:
				error_no = getattr(e, 'errno', None)
				logging.error(f"request_log insert error - errno={error_no}, type={type(e).__name__}, msg={str(e)}")
				if error_no in (1062,):  # MySQL duplicate key
					# Fetch and return the original message
					try:
						cur.execute("SELECT message, status_code FROM request_log WHERE request_id=%s", (request_id,))
						row = cur.fetchone()
						msg = row[0] if row and row[0] else "Request already processed"
						status = row[1] if row and row[1] is not None else (200 if msg == "user created" else 401)
					except Exception:
						msg = "Request already processed"; status = 401
					close_connection(conn, cur)
					return pb2.userResponse(status=status, message=msg)
				logging.exception("request_log insert failed")
				close_connection(conn, cur)
				return pb2.userResponse(status=500, message=f"request_log error: {str(e)}")

			# Email uniqueness
			cur.execute("SELECT 1 FROM users WHERE email=%s", (email,))
			if cur.fetchone() is not None:
				try:
					cur.execute("UPDATE request_log SET message=%s, status_code=%s WHERE request_id=%s", ("user already exists", 409, request_id))
				except Exception:
					pass
				close_connection_with_rollback(conn, cur)
				return pb2.userResponse(status=409, message="user already exists")
			cur.execute("SELECT 1 FROM users WHERE username=%s", (username,))
			if cur.fetchone() is not None:
				try:
					cur.execute("UPDATE request_log SET message=%s, status_code=%s WHERE request_id=%s", ("username already exists", 409, request_id))
				except Exception:
					pass
				close_connection_with_rollback(conn, cur)
				return pb2.userResponse(status=409, message="username already exists")

			cur.execute(
				"""
				INSERT INTO users (email, username, password)
				VALUES (%s, %s, %s)
				""",
				(email, username, pwd_hash),
			)
			# Update log message to final outcome
			try:
				cur.execute("UPDATE request_log SET message=%s, status_code=%s WHERE request_id=%s", ("user created", 201, request_id))
			except Exception:
				pass
			conn.commit() 
			close_connection(conn, cur)
			return pb2.userResponse(status=201, message="user created")
		except Exception as e:
			try:
				conn.rollback()
			except Exception:
				pass
			logging.exception("AddUser failed")
			return pb2.userResponse(status=500, message=str(e))

	def DeleteUser(self, request, context):
		username, password, email, operation = get_request_attributes(request)
		if ((not email and not username) or not password):
			return pb2.userResponse(status=400, message="(email or username) and password required")
		if not operation:
			operation = 'DeleteUser'
		try:
			conn = get_connection() 
			cur = conn.cursor()
			# Insert generated request_id; if duplicate we skip all
			ts_iso = time.strftime("%Y-%m-%d %H:%M:%S")
			request_id = compute_request_id(email, username, operation, ts_iso)
			try:
				cur.execute("INSERT INTO request_log (request_id, operation, ts, message, status_code) VALUES (%s,%s,%s,%s,%s)", (request_id, operation, ts_iso, "processing", None))
			except Exception as e:
				if getattr(e, 'errno', None) in (1062,):
					# Fetch and return the original message
					try:
						cur.execute("SELECT message, status_code FROM request_log WHERE request_id=%s", (request_id,))
						row = cur.fetchone()
						msg = row[0] if row and row[0] else "already processed"
						status = row[1] if row and row[1] is not None else 200
					except Exception:
						msg = "already processed"; status = 200
					close_connection(conn, cur)
					return pb2.userResponse(status=status, message=msg)
				logging.exception("request_log insert failed")
				close_connection(conn, cur)
				return pb2.userResponse(status=500, message="request_log error")

			# Resolve identity
			row = None 
			resolved_email = None
			if email:
				cur.execute("SELECT email, password FROM users WHERE email=%s", (email,))
				row = cur.fetchone() 
				resolved_email = email if row else None
			else:
				cur.execute("SELECT email, password FROM users WHERE username=%s", (username,))
				rows = cur.fetchall()
				if len(rows) == 0:
					close_connection_with_rollback(conn, cur)
					return pb2.userResponse(status=404, message="user not found")
				if len(rows) > 1:
					close_connection_with_rollback(conn, cur)
					return pb2.userResponse(status=409, message="username not unique")
				resolved_email, stored_hash = rows[0][0], rows[0][1] if len(rows[0]) > 1 else None
				row = (resolved_email, stored_hash)

			if not row:
				close_connection_with_rollback(conn, cur)
				return pb2.userResponse(status=404, message="user not found")
			stored_hash = row[1]
			if not verify_password(password, stored_hash):
				close_connection_with_rollback(conn, cur)
				return pb2.userResponse(status=401, message="invalid credentials")

			cur.execute("DELETE FROM users WHERE email=%s", (resolved_email,))
			affected = cur.rowcount
			# Update log message to final outcome
			try:
				cur.execute("UPDATE request_log SET message=%s, status_code=%s WHERE request_id=%s", ("user deleted", 200, request_id))
			except Exception:
				pass
			conn.commit()
			close_connection(conn, cur)
			if affected == 0:
				return pb2.userResponse(status=404, message="user not found")
			return pb2.userResponse(status=200, message="user deleted")
		except Exception as e:
			try:
				conn.rollback()
			except Exception:
				pass
			logging.exception("DeleteUser failed")
			return pb2.userResponse(status=500, message=str(e))

	def LoginUser(self, request, context):
		_, username, password, email = get_request_attributes(request)
		if (not email and not username) or not password:
			return pb2.userResponse(status=400, message="email or username and password required")
		try:
			conn = get_connection()
			cur = conn.cursor()
			row = None
			if email:
				cur.execute("SELECT password FROM users WHERE email=%s", (email,))
				row = cur.fetchone()
			else:
				cur.execute("SELECT password FROM users WHERE username=%s", (username,))
				rows = cur.fetchall()
				if len(rows) > 1:
					close_connection(conn, cur)
					return pb2.userResponse(status=409, message="username not unique")
				row = rows[0] if rows else None
			close_connection(conn, cur)
			if not row:
				return pb2.userResponse(status=401, message="invalid credentials")
			stored_hash = row[0]
			if verify_password(password, stored_hash):
				return pb2.userResponse(status=200, message="login ok")
			return pb2.userResponse(status=401, message="invalid credentials")
		except Exception as e:
			logging.exception("LoginUser failed")
			return pb2.userResponse(status=500, message=str(e))


def serve_grpc():
	server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
	pb2_grpc.add_UserServiceServicer_to_server(UserService(), server)
	server.add_insecure_port(f"[::]:{GRPC_PORT}")
	server.start()
	server.wait_for_termination()


app = Flask(__name__)
# Disable static file caching for dev so updated HTML is always served
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0


def _get_request_data():
	"""Extract and sanitize JSON request data."""
	return request.get_json(silent=True) or {}


@app.post("/add")
def http_add():
	data = _get_request_data()
	req = types.SimpleNamespace(
		username=(data.get("username") or "").strip(),
		password=data.get("password") or "",
		email=(data.get("email") or "").strip(),
		operation=(data.get("operation") or "AddUser").strip()
	)
	res = UserService().AddUser(req, None)
	http_status = 201 if res.status == 201 else res.status
	return jsonify({"status": res.status, "message": res.message}), http_status


@app.post("/delete")
def http_delete():
	data = _get_request_data()
	identity = (data.get("identity") or "").strip()
	email = identity if "@" in identity else ""
	username = identity if "@" not in identity else ""
	req = types.SimpleNamespace(
		username=username,
		email=email,
		password=data.get("password") or "",
		operation=(data.get("operation") or "DeleteUser").strip()
	)
	res = UserService().DeleteUser(req, None)
	http_status = res.status if res.status in (200, 400, 401, 404, 409) else 500
	return jsonify({"status": res.status, "message": res.message}), http_status


@app.post("/login") 
def http_login():
	data = _get_request_data()
	identity = (data.get("identity") or "").strip()
	email = identity if "@" in identity else ""
	username = identity if "@" not in identity else ""
	req = types.SimpleNamespace(
		username=username,
		password=data.get("password") or "",
		email=email
	)
	res = UserService().LoginUser(req, None)
	body = {"status": res.status, "message": res.message}
	
	# If login ok, resolve canonical email for redirect to data_test
	if res.status == 200 and not email:
		try:
			conn = get_connection(); cur = conn.cursor()
			cur.execute("SELECT email FROM users WHERE username=%s", (username,))
			row = cur.fetchone()
			close_connection(conn, cur)
			if row:
				body["email"] = row[0]
		except Exception:
			pass
	elif res.status == 200:
		body["email"] = email
	
	http_status = res.status if res.status in (200, 400, 401) else 500
	return jsonify(body), http_status


def serve_http():
	app.run(host="0.0.0.0", port=HTTP_PORT)


# Serve the local HTML tester to avoid CORS issues
@app.get("/")
def serve_test_page():
	resp = send_from_directory(os.path.dirname(__file__), "user_test.html")
	cache_headers = {
		'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
		'Pragma': 'no-cache',
		'Expires': '0'
	}
	for key, val in cache_headers.items():
		resp.headers[key] = val
	return resp


@app.get("/data_test")
def serve_data_page():
	# Page moved to DataCollector service; keep backwards compatibility by redirect hint
	return jsonify({"moved": True, "location": "http://localhost:8082/data_test"}), 301


if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
	try:
		wait_for_db(120)
	except Exception as e:
		logging.error("DB not ready: %s", e)
		raise

	from threading import Thread

	http_thread = Thread(target=serve_http, daemon=True)
	http_thread.start()

	serve_grpc()

