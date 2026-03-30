#!/bin/bash
# ============================================================
# Oracle Cloud VM Setup Script
# Run this ONCE on your fresh Ubuntu VM
# Usage: bash setup_vm.sh
# ============================================================

set -e

echo "=========================================="
echo "Invoice Handler - VM Setup"
echo "=========================================="

# Update system
echo "[1/6] Updating system packages..."
sudo apt-get update -y && sudo apt-get upgrade -y

# Install Docker
echo "[2/6] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo "Docker installed"
else
    echo "Docker already installed"
fi

# Install Docker Compose
echo "[3/6] Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    sudo apt-get install -y docker-compose-plugin
    echo "Docker Compose installed"
else
    echo "Docker Compose already installed"
fi

# Install Nginx and Certbot
echo "[4/6] Installing Nginx and Certbot..."
sudo apt-get install -y nginx certbot python3-certbot-nginx

# Setup firewall
echo "[5/6] Configuring firewall..."
sudo apt-get install -y ufw
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw --force enable

# Create app directory
echo "[6/6] Creating app directory..."
sudo mkdir -p /opt/invoice-handler
sudo chown $USER:$USER /opt/invoice-handler

echo ""
echo "=========================================="
echo "VM Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Clone your repo: cd /opt/invoice-handler && git clone https://github.com/YOUR_USER/invoice-handler.git ."
echo "2. Create .env file: cp .env.example .env && nano .env"
echo "3. Run: docker compose -f docker-compose.prod.yml up -d"
echo ""
echo "To get free SSL (if you have a domain):"
echo "  sudo certbot --nginx -d yourdomain.com"
echo ""
