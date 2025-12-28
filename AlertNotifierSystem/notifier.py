import os
import json
import logging
import smtplib
from email.mime.text import MIMEText
from confluent_kafka import Consumer
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

def _env(name: str, default: str = '') -> str:
    """Get env var and sanitize by stripping whitespace and quotes."""
    val = os.getenv(name, default) or ''
    return val.strip().strip('"').strip("'")

def _env_bool(name: str, default_true: bool = True) -> bool:
    raw = _env(name, 'true' if default_true else 'false').lower()
    return raw in ('true', '1', 'yes', 'y')

def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except Exception:
        return default

KAFKA_BROKER = _env('KAFKA_BROKER', 'kafka:29092')
TOPIC_IN = _env('KAFKA_TOPIC_IN', 'to-notifier')
GROUP_ID = _env('KAFKA_GROUP_ID', 'alert-notifier-group')

SMTP_HOST = _env('SMTP_HOST', '')
SMTP_PORT = _env_int('SMTP_PORT', 587)
SMTP_USER = _env('SMTP_USER', '')
SMTP_PASS = _env('SMTP_PASS', '')
SMTP_FROM = _env('SMTP_FROM', SMTP_USER or 'notifier@example.com')
# Default to disabling emails when env var is missing
DISABLE_EMAIL = _env_bool('DISABLE_EMAIL', default_true=True)

app = FastAPI()


def send_email(to_addr: str, subject: str, body: str) -> bool:
    # Fallback to mock if disabled or SMTP not configured
    if DISABLE_EMAIL or not SMTP_HOST:
        reason = []
        if DISABLE_EMAIL:
            reason.append('DISABLE_EMAIL=true')
        if not SMTP_HOST:
            reason.append('SMTP_HOST not set')
        logging.info("[EMAIL MOCK] (%s) to=%s subject=%s body=%s", ', '.join(reason), to_addr, subject, body)
        return True
    try:
        # Gmail app passwords are shown with spaces; remove spaces for Gmail hosts
        pass_for_login = SMTP_PASS.replace(' ', '') if 'gmail.com' in SMTP_HOST else SMTP_PASS
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM
        msg['To'] = to_addr
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, pass_for_login)
            server.send_message(msg)
        return True
    except Exception as e:
        logging.error("Email send failed: %s", e)
        return False


def run_consumer():
    conf = {
        'bootstrap.servers': KAFKA_BROKER,
        'group.id': GROUP_ID,
        'auto.offset.reset': 'latest',
        'enable.auto.commit': True,
    }
    consumer = Consumer(conf)
    consumer.subscribe([TOPIC_IN])
    logging.info('AlertNotifierSystem consuming from %s', TOPIC_IN)
    logging.info('Email config: disabled=%s host=%s port=%s user=%s from=%s', DISABLE_EMAIL, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_FROM)
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                logging.error('Consumer error: %s', msg.error())
                continue
            try:
                payload = json.loads(msg.value().decode('utf-8'))
                email = (payload.get('email') or '').strip()
                airport = (payload.get('airport') or '').strip()
                condition = (payload.get('condition') or '').strip()
                if not email or not airport or not condition:
                    continue
                subject = airport
                body = condition
                ok = send_email(email, subject, body)
                if ok:
                    logging.info('Email sent to %s for %s %s', email, airport, condition)
                else:
                    logging.warning('Email not sent to %s', email)
            except Exception as e:
                logging.exception('Failed to process notifier message: %s', e)
    except KeyboardInterrupt:
        logging.info('Shutting down notifier')
    finally:
        consumer.close()


@app.get('/')
async def health():
    return {'status': 'ok', 'email': 'disabled' if DISABLE_EMAIL else 'enabled'}


if __name__ == '__main__':
    run_consumer()
