# DSBD Kubernetes Deployment Script
# Run this script from the project root directory

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "DSBD Flight Tracker - Kubernetes Deploy" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Step 1: Create Kind cluster
Write-Host "`n[1/6] Creating Kind cluster..." -ForegroundColor Yellow
kind delete cluster --name dsbd-cluster 2>$null
kind create cluster --config k8s/kind-config.yaml
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to create Kind cluster" -ForegroundColor Red
    exit 1
}

# Step 2: Install NGINX Ingress Controller
Write-Host "`n[2/6] Installing NGINX Ingress Controller..." -ForegroundColor Yellow
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
Write-Host "  - Waiting for Ingress Controller to be ready..." -ForegroundColor Gray
kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=120s

# Step 3: Build Docker images
Write-Host "`n[3/6] Building Docker images..." -ForegroundColor Yellow
docker build -t dsbd/user-manager:latest ./UserManager
docker build -t dsbd/data-collector:latest ./DataCollector
docker build -t dsbd/alert-system:latest ./AlertSystem
docker build -t dsbd/alert-notifier:latest ./AlertNotifierSystem
docker build -t dsbd/api-gateway:latest ./nginx

# Step 4: Load images into Kind cluster
Write-Host "`n[4/6] Loading images into Kind cluster..." -ForegroundColor Yellow
kind load docker-image dsbd/user-manager:latest --name dsbd-cluster
kind load docker-image dsbd/data-collector:latest --name dsbd-cluster
kind load docker-image dsbd/alert-system:latest --name dsbd-cluster
kind load docker-image dsbd/alert-notifier:latest --name dsbd-cluster
kind load docker-image dsbd/api-gateway:latest --name dsbd-cluster

# Step 5: Prepare secrets and apply manifests via Kustomize
Write-Host "`n[5/6] Applying Kubernetes manifests..." -ForegroundColor Yellow
Write-Host "  - Preparing secrets from .env..." -ForegroundColor Gray
if (Test-Path ".\.env") {
    Copy-Item -Path ".\.env" -Destination ".\k8s\.secrets.env" -Force
} else {
    Write-Host "ERROR: .env file not found in project root. Create it before deploying." -ForegroundColor Red
    exit 1
}

Write-Host "  - Applying kustomization (namespace, configmaps, secrets, services)..." -ForegroundColor Gray
kubectl apply -k k8s/

Write-Host "  - Cleaning up temporary secrets file..." -ForegroundColor Gray
Remove-Item -Path ".\k8s\.secrets.env" -Force

Write-Host "  - Waiting for core services to be ready..." -ForegroundColor Gray
kubectl wait --for=condition=ready pod -l app=userdb -n dsbd --timeout=120s
kubectl wait --for=condition=ready pod -l app=datadb -n dsbd --timeout=120s
kubectl wait --for=condition=ready pod -l app=kafka -n dsbd --timeout=120s

# Step 6: Verify deployment
Write-Host "`n[6/6] Verifying deployment..." -ForegroundColor Yellow
Start-Sleep -Seconds 10
kubectl get pods -n dsbd
kubectl get services -n dsbd

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "Deployment complete!" -ForegroundColor Green
Write-Host "Access the application at: http://localhost" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

Write-Host "`nUseful commands:" -ForegroundColor Cyan
Write-Host "  kubectl get pods -n dsbd          # List all pods"
Write-Host "  kubectl logs -f <pod-name> -n dsbd  # View pod logs"
Write-Host "  kubectl describe pod <pod-name> -n dsbd  # Debug pod"
Write-Host "  kind delete cluster --name dsbd-cluster  # Cleanup"
