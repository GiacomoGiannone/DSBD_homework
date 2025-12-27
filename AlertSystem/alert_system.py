import os
import json
import logging
import time
import mysql.connector
from confluent_kafka import Consumer, Producer

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# Env
KAFKA_BROKER = os.getenv('KAFKA_BROKER', 'kafka:29092')
TOPIC_IN = os.getenv('KAFKA_TOPIC_IN', 'to-alert-system')
TOPIC_OUT = os.getenv('KAFKA_TOPIC_OUT', 'to-notifier')
GROUP_ID = os.getenv('KAFKA_GROUP_ID', 'alert-system-group')

DATA_DB = {
    'host': os.getenv('DATA_DB_HOST', 'datadb'),
    'port': int(os.getenv('DATA_DB_PORT', '3306')),
    'database': os.getenv('DATA_DB_NAME', 'datadb'),
    'user': os.getenv('DATA_DB_USER', 'root'),
    'password': os.getenv('DATA_DB_PASSWORD', 'root'),
}


def get_db_conn():
    return mysql.connector.connect(**DATA_DB)


def fetch_interests_for_airport(airport_code: str):
    conn = get_db_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT email, high_value, low_value FROM interests WHERE airport_code=%s",
        (airport_code,)
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows


def build_condition(dep_count: int, arr_count: int, high_value, low_value):
    # Total flights for threshold comparison; adjust if you want separate checks
    total = dep_count + arr_count
    if high_value is not None and total > int(high_value):
        return 'ABOVE_HIGH'
    if low_value is not None and total < int(low_value):
        return 'BELOW_LOW'
    return None


def main():
    consumer_conf = {
        'bootstrap.servers': KAFKA_BROKER,
        'group.id': GROUP_ID,
        'auto.offset.reset': 'latest',
        'enable.auto.commit': True,
    }
    producer_conf = {
        'bootstrap.servers': KAFKA_BROKER,
        'acks': 'all',
        'linger.ms': 10,
        'max.in.flight.requests.per.connection': 5,
        'retries': 5,  
    }
    consumer = Consumer(consumer_conf)
    producer = Producer(producer_conf)

    consumer.subscribe([TOPIC_IN])
    logging.info('AlertSystem consuming from %s, producing to %s', TOPIC_IN, TOPIC_OUT)

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
                airport = payload.get('airport')
                dep = int(payload.get('departure_count') or 0)
                arr = int(payload.get('arrival_count') or 0)
                ts = int(payload.get('timestamp') or int(time.time()))
                if not airport:
                    continue
                # For each interested user, check thresholds
                rows = fetch_interests_for_airport(airport)
                for email, high_value, low_value in rows:
                    cond = build_condition(dep, arr, high_value, low_value)
                    if cond:
                        out = {
                            'email': email,
                            'airport': airport,
                            'condition': cond,
                            'departure_count': dep,
                            'arrival_count': arr,
                            'timestamp': ts,
                        }
                        producer.produce(
                            TOPIC_OUT,
                            json.dumps(out).encode('utf-8'),
                            key=email.encode('utf-8') if email else None
                        )
                        producer.poll(0)
                        logging.info('Emitted notifier for %s %s %s', email, airport, cond)
            except Exception as e:
                logging.exception('Failed to process message: %s', e)
    except KeyboardInterrupt:
        logging.info('Shutting down AlertSystem')
    finally:
        consumer.close()
        remaining = producer.flush(10)
        if remaining:
            logging.warning('%d messages not delivered', remaining)


if __name__ == '__main__':
    main()
