import os
import time
import logging
from concurrent import futures

import grpc
import mysql.connector
from flask import Flask, request, jsonify
import bcrypt

import UserService_pb2 as pb2
import UserService_pb2_grpc as pb2_grpc


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


def wait_for_db(max_wait_seconds: int = 60):
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


class UserService(pb2_grpc.UserServiceServicer):
	def AddUser(self, request, context):
		username = (getattr(request, "username", "") or "").strip()
		password = getattr(request, "password", "") or ""
		email = (getattr(request, "email", "") or "").strip() or username

		if not email or not password:
			return pb2.userResponse(status=400, message="email and password required")
		pwd_hash = hash_password(password)

		try:
			conn = get_connection()
			cur = conn.cursor()
			cur.execute("SELECT email FROM users WHERE email=%s", (email,))
			if cur.fetchone():
				cur.close()
				conn.close()
				return pb2.userResponse(status=409, message="user already exists")

			cur.execute(
				"""
				INSERT INTO users (email, username, password, iban, codice_fiscale)
				VALUES (%s, %s, %s, %s, %s)
				""",
				(email, username or email, pwd_hash, None, None),
			)
			conn.commit()
			cur.close()
			conn.close()
			return pb2.userResponse(status=201, message="user created")
		except Exception as e:
			logging.exception("AddUser failed")
			return pb2.userResponse(status=500, message=str(e))

	def DeleteUser(self, request, context):
		username = (getattr(request, "username", "") or "").strip()
		email = (getattr(request, "email", "") or "").strip() or username
		if not email:
			return pb2.userResponse(status=400, message="email required")
		try:
			conn = get_connection()
			cur = conn.cursor()
			cur.execute("DELETE FROM users WHERE email=%s", (email,))
			affected = cur.rowcount
			conn.commit()
			cur.close()
			conn.close()
			if affected == 0:
				return pb2.userResponse(status=404, message="user not found")
			return pb2.userResponse(status=200, message="user deleted")
		except Exception as e:
			logging.exception("DeleteUser failed")
			return pb2.userResponse(status=500, message=str(e))

	def LoginUser(self, request, context):
		username = (getattr(request, "username", "") or "").strip()
		password = getattr(request, "password", "") or ""
		email = (getattr(request, "email", "") or "").strip() or username
		if not email or not password:
			return pb2.userResponse(status=400, message="email and password required")
		try:
			conn = get_connection()
			cur = conn.cursor()
			cur.execute("SELECT password FROM users WHERE email=%s", (email,))
			row = cur.fetchone()
			cur.close()
			conn.close()
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


@app.post("/add")
def http_add():
	data = request.get_json(silent=True) or {}
	username = (data.get("username") or "").strip()
	password = data.get("password") or ""
	email = (data.get("email") or "").strip()
	class _Req:
		pass
	req = _Req()
	req.username = username
	req.password = password
	req.email = email
	res = UserService().AddUser(req, None)
	return jsonify({"status": res.status, "message": res.message}), (res.status if res.status not in (201,) else 201)


@app.post("/delete")
def http_delete():
	data = request.get_json(silent=True) or {}
	username = (data.get("username") or "").strip()
	email = (data.get("email") or "").strip()
	class _Req:
		pass
	req = _Req()
	req.username = username
	req.email = email
	res = UserService().DeleteUser(req, None)
	return jsonify({"status": res.status, "message": res.message}), (200 if res.status == 200 else 404 if res.status == 404 else 400 if res.status == 400 else 500)


@app.post("/login") 
def http_login():
	data = request.get_json(silent=True) or {}
	username = (data.get("username") or "").strip()
	password = data.get("password") or ""
	email = (data.get("email") or "").strip()
	class _Req:
		pass
	req = _Req()
	req.username = username
	req.password = password
	req.email = email
	res = UserService().LoginUser(req, None)
	return jsonify({"status": res.status, "message": res.message}), (200 if res.status == 200 else 401 if res.status == 401 else 400 if res.status == 400 else 500)


def serve_http():
	app.run(host="0.0.0.0", port=HTTP_PORT)


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

