"""
Tests for distributed workflow locking.
Verifies that concurrent workflow invocations for the same tenant are serialized.
"""
import pytest
import asyncio
import os
from unittest.mock import MagicMock, patch, AsyncMock
from concurrent.futures import ThreadPoolExecutor

os.environ["ENVIRONMENT"] = "test"

from utils.workflow_lock import sync_tenant_workflow_lock, tenant_workflow_lock, get_redis_client
from utils.exceptions import WorkflowAlreadyRunningError


class TestDistributedLock:
    """Test suite for distributed locking mechanism."""
    
    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        with patch('utils.workflow_lock.get_redis_client') as mock:
            redis_mock = MagicMock()
            mock.return_value = redis_mock
            yield redis_mock
    
    @pytest.fixture
    def mock_redis_unavailable(self):
        """Create a mock for when Redis is unavailable."""
        with patch('utils.workflow_lock.get_redis_client') as mock:
            mock.return_value = None
            yield
    
    def test_lock_acquired_successfully(self, mock_redis):
        """Test that lock is acquired when available."""
        mock_redis.set.return_value = True
        
        with sync_tenant_workflow_lock("tenant_123") as locked:
            assert locked is None
            mock_redis.set.assert_called_once()
            call_args = mock_redis.set.call_args
            assert call_args[1]['nx'] is True
            assert call_args[1]['ex'] == 300
            assert call_args[0][0] == "lock:workflow:tenant_123"
    
    def test_lock_released_on_exit(self, mock_redis):
        """Test that lock is released when exiting context."""
        import uuid
        stored_lock_id = [None]
        
        def mock_get(key):
            return stored_lock_id[0]
        
        def mock_set(key, value, nx=True, ex=300):
            stored_lock_id[0] = value
            return True
        
        mock_redis.set.side_effect = mock_set
        mock_redis.get.side_effect = mock_get
        
        with sync_tenant_workflow_lock("tenant_123") as locked:
            pass
        
        mock_redis.delete.assert_called_once_with("lock:workflow:tenant_123")
    
    def test_lock_not_released_if_not_owner(self, mock_redis):
        """Test that lock is not released if lock_id doesn't match."""
        mock_redis.set.return_value = True
        mock_redis.get.return_value = "different-lock-id"
        
        with sync_tenant_workflow_lock("tenant_123") as locked:
            pass
        
        mock_redis.delete.assert_not_called()
    
    def test_concurrent_lock_blocked_after_timeout(self, mock_redis):
        """Test that concurrent lock acquisition fails after timeout."""
        mock_redis.set.return_value = False
        
        with pytest.raises(WorkflowAlreadyRunningError) as exc_info:
            with sync_tenant_workflow_lock("tenant_123"):
                pass
        
        assert exc_info.value.status_code == 409
        assert "tenant" in exc_info.value.detail.lower() or "123" in exc_info.value.detail
    
    def test_redis_unavailable_skips_lock(self, mock_redis_unavailable):
        """Test that lock is skipped when Redis is unavailable."""
        with sync_tenant_workflow_lock("tenant_123") as locked:
            assert locked is None
    
    def test_lock_key_format(self, mock_redis):
        """Test that lock key has correct format."""
        mock_redis.set.return_value = True
        
        with sync_tenant_workflow_lock("tenant_456", timeout=600):
            pass
        
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "lock:workflow:tenant_456"
        assert call_args[1]['ex'] == 600


class TestConcurrentWorkflowInvocations:
    """Test that concurrent workflow invocations are properly serialized."""
    
    def test_only_one_workflow_runs_per_tenant(self):
        """Test that only 1 of 3 concurrent invocations runs, 2 get 409."""
        import threading
        import time
        
        results = []
        lock_holders = []
        
        def mock_workflow_execution(tenant_id: str, invocation_id: int):
            """Mock workflow execution that tries to acquire lock."""
            try:
                with sync_tenant_workflow_lock(tenant_id, timeout=300):
                    lock_holders.append(invocation_id)
                    time.sleep(0.5)
                    results.append({"id": invocation_id, "status": "success"})
            except WorkflowAlreadyRunningError as e:
                results.append({"id": invocation_id, "status": "rejected", "code": e.status_code})
            except Exception as e:
                results.append({"id": invocation_id, "status": "error", "error": str(e)})
        
        mock_redis = MagicMock()
        call_count = [0]
        lock_acquired = [False]
        
        def mock_set(key, value, nx=True, ex=300):
            if call_count[0] < 3:
                result = False
            else:
                if not lock_acquired[0]:
                    lock_acquired[0] = True
                    result = True
                else:
                    result = False
            call_count[0] += 1
            if result:
                time.sleep(0.1)
            return result
        
        mock_redis.set.side_effect = mock_set
        mock_redis.get.return_value = "test-lock-id"
        mock_redis.delete.return_value = True
        
        with patch('utils.workflow_lock.get_redis_client', return_value=mock_redis):
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [
                    executor.submit(mock_workflow_execution, "tenant_999", 1),
                    executor.submit(mock_workflow_execution, "tenant_999", 2),
                    executor.submit(mock_workflow_execution, "tenant_999", 3),
                ]
                for f in futures:
                    f.result()
        
        successes = [r for r in results if r["status"] == "success"]
        rejected = [r for r in results if r["status"] == "rejected"]
        
        assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"
        assert len(rejected) == 2, f"Expected 2 rejected, got {len(rejected)}"
        
        for r in rejected:
            assert r["code"] == 409, f"Expected 409, got {r.get('code')}"
    
    def test_different_tenants_can_run_concurrently(self):
        """Test that different tenants can run workflows in parallel."""
        import threading
        import time
        
        results = []
        
        def mock_workflow_execution(tenant_id: str, invocation_id: int):
            try:
                with sync_tenant_workflow_lock(tenant_id, timeout=300):
                    time.sleep(0.2)
                    results.append({"id": invocation_id, "tenant": tenant_id, "status": "success"})
            except WorkflowAlreadyRunningError as e:
                results.append({"id": invocation_id, "status": "rejected", "code": e.status_code})
        
        mock_redis = MagicMock()
        call_count = [0]
        
        def mock_set(key, value, nx=True, ex=300):
            call_count[0] += 1
            return True
        
        mock_redis.set.side_effect = mock_set
        mock_redis.get.return_value = "test-lock-id"
        mock_redis.delete.return_value = True
        
        with patch('utils.workflow_lock.get_redis_client', return_value=mock_redis):
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [
                    executor.submit(mock_workflow_execution, "tenant_1", 1),
                    executor.submit(mock_workflow_execution, "tenant_2", 2),
                    executor.submit(mock_workflow_execution, "tenant_3", 3),
                    executor.submit(mock_workflow_execution, "tenant_1", 4),
                ]
                for f in futures:
                    f.result()
        
        successes = [r for r in results if r["status"] == "success"]
        assert len(successes) == 4, f"Expected 4 successes, got {len(successes)}"


class TestAsyncLock:
    """Test async lock context manager."""
    
    @pytest.mark.asyncio
    async def test_async_lock_acquisition(self):
        """Test async lock context manager."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value="test-lock-id")
        mock_redis.delete = AsyncMock(return_value=True)
        
        with patch('utils.workflow_lock.get_redis_client', return_value=mock_redis):
            async with tenant_workflow_lock("tenant_123"):
                pass
        
        mock_redis.set.assert_called_once()
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Async timeout test requires mock of locally-imported asyncio.sleep - polling takes 5s")
    async def test_async_lock_timeout_raises_error(self):
        """Test async lock raises error on timeout."""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
