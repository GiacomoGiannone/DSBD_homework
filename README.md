Per eseguire correttamente il progetto, segui questi passaggi:
1. Scarica il file credentials.json dall’area privata del sito OpenSky.
2. Inserisci il file credentials.json nella cartella principale del progetto DSDB_Homework.
3. Avvia il progetto scegliendo una delle seguenti modalità:
**Docker Compose:**
```bash
docker-compose up
```
**Kubernetes:**
```bash
# Su macOS/Linux
./k8s/deploy.sh
```
```powershell
# Su Windows
./k8s/deploy.ps1
```

Per visualizzare i dati raccolti da Prometheus sono previste due modalità:
1. Accesso diretto a Prometheus UI:
- Utilizzando Docker Compose, la Prometheus UI è accessibile all’indirizzo: http://localhost:9090
- Utilizzando Kubernetes, è necessario eseguire il port-forward del servizio Prometheus eseguendo: kubectl port-forward svc/prometheus 9090:9090 -n dsbd, e successivamente accedere alla UI allo stesso indirizzo: http://localhost:9090
2. Generare grafici con metric_reader:
La prima volta è necessario configurare un virtual environment Python:
```bash
cd prometheus
python3 -m venv venv
source venv/bin/activate  # Su macOS/Linux
# oppure: venv\Scripts\activate  # Su Windows
pip install -r requirements.txt
```
Per generare i grafici (dopo aver attivato il virtual environment):
```bash
cd prometheus
source venv/bin/activate  # Se non già attivo
python3 metrics_reader.py --hours 1
```
I file PNG prodotti vengono salvati nella cartella: prometheus/metrics_output/

Prometheus raccoglie automaticamente le metriche ogni 15 secondi dagli endpoint `/metrics` dei microservizi UserManager e DataCollector.