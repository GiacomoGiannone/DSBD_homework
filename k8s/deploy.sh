#!/bin/bash

# DSBD Kubernetes Deployment Script for Mac/Linux
# Run this script from the project root directory
# Usage: chmod +x k8s/deploy.sh && ./k8s/deploy.sh

# Colors for output
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}DSBD Flight Tracker - Kubernetes Deploy${NC}"
echo -e "${CYAN}========================================${NC}"

# Step 1: Create Kind cluster
echo -e "\n${YELLOW}[1/6] Creating Kind cluster...${NC}"
kind delete cluster --name dsbd-cluster 2>/dev/null
kind create cluster --config k8s/kind-config.yaml
if [ $? -ne 0 ]; then
    echo -e "${RED}ERROR: Failed to create Kind cluster${NC}"
    exit 1
fi

# Step 2: Install NGINX Ingress Controller
echo -e "\n${YELLOW}[2/6] Installing NGINX Ingress Controller...${NC}"
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
echo -e "${GRAY}  - Waiting for Ingress Controller to be ready...${NC}"
kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=120s

# Step 3: Build Docker images
echo -e "\n${YELLOW}[3/6] Building Docker images...${NC}"
docker build -t dsbd/user-manager:latest ./UserManager
docker build -t dsbd/data-collector:latest ./DataCollector
docker build -t dsbd/alert-system:latest ./AlertSystem
docker build -t dsbd/alert-notifier:latest ./AlertNotifierSystem
docker build -t dsbd/api-gateway:latest ./nginx

# Step 4: Load images into Kind cluster
echo -e "\n${YELLOW}[4/6] Loading images into Kind cluster...${NC}"
kind load docker-image dsbd/user-manager:latest --name dsbd-cluster
kind load docker-image dsbd/data-collector:latest --name dsbd-cluster
kind load docker-image dsbd/alert-system:latest --name dsbd-cluster
kind load docker-image dsbd/alert-notifier:latest --name dsbd-cluster
kind load docker-image dsbd/api-gateway:latest --name dsbd-cluster

# Step 5: Prepare secrets and apply manifests via Kustomize
echo -e "\n${YELLOW}[5/6] Applying Kubernetes manifests...${NC}"
echo -e "${GRAY}  - Preparing secrets from .env...${NC}"
if [ -f .env ]; then
    cp .env k8s/.secrets.env
else
    echo -e "${RED}ERROR: .env file not found in project root. Create it before deploying.${NC}"
    exit 1
fi

echo -e "${GRAY}  - Applying kustomization (namespace, configmaps, secrets, services)...${NC}"
kubectl apply -k k8s/

echo -e "${GRAY}  - Cleaning up temporary secrets file...${NC}"
rm -f k8s/.secrets.env

echo -e "${GRAY}  - Waiting for core services to be ready...${NC}"
kubectl wait --for=condition=ready pod -l app=userdb -n dsbd --timeout=120s || true
kubectl wait --for=condition=ready pod -l app=datadb -n dsbd --timeout=120s || true
kubectl wait --for=condition=ready pod -l app=kafka -n dsbd --timeout=120s || true

# Step 6: Verify deployment
echo -e "\n${YELLOW}[6/6] Verifying deployment...${NC}"
sleep 10
kubectl get pods -n dsbd
kubectl get services -n dsbd

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment complete!${NC}"
echo -e "${GREEN}Access the application at: http://localhost${NC}"
echo -e "${GREEN}========================================${NC}"

echo -e "\n${CYAN}Useful commands:${NC}"
echo "  kubectl get pods -n dsbd              # List all pods"
echo "  kubectl logs -f <pod-name> -n dsbd    # View pod logs"
echo "  kubectl describe pod <pod-name> -n dsbd  # Debug pod"
echo "  kind delete cluster --name dsbd-cluster  # Cleanup"
