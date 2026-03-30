# ORACLE CLOUD DEPLOYMENT GUIDE
## $0/month, Always On, No Sleep, No Cold Starts
### Debit Card Accepted ✓

---

## TOTAL TIME: ~20 minutes

---

## STEP 1: Sign Up for Oracle Cloud (5 min)

1. Go to **https://www.oracle.com/cloud/free/**
2. Click **Start for free**
3. Enter your email and verify
4. Fill in your details:
   - Country: Your country
   - Name, address, etc.
5. **Payment verification:** Enter your debit card
   - Oracle places a **$1 temporary hold** (refunded automatically)
   - **You will NEVER be charged** as long as you use Always Free resources
6. Complete signup and verify your email
7. Login to Oracle Cloud Console

---

## STEP 2: Create Your Free VM (5 min)

1. In Oracle Cloud Console, go to **Menu → Compute → Instances**
2. Click **Create Instance**
3. Configure:
   - **Name:** `invoice-handler`
   - **Compartment:** (default)
   - **Image:** Ubuntu 22.04 (click "Change image" → Ubuntu → Ubuntu 22.04)
   - **Shape:** Click "Change shape" → **Ampere** → **VM.Standard.A1.Flex**
     - OCPUs: **4** (maximum free)
     - Memory: **24 GB** (maximum free)
   - **Networking:** Create new VCN (default settings)
   - **SSH key:** Upload your public key or click "Generate key pair"
     - **DOWNLOAD THE PRIVATE KEY** — you need it to connect
4. Click **Create**
5. Wait ~2 minutes for the instance to provision
6. Copy the **Public IP address** (e.g., `123.456.789.012`)

---

## STEP 3: Open Firewall Ports (2 min)

1. Go to your instance details page
2. Click on the **Subnet** link (under VNIC)
3. Click **Security Lists** → your default security list
4. Click **Add Ingress Rules** and add these rules:

| Source CIDR | Protocol | Dest Port | Description |
|---|---|---|---|
| 0.0.0.0/0 | TCP | 22 | SSH |
| 0.0.0.0/0 | TCP | 80 | HTTP |
| 0.0.0.0/0 | TCP | 443 | HTTPS |

5. Click **Add Ingress Rules**

---

## STEP 4: Connect to Your VM (1 min)

Open terminal (or PowerShell on Windows):

```bash
# On Windows (PowerShell):
ssh -i "path/to/your-private-key.pem" ubuntu@YOUR_VM_IP

# On Mac/Linux:
chmod 600 your-private-key.pem
ssh -i your-private-key.pem ubuntu@YOUR_VM_IP
```

---

## STEP 5: Setup the VM (3 min)

Once connected to your VM:

```bash
# Download and run setup script
curl -sSL https://raw.githubusercontent.com/YOUR_USER/invoice-handler/main/scripts/setup_vm.sh | bash
```

Or manually:

```bash
# Update system
sudo apt-get update -y && sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt-get install -y docker-compose-plugin

# Install Nginx
sudo apt-get install -y nginx

# Setup firewall
sudo apt-get install -y ufw
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

# Create app directory
sudo mkdir -p /opt/invoice-handler
sudo chown $USER:$USER /opt/invoice-handler

# Log out and back in for docker group to take effect
exit
```

Reconnect:
```bash
ssh -i your-private-key.pem ubuntu@YOUR_VM_IP
```

---

## STEP 6: Deploy the App (3 min)

On your VM:

```bash
cd /opt/invoice-handler

# Clone your repo
git clone https://github.com/YOUR_USERNAME/invoice-handler.git .

# Generate secrets
python3 -c "
from cryptography.fernet import Fernet
import secrets
print(f'SECRET_KEY={secrets.token_urlsafe(48)}')
print(f'JWT_SECRET_KEY={secrets.token_urlsafe(48)}')
print(f'TOKEN_ENCRYPTION_KEY={Fernet.generate_key().decode()}')
print(f'OAUTH_STATE_SECRET={secrets.token_urlsafe(32)}')
print(f'POSTGRES_PASSWORD={secrets.token_urlsafe(24)}')
"

# Create .env file
cat > .env << 'EOF'
# Copy the output from the command above into here:
SECRET_KEY=<paste-here>
JWT_SECRET_KEY=<paste-here>
TOKEN_ENCRYPTION_KEY=<paste-here>
OAUTH_STATE_SECRET=<paste-here>
POSTGRES_PASSWORD=<paste-here>

# App settings
ENVIRONMENT=production
POSTGRES_DB=invoice_handler
POSTGRES_USER=postgres
CORS_ORIGINS=*
ENFORCE_MFA=false
ENABLE_PASSWORD_AUTH=true
LOG_LEVEL=INFO
EOF

# Start everything
docker compose -f docker-compose.prod.yml up -d --build

# Wait for services to start (30 seconds)
sleep 30

# Create database and default user
docker compose -f docker-compose.prod.yml exec -T api python setup_production.py
```

---

## STEP 7: Verify It's Running

```bash
# Check all containers are running
docker compose -f docker-compose.prod.yml ps

# Test the API
curl http://localhost:8000/health

# Test from outside
curl http://YOUR_VM_IP:8000/health
```

---

## STEP 8: Login

Open your browser and go to:
- **API Docs:** http://YOUR_VM_IP:8000/docs
- **Health Check:** http://YOUR_VM_IP:8000/health

**Login credentials:**
- Email: `admin@invoicehandler.com`
- Password: `InvoiceHandler2026!`
- Plan: PRO (500 invoices/month)

---

## STEP 9: Deploy Frontend to Vercel (3 min)

1. Go to **https://vercel.com** → Import your GitHub repo
2. Set **Root Directory** to `frontend`
3. Add environment variable:
   ```
   NEXT_PUBLIC_API_URL=http://YOUR_VM_IP:8000
   ```
4. Deploy
5. Your frontend is now live at `https://your-project.vercel.app`

---

## OPTIONAL: Custom Domain + SSL

If you own a domain:

```bash
# Point your domain to your VM IP (via DNS A record)
# Then run:
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Update .env CORS_ORIGINS
nano .env
# Change: CORS_ORIGINS=https://yourdomain.com

# Restart API
docker compose -f docker-compose.prod.yml restart api
```

---

## OPTIONAL: GitHub Auto-Deploy

1. Go to your GitHub repo → Settings → Secrets → Actions
2. Add these secrets:
   - `VM_HOST` = your VM IP
   - `VM_USER` = ubuntu
   - `VM_SSH_KEY` = contents of your private key file
3. Now every push to `main` auto-deploys!

---

## USEFUL COMMANDS

```bash
# View logs
docker compose -f docker-compose.prod.yml logs -f api

# Restart everything
docker compose -f docker-compose.prod.yml restart

# Stop everything
docker compose -f docker-compose.prod.yml down

# Update and redeploy
git pull && docker compose -f docker-compose.prod.yml up -d --build

# Check disk space
df -h

# Check memory
free -h
```

---

## WHAT YOU GET FOR FREE

| Resource | Free Tier | Your Usage |
|---|---|---|
| CPU | 4 ARM cores | ✓ Always on |
| RAM | 24 GB | ✓ Always on |
| Storage | 200 GB | ~2 GB used |
| Bandwidth | 10 TB/month | ~1 GB expected |
| IP | 1 static public IP | ✓ |
| **Cost** | **$0/month forever** | **$0** |

---

## TROUBLESHOOTING

**Can't connect via SSH:**
- Check security list has port 22 open
- Make sure you're using the correct private key
- Try: `ssh -v -i key.pem ubuntu@IP` for verbose output

**Containers won't start:**
- Check logs: `docker compose -f docker-compose.prod.yml logs`
- Make sure .env has all required variables
- Check disk space: `df -h`

**API returns 502:**
- Wait 30 seconds after first deploy (building containers)
- Check: `docker compose -f docker-compose.prod.yml ps`
- Check logs: `docker compose -f docker-compose.prod.yml logs api`

**Database connection refused:**
- Make sure db container is healthy: `docker compose -f docker-compose.prod.yml ps`
- Check DATABASE_URL in .env has correct password
