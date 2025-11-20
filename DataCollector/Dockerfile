# Dockerfile per Data Collector
FROM python:3.12-slim

WORKDIR /app

# Copia requirements e installazione
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutto il codice
COPY . .

# Genera gli stub gRPC dal proto
RUN python -m grpc_tools.protoc -I. \
	--python_out=. \
	--grpc_python_out=. \
	DataCollector.proto

# Esponi la porta REST
EXPOSE 8082

# Entrypoint: run Python uploader if credentials.json provided, then start service
ENTRYPOINT ["python", "/app/entrypoint.py"]

# Fallback command (kept for clarity)
CMD ["python", "data_collector.py"]