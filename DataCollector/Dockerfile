# Dockerfile per Data Collector
FROM python:3.12-slim

WORKDIR /app

# Copia requirements e installazione
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutto il codice
COPY . .

# Esponi la porta REST
EXPOSE 8082

# Comando per partire con il server
CMD ["python", "data_collector.py"]