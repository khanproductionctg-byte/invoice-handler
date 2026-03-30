"""
Distributed locking utilities for workflow concurrency control.
Uses Redis SET NX EX pattern for atomic lock acquisition.
"""
import os
import uuid
import logging
import threading
import time
from contextlib import contextmanager, asynccontextmanager
from typing import Optional

logger = logging.getLogger(__name__)

LOCK_ACQUIRE_TIMEOUT = 5
LOCK_KEY_PREFIX = "lock:workflow:"
LOCK_RENEWAL_INTERVAL = 60  # Renew lock every 60 seconds


class LockAcquisitionError(Exception):
    """Raised when lock cannot be acquired within timeout."""
    pass


def get_redis_client():
    """Get Redis client for distributed locking."""
    import redis
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    return redis.from_url(redis_url, decode_responses=True)


@contextmanager
def sync_tenant_workflow_lock(tenant_id: str, timeout: int = 300):
    """
    Synchronous context manager for distributed workflow locking per tenant.
    
    Uses Redis SET NX EX pattern for atomic lock acquisition.
    Only the lock holder can release the lock (using lock_id).
    Includes automatic lock renewal to prevent expiry during long workflows.
    
    Args:
        tenant_id: Tenant identifier for the workflow lock
        timeout: Lock TTL in seconds (default 300)
    
    Raises:
        WorkflowAlreadyRunningError: If lock cannot be acquired within 5s
    
    Usage:
        with sync_tenant_workflow_lock(tenant_id):
            run_workflow(...)
    """
    import time
    from utils.exceptions import WorkflowAlreadyRunningError
    
    redis_client = None
    lock_id = str(uuid.uuid4())
    lock_key = f"{LOCK_KEY_PREFIX}{tenant_id}"
    acquired = False
    renewal_thread = None
    stop_renewal = threading.Event()
    
    def renew_lock_periodically():
        """Background thread to renew the lock periodically."""
        while not stop_renewal.is_set():
            try:
                if redis_client is not None:
                    current = redis_client.get(lock_key)
                    if current == lock_id:
                        redis_client.expire(lock_key, timeout)
                        logger.debug(f"Lock renewed: key={lock_key}, lock_id={lock_id}")
            except Exception as e:
                logger.warning(f"Lock renewal error: {e}")
            stop_renewal.wait(LOCK_RENEWAL_INTERVAL)
    
    try:
        redis_client = get_redis_client()
        if redis_client is None:
            logger.warning("Redis unavailable, skipping distributed lock")
            yield
            return
        
        wait_time = 0
        poll_interval = 0.1
        
        while wait_time < LOCK_ACQUIRE_TIMEOUT:
            acquired = redis_client.set(
                lock_key,
                lock_id,
                nx=True,
                ex=timeout
            )
            
            if acquired:
                logger.info(
                    f"Lock acquired: key={lock_key}, lock_id={lock_id}, timeout={timeout}s"
                )
                break
            
            time.sleep(poll_interval)
            wait_time += poll_interval
        
        if not acquired:
            logger.warning(
                f"Lock acquisition failed: key={lock_key}, waited={wait_time}s"
            )
            raise WorkflowAlreadyRunningError(
                tenant_id=int(tenant_id) if tenant_id.isdigit() else 0,
                message=f"Workflow already running for tenant. Could not acquire lock after {LOCK_ACQUIRE_TIMEOUT}s."
            )
        
        # Start lock renewal thread
        renewal_thread = threading.Thread(target=renew_lock_periodically, daemon=True)
        renewal_thread.start()
        
        yield
        
    except WorkflowAlreadyRunningError:
        raise
        
    except Exception as e:
        logger.error(f"Lock error: key={lock_key}, error={str(e)}")
        raise
        
    finally:
        # Stop renewal thread
        stop_renewal.set()
        if renewal_thread:
            renewal_thread.join(timeout=5)
        
        if redis_client is not None and acquired:
            try:
                current_lock_id = redis_client.get(lock_key)
                if current_lock_id == lock_id:
                    redis_client.delete(lock_key)
                    logger.info(f"Lock released: key={lock_key}, lock_id={lock_id}")
            except Exception as release_err:
                logger.error(f"Lock release error: {release_err}")


@asynccontextmanager
async def tenant_workflow_lock(tenant_id: str, timeout: int = 300):
    """
    Async generator for distributed workflow locking per tenant.
    Includes automatic lock renewal to prevent expiry during long workflows.
    
    Args:
        tenant_id: Tenant identifier for the workflow lock
        timeout: Lock TTL in seconds (default 300)
    
    Raises:
        WorkflowAlreadyRunningError: If lock cannot be acquired within 5s
    
    Usage:
        async with tenant_workflow_lock(tenant_id):
            await run_workflow(...)
    """
    import asyncio
    from utils.exceptions import WorkflowAlreadyRunningError
    
    redis_client = None
    lock_id = str(uuid.uuid4())
    lock_key = f"{LOCK_KEY_PREFIX}{tenant_id}"
    acquired = False
    renewal_task = None
    
    async def renew_lock_periodically():
        """Async task to renew the lock periodically."""
        while True:
            try:
                await asyncio.sleep(LOCK_RENEWAL_INTERVAL)
                if redis_client is not None:
                    current = redis_client.get(lock_key)
                    if current == lock_id:
                        redis_client.expire(lock_key, timeout)
                        logger.debug(f"Lock renewed: key={lock_key}, lock_id={lock_id}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Lock renewal error: {e}")
    
    try:
        redis_client = get_redis_client()
        if redis_client is None:
            logger.warning("Redis unavailable, skipping distributed lock")
            yield
            return
        
        wait_time = 0
        poll_interval = 0.1
        
        while wait_time < LOCK_ACQUIRE_TIMEOUT:
            acquired = redis_client.set(
                lock_key,
                lock_id,
                nx=True,
                ex=timeout
            )
            
            if acquired:
                logger.info(
                    f"Lock acquired: key={lock_key}, lock_id={lock_id}, timeout={timeout}s"
                )
                break
            
            await asyncio.sleep(poll_interval)
            wait_time += poll_interval
        
        if not acquired:
            logger.warning(
                f"Lock acquisition failed: key={lock_key}, waited={wait_time}s"
            )
            raise WorkflowAlreadyRunningError(
                tenant_id=int(tenant_id) if tenant_id.isdigit() else 0,
                message=f"Workflow already running for tenant. Could not acquire lock after {LOCK_ACQUIRE_TIMEOUT}s."
            )
        
        # Start async lock renewal task
        renewal_task = asyncio.create_task(renew_lock_periodically())
        
        yield
        
    except WorkflowAlreadyRunningError:
        raise
        
    except Exception as e:
        logger.error(f"Lock error: key={lock_key}, error={str(e)}")
        raise
        
    finally:
        # Cancel renewal task
        if renewal_task:
            renewal_task.cancel()
            try:
                await renewal_task
            except asyncio.CancelledError:
                pass
        
        if redis_client is not None and acquired:
            try:
                current_lock_id = redis_client.get(lock_key)
                if current_lock_id == lock_id:
                    redis_client.delete(lock_key)
                    logger.info(f"Lock released: key={lock_key}, lock_id={lock_id}")
            except Exception as release_err:
                logger.error(f"Lock release error: {release_err}")
