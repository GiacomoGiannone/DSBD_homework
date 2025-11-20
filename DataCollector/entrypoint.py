#!/usr/bin/env python3
"""
Portable Python entrypoint for DataCollector container.
- If mounted, processes /credentials/credentials.json with upload_credentials.py
- Loads /app/.env into environment (if created) so the server inherits vars
- If OAuth credentials present, generates OPEN_SKY_TOKEN and exports it
- Replaces process with data_collector.py
"""
import os
import sys
import subprocess
import shlex
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def run_uploader(cred_path, env_path):
    # Use same Python interpreter
    cmd = [sys.executable, os.path.join('/app', 'upload_credentials.py'), '--file', cred_path, '--env', env_path]
    try:
        logging.info('Running uploader: %s', ' '.join(shlex.quote(p) for p in cmd))
        # Do not raise on non-zero; uploader logs errors
        subprocess.run(cmd, check=False)
    except Exception as e:
        logging.warning('Uploader execution failed: %s', e)


def load_env_file(env_path):
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                # preserve existing env values only if not set (do not override host)
                os.environ.setdefault(k.strip(), v.strip())
        logging.info('Loaded env vars from %s', env_path)
    except Exception as e:
        logging.warning('Failed loading env file %s: %s', env_path, e)


def generate_opensky_token(client_id, client_secret):
    """Generate OpenSky OAuth token from credentials."""
    if not client_id or not client_secret:
        return None
    try:
        import requests
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
                logging.info(f"Generated OpenSky OAuth token (expires in {expires_in}s)")
                return access_token
        else:
            logging.warning(f"OpenSky token response failed: {response.status_code}")
    except Exception as e:
        logging.warning(f"Failed to generate OpenSky token: {e}")
    return None


def main():
    CRED_PATH = '/credentials/credentials.json'
    ENV_PATH = '/app/.env'

    # If credentials file is mounted, process it
    if os.path.exists(CRED_PATH):
        logging.info('Found credentials at %s — running uploader', CRED_PATH)
        run_uploader(CRED_PATH, ENV_PATH)
    else:
        logging.info('No credentials file mounted at %s', CRED_PATH)

    # Load any env file produced by uploader
    if os.path.exists(ENV_PATH):
        logging.info('Sourcing %s into environment', ENV_PATH)
        load_env_file(ENV_PATH)

    # Try to generate OpenSky OAuth token if client credentials are available
    # Support both snake_case (OPEN_SKY_CLIENT_ID) and camelCase (set by upload_credentials)
    client_id = os.environ.get("OPEN_SKY_CLIENT_ID", "") or os.environ.get("OPENSKY_CLIENT_ID", "")
    client_secret = os.environ.get("OPEN_SKY_CLIENT_SECRET", "") or os.environ.get("OPENSKY_CLIENT_SECRET", "")
    existing_token = os.environ.get("OPEN_SKY_TOKEN", "") or os.environ.get("OPENSKY_TOKEN", "")
    
    if not existing_token and client_id and client_secret:
        logging.info("Attempting to generate OpenSky OAuth token from client credentials...")
        token = generate_opensky_token(client_id, client_secret)
        if token:
            os.environ["OPEN_SKY_TOKEN"] = token
            logging.info("OpenSky token set in environment")
    elif existing_token:
        logging.info("OpenSky token already available in environment")
    else:
        logging.warning("No OpenSky credentials available (OAuth or basic auth)")

    # Exec the main process (replace this process)
    target = os.path.join('/app', 'data_collector.py')
    if not os.path.exists(target):
        logging.error('Main script not found: %s', target)
        sys.exit(3)

    logging.info('Starting %s', target)
    os.execvp(sys.executable, [sys.executable, target])


if __name__ == '__main__':
    main()
