# NEON + RAILWAY + VERCEL DEPLOYMENT GUIDE
## $0/month, Always On, No Sleep

| Layer | Platform | Cost | What It Does |
|---|---|---|---|
| **Database** | Neon | $0 | PostgreSQL (0.5 GB, managed, backed up) |
| **Backend** | Railway | $0 | FastAPI + Celery (0.5 GB RAM) |
| **Frontend** | Vercel | $0 | Next.js (100 GB bandwidth) |
| **Total** | | **$0/month** | |

---

## STEP 1: Create Neon Database (3 min)

1. Go to **https://neon.tech** → Sign up with GitHub
2. Click **Create Project**
3. Configure:
   - **Project name:** `invoice-handler`
   - **Database name:** `invoice_handler`
   - **Region:** Select closest to you
4. Click **Create Project**
5. Copy the **Connection string** from the dashboard
   - It looks like: `postgresql://username:password@ep-xxx.us-east-2.aws.neon.tech/invoice_handler?sslmode=require`
6. **Save this** — you'll need it for Railway

---

## STEP 2: Push Code to GitHub (2 min)

```bash
cd "Z:\invoice handler"
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/invoice-handler.git
git push -u origin main
```

---

## STEP 3: Sign Up for Railway (1 min)

1. Go to **https://railway.com** → Login with GitHub
2. **No credit card required**

---

## STEP 4: Deploy Backend to Railway (3 min)

1. Click **New Project** → **Deploy from GitHub Repo**
2. Select `invoice-handler`
3. Railway detects `Dockerfile.railway` and starts building

**Before it finishes, set variables:**

4. Click on your service → **Variables** tab
5. Add these:

```
DATABASE_URL=postgresql://username:password@ep-xxx.us-east-2.aws.neon.tech/invoice_handler?sslmode=require
REDIS_URL=redis://default:password@redis.railway.internal:6379
CELERY_BROKER_URL=redis://default:password@redis.railway.internal:6379
CELERY_RESULT_BACKEND=redis://default:password@redis.railway.internal:6379
ENVIRONMENT=production
ENFORCE_MFA=false
ENABLE_PASSWORD_AUTH=true
PYTHONPATH=/app
LOG_LEVEL=INFO
```

6. Generate secrets:

```bash
python -c "
from cryptography.fernet import Fernet
import secrets
print(f'SECRET_KEY={secrets.token_urlsafe(48)}')
print(f'JWT_SECRET_KEY={secrets.token_urlsafe(48)}')
print(f'TOKEN_ENCRYPTION_KEY={Fernet.generate_key().decode()}')
print(f'OAUTH_STATE_SECRET={secrets.token_urlsafe(32)}')
"
```

7. Add the secrets to Railway Variables too

---

## STEP 5: Add Redis on Railway (1 min)

1. In your Railway project, click **+ New** → **Database** → **Redis**
2. Click on Redis → **Connect** tab → Copy `REDIS_URL`
3. Update `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` in your API service variables

---

## STEP 6: Generate Domain (30 sec)

1. Click on API service → **Settings** → **Networking**
2. Click **Generate Domain**
3. Your API is live: `https://invoice-handler.up.railway.app`

---

## STEP 7: Create Account (1 min)

Wait for deployment to succeed (green checkmark), then:

Option A - Via Railway Terminal:
```bash
python setup_production.py
```

Option B - From your local machine:
```bash
export DATABASE_URL="your-neon-connection-string"
python setup_production.py
```

**Login:**
- Email: `admin@invoicehandler.com`
- Password: `InvoiceHandler2026!`
- Plan: PRO

---

## STEP 8: Deploy Frontend to Vercel (2 min)

1. Go to **https://vercel.com** → Import your GitHub repo
2. Set **Root Directory** to `frontend`
3. Add:
   ```
   NEXT_PUBLIC_API_URL=https://invoice-handler.up.railway.app
   ```
4. Deploy

---

## STEP 9: Update CORS (30 sec)

Go to Railway → API service → Variables:
```
CORS_ORIGINS=https://your-project.vercel.app
```

---

## DONE!

| Service | URL | Cost |
|---|---|---|
| API | `https://invoice-handler.up.railway.app` | $0 |
| API Docs | `https://invoice-handler.up.railway.app/docs` | $0 |
| Frontend | `https://your-project.vercel.app` | $0 |
| Database | Neon (managed) | $0 |

---

## WHY THIS STACK WORKS

**Neon Database:**
- Managed PostgreSQL (backups, scaling)
- 0.5 GB storage
- Branching (like Git for databases)
- No sleep, always available
- Separate from app = won't go down if app restarts

**Railway Backend:**
- Only runs API + Celery (saves RAM)
- 0.5 GB RAM is enough for API alone
- No database overhead
- Always on, no sleep

**Vercel Frontend:**
- 100 GB bandwidth
- Global CDN
- Auto HTTPS
- Preview deployments

---

## STORAGE LIMITS

| Platform | Storage | What Goes There |
|---|---|---|
| Neon | 0.5 GB | All your data (invoices, payments, etc.) |
| Railway | 0.5 GB | App code + logs |
| Vercel | Unlimited | Frontend assets |

Neon 0.5 GB can store approximately:
- ~50,000 invoices
- ~50,000 payments
- ~10,000 customers
- Plenty for a small business

---

## AFTER 30 DAYS

Railway: Downgrade to Free at https://railway.com/workspace/plans
- Gets $1/month free credits
- If usage stays under $1/month = $0 forever

Neon: Stays free forever
- 0.5 GB storage
- 100 compute hours/month

Vercel: Stays free forever
- No limits on bandwidth for hobby use
