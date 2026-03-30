# RAILWAY DEPLOYMENT GUIDE
## $0/month, Always On, No Sleep, No Credit Card Required
### Free forever (after 30-day $5 trial)

---

## WHAT YOU GET (FREE PLAN)

| Resource | Free Limit |
|---|---|
| RAM | 0.5 GB per service |
| Services | 3 |
| Storage | 0.5 GB |
| Build time | 10 min |
| Custom domain | 0 (use railway.app subdomain) |
| **Cost** | **$0/month** |

**No credit card required to sign up.**

---

## STEP 1: Push Code to GitHub (2 min)

If you haven't already:

```bash
cd "Z:\invoice handler"
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/invoice-handler.git
git push -u origin main
```

---

## STEP 2: Sign Up for Railway (1 min)

1. Go to **https://railway.com**
2. Click **Login** → **Login with GitHub**
3. Authorize Railway to access your repos
4. **No credit card required** for the free trial

You get **$5 free credits** for 30 days. After that, Free plan gives **$1/month free**.

---

## STEP 3: Create Project + Add PostgreSQL (2 min)

1. Click **New Project**
2. Click **Deploy from GitHub Repo**
3. Select your `invoice-handler` repo
4. Railway auto-detects the Dockerfile and starts deploying

**Before it finishes, add PostgreSQL:**

5. Click **+ New** → **Database** → **PostgreSQL**
6. Railway creates a PostgreSQL database instantly
7. Click on the PostgreSQL service → **Connect** tab
8. Copy the **DATABASE_URL** value

---

## STEP 4: Add Redis (1 min)

1. Click **+ New** → **Database** → **Redis**
2. Click on the Redis service → **Connect** tab
3. Copy the **REDIS_URL** value

---

## STEP 5: Set Environment Variables (2 min)

1. Click on your **API service** (the one from GitHub)
2. Go to **Variables** tab
3. Add these variables:

```
DATABASE_URL=<paste from PostgreSQL Connect tab>
REDIS_URL=<paste from Redis Connect tab>
CELERY_BROKER_URL=<same as REDIS_URL>
CELERY_RESULT_BACKEND=<same as REDIS_URL>
ENVIRONMENT=production
ENFORCE_MFA=false
ENABLE_PASSWORD_AUTH=true
PYTHONPATH=/app
```

4. Generate secrets:

Go to your terminal and run:
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

5. Add the output to Railway Variables too

6. Railway auto-redeploys after adding variables

---

## STEP 6: Generate Public Domain (30 sec)

1. Click on your API service
2. Go to **Settings** → **Networking**
3. Click **Generate Domain**
4. Railway gives you something like: `invoice-handler-production.up.railway.app`

**Your API is now live at:** `https://invoice-handler-production.up.railway.app`

---

## STEP 7: Create Database Account (1 min)

1. Click on your API service → **Deployments** tab
2. Wait for the deployment to succeed (green checkmark)
3. Open the Railway terminal (click the service → **Terminal** tab)
4. Run:

```bash
python setup_production.py
```

**Login credentials:**
- Email: `admin@invoicehandler.com`
- Password: `InvoiceHandler2026!`
- Plan: PRO (500 invoices/month)

---

## STEP 8: Deploy Frontend to Vercel (2 min)

1. Go to **https://vercel.com** → Import your GitHub repo
2. Set **Root Directory** to `frontend`
3. Add environment variable:
   ```
   NEXT_PUBLIC_API_URL=https://invoice-handler-production.up.railway.app
   ```
4. Deploy
5. Your frontend is live at `https://your-project.vercel.app`

---

## STEP 9: Update CORS (30 sec)

Go back to Railway → API service → Variables, update:
```
CORS_ORIGINS=https://your-project.vercel.app
```

---

## DONE!

**API:** `https://invoice-handler-production.up.railway.app`
**Docs:** `https://invoice-handler-production.up.railway.app/docs`
**Frontend:** `https://your-project.vercel.app`

**Login:** admin@invoicehandler.com / InvoiceHandler2026!

**Cost: $0/month**

---

## AFTER 30 DAYS

When your $5 trial credits expire:
1. Go to **https://railway.com/workspace/plans**
2. Click **Downgrade to Free**
3. You get $1/month in free credits forever
4. If usage stays under $1/month = **$0 forever**

---

## WHAT FITS IN FREE PLAN

| Service | RAM Used | Storage |
|---|---|---|
| PostgreSQL | ~150 MB | ~100 MB |
| Redis | ~30 MB | ~10 MB |
| API + Celery | ~200 MB | ~50 MB |
| **Total** | **~380 MB** | **~160 MB** |

Well within 0.5 GB per service limit.

---

## USEFUL COMMANDS

```bash
# View logs
railway logs

# Open terminal
railway shell

# Redeploy
railway up

# Check status
railway status
```

Install Railway CLI (optional):
```bash
npm install -g @railway/cli
railway login
railway link
```

---

## TROUBLESHOOTING

**Build fails:**
- Check logs in Railway dashboard
- Make sure `Dockerfile.railway` exists in repo root
- Check `requirements.prod.txt` has no typos

**502 after deploy:**
- Wait 30 seconds for container to start
- Check health endpoint: `/health`
- Check logs for errors

**Database connection fails:**
- Make sure `DATABASE_URL` uses Railway's internal URL (not external)
- Railway PostgreSQL uses `postgres://` prefix (works with SQLAlchemy)

**Out of memory:**
- Reduce Celery concurrency: change `--concurrency=1` to a background worker
- Or disable Celery and use API-only mode

**Storage full (0.5 GB limit):**
- Free plan only has 0.5 GB
- For production data, upgrade to Hobby ($5/month) for 5 GB
- Or periodically clean old data
