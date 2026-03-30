# Simple Procfile for Railway (no Docker needed)
web: alembic upgrade head 2>/dev/null; python -m uvicorn api.main:app --host 0.0.0.0 --port $PORT
worker: celery -A worker.celery_worker:celery_app worker --loglevel=info --concurrency=1
