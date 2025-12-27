import os
import json
import logging
import smtplib
from email.mime.text import MIMEText
from confluent_kafka import Consumer
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

KAFKA_BROKER = os.getenv('KAFKA_BROKER', 'kafka:29092')
TOPIC_IN = os.getenv('KAFKA_TOPIC_IN', 'to-notifier')
GROUP_ID = os.getenv('KAFKA_GROUP_ID', 'alert-notifier-group')

SMTP_HOST = os.getenv('SMTP_HOST', '')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASS = os.getenv('SMTP_PASS', '')
SMTP_FROM = os.getenv('SMTP_FROM', SMTP_USER or 'notifier@example.com')
DISABLE_EMAIL = os.getenv('DISABLE_EMAIL', 'false').lower() == 'true'

app = FastAPI()


def send_email(to_addr: str, subject: str, body: str) -> bool:
    # Fallback to mock if disabled or SMTP not configured
    if DISABLE_EMAIL or not SMTP_HOST:
        if not SMTP_HOST and not DISABLE_EMAIL:
            logging.warning("SMTP not configured, falling back to mock send")
        logging.info("[EMAIL MOCK] to=%s subject=%s body=%s", to_addr, subject, body)
        return True
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_FROM
        msg['To'] = to_addr
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASS)
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
