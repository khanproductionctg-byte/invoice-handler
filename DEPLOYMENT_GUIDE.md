# PRODUCTION DEPLOYMENT GUIDE
## Render (Backend) + Vercel (Frontend) + Neon (Database)
### Total Cost: $0/month (Free tiers)

---

## STEP 1: Create Neon Database (2 minutes)

1. Go to **https://neon.tech** and sign up (free)
2. Create a new project: `invoice-handler`
3. Copy the connection string from the dashboard
   - It looks like: `postgresql://username:password@ep-xxx.us-east-2.aws.neon.tech/invoice_handler?sslmode=require`
4. Save this as `DATABASE_URL` — you'll need it for Render

---

## STEP 2: Deploy Backend to Render (5 minutes)

1. Go to **https://render.com** and sign up (free)
2. Click **New +** → **Web Service**
3. Connect your GitHub repo (or use "Public Git URL")
4. Configure:
   - **Name:** `invoice-handler-api`
   - **Runtime:** Python 3
   - **Build Command:** `pip install --upgrade pip && pip install -r requirements.txt`
   - **Start Command:** `python -m uvicorn api.main:app --host 0.0.0.0 --port $PORT`
   - **Plan:** Free
5. Add Environment Variables:
   ```
   ENVIRONMENT=production
   DATABASE_URL=<your-neon-connection-string-from-step-1>
   SECRET_KEY=<click-generate>
   JWT_SECRET_KEY=<click-generate>
   TOKEN_ENCRYPTION_KEY=<click-generate>
   OAUTH_STATE_SECRET=<click-generate>
   CORS_ORIGINS=https://your-frontend.vercel.app
   ENFORCE_MFA=false
   ENABLE_PASSWORD_AUTH=true
   PYTHONPATH=/opt/render/project/src
   ```
6. Click **Create Web Service**
7. Wait for deploy (~3-5 minutes)
8. Copy your API URL: `https://invoice-handler-api.onrender.com`

---

## STEP 3: Create Pro Account on Neon (1 minute)

After backend is deployed, run this once:

```bash
# Set your Neon DATABASE_URL
export DATABASE_URL="postgresql://user:pass@ep-xxx.neon.tech/invoice_handler?sslmode=require"

# Run the setup
python setup_production.py
```

**This creates your account:**
- **Email:** admin@invoicehandler.com
- **Password:** InvoiceHandler2026!
- **Plan:** PRO (500 invoices/month)

---

## STEP 4: Deploy Frontend to Vercel (3 minutes)

1. Go to **https://vercel.com** and sign up (free)
2. Click **Add New...** → **Project**
3. Import your GitHub repo
4. Configure:
   - **Framework Preset:** Next.js
   - **Root Directory:** `frontend`
   - **Build Command:** `npm run build` (auto-detected)
5. Add Environment Variables:
   ```
   NEXT_PUBLIC_API_URL=https://invoice-handler-api.onrender.com
   NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=<from-clerk.com>
   CLERK_SECRET_KEY=<from-clerk.com>
   ```
6. Click **Deploy**
7. Wait for deploy (~2 minutes)
8. Your frontend is live at: `https://your-project.vercel.app`

---

## STEP 5: Update CORS on Backend (30 seconds)

1. Go to Render → Your Service → Environment
2. Update `CORS_ORIGINS` to your Vercel URL:
   ```
   CORS_ORIGINS=https://your-project.vercel.app
   ```
3. Save → Service auto-restarts

---

## STEP 6: Login

Go to your Vercel URL and login with:
- **Email:** admin@invoicehandler.com
- **Password:** InvoiceHandler2026!

---

## TROUBLESHOOTING

**Backend won't start on Render:**
- Check logs in Render dashboard
- Make sure DATABASE_URL includes `?sslmode=require`

**Frontend can't connect to backend:**
- Verify CORS_ORIGINS matches your Vercel URL exactly
- Check NEXT_PUBLIC_API_URL has no trailing slash

**Database connection fails:**
- Neon free tier sleeps after 5 minutes of inactivity
- First request may take 2-3 seconds to wake up (normal)

---

## FREE TIER LIMITS

| Service | Free Limit |
|---------|-----------|
| Neon | 0.5 GB storage, 100 hours compute/month |
| Render | 750 hours/month, sleeps after 15 min inactivity |
| Vercel | 100 GB bandwidth, 100 builds/day |

**Tip:** Render free tier sleeps after 15 min. First request after sleep takes ~30 seconds to wake up.
For always-on, upgrade Render to Starter ($7/month).
