#!/usr/bin/env python3
"""
Load credentials from JSON and write environment variables to .env file.
Supports multiple JSON key formats (camelCase, snake_case, uppercase).
"""
import os
import sys
import json
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_json(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def read_env(path: str):
    data = {}
    if not os.path.exists(path):
        return data
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            data[k.strip()] = v.strip()
    return data


def write_env(path: str, data: dict):
    """Write env variables to file, sorted by key."""
    lines = []
    for k in sorted(data.keys()):
        lines.append(f"{k}={data[k]}")
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def normalize_keys(d: dict):
    """Normalize all keys to uppercase for matching."""
    out = {}
    for k, v in d.items():
        if not isinstance(k, str):
            continue
        out[k.strip().upper()] = v
    return out


def main():
    parser = argparse.ArgumentParser(description='Load credentials from JSON and persist to .env')
    parser.add_argument('--file', '-f', help='Path to credentials JSON (default: ./credentials.json)',
                       default=os.path.join(os.path.dirname(__file__), 'credentials.json'))
    parser.add_argument('--env', '-e', help='Path to .env to write (default: ./DataCollector/.env)',
                       default=os.path.join(os.path.dirname(__file__), '.env'))
    args = parser.parse_args()

    json_path = os.path.abspath(args.file)
    env_path = os.path.abspath(args.env)

    if not os.path.exists(json_path):
        logging.error('Credentials file not found: %s', json_path)
        sys.exit(2)

    try:
        raw = load_json(json_path)
    except Exception as e:
        logging.exception('Failed to parse JSON %s: %s', json_path, e)
        sys.exit(3)

    norm = normalize_keys(raw)

    # Map various credential key formats to standardized env var names
    to_set = {}

    # OpenSky OAuth Client Credentials (priority: clientId/clientSecret > open_sky_client_id/secret)
    if 'CLIENTID' in norm:
        to_set['OPEN_SKY_CLIENT_ID'] = str(norm['CLIENTID'])
    elif 'CLIENT_ID' in norm:
        to_set['OPEN_SKY_CLIENT_ID'] = str(norm['CLIENT_ID'])
    elif 'OPEN_SKY_CLIENT_ID' in norm:
        to_set['OPEN_SKY_CLIENT_ID'] = str(norm['OPEN_SKY_CLIENT_ID'])

    if 'CLIENTSECRET' in norm:
        to_set['OPEN_SKY_CLIENT_SECRET'] = str(norm['CLIENTSECRET'])
    elif 'CLIENT_SECRET' in norm:
        to_set['OPEN_SKY_CLIENT_SECRET'] = str(norm['CLIENT_SECRET'])
    elif 'OPEN_SKY_CLIENT_SECRET' in norm:
        to_set['OPEN_SKY_CLIENT_SECRET'] = str(norm['OPEN_SKY_CLIENT_SECRET'])

    # OpenSky Basic Auth (legacy)
    if 'OPENSKY_USER' in norm or 'USER' in norm:
        to_set['OPENSKY_USER'] = str(norm.get('OPENSKY_USER') or norm.get('USER', ''))

    if 'OPENSKY_PASS' in norm or 'PASSWORD' in norm:
        to_set['OPENSKY_PASS'] = str(norm.get('OPENSKY_PASS') or norm.get('PASSWORD', ''))

    # Direct token if provided
    if 'OPEN_SKY_TOKEN' in norm:
        to_set['OPEN_SKY_TOKEN'] = str(norm['OPEN_SKY_TOKEN'])
    elif 'TOKEN' in norm and norm.get('TOKEN'):
        to_set['OPEN_SKY_TOKEN'] = str(norm.get('TOKEN'))

    if not to_set:
        logging.error('No credential keys found in %s. Expected at least one of: clientId/clientSecret, opensky_user/pass, or token.', json_path)
        sys.exit(4)

    # Load existing .env and merge
    existing = read_env(env_path)
    for k, v in to_set.items():
        logging.info('Setting %s from credentials', k)
        existing[k] = v

    try:
        write_env(env_path, existing)
        logging.info('Credentials persisted to %s', env_path)
    except Exception as e:
        logging.exception('Failed to write env file %s: %s', env_path, e)
        sys.exit(5)


if __name__ == '__main__':
    main()
