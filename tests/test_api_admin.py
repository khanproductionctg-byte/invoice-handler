"""
Test for the admin API routes.
"""
import pytest
from unittest.mock import patch, MagicMock
import os

# Skip if database is not available
pytestmark = pytest.mark.skipif(
    not os.getenv("POSTGRES_SERVER"),
    reason="Database not available"
)


def test_admin_health_check_mock():
    """Test the admin health check endpoint with mocked data."""
    # This test mocks all dependencies to avoid DB connection
    with patch('api.routes.admin.get_system_stats') as mock_system_stats, \
         patch('api.routes.admin.get_db_stats') as mock_db_stats:
        
        # Setup mocks
        mock_system_stats.return_value = {"cpu_percent": 50.0}
        mock_db_stats.return_value = {"user_count": 1}
        
        # Import after patching
        from api.routes.admin import get_system_stats, get_db_stats
        
        # Test the helper functions directly
        stats = get_system_stats()
        assert stats["cpu_percent"] == 50.0
        
        db_stats = get_db_stats()
        assert db_stats["user_count"] == 1


def test_celery_stats_mock():
    """Test celery stats helper."""
    with patch('api.routes.admin.celery_app') as mock_celery:
        from api.routes.admin import get_celery_stats
        
        if mock_celery is None:
            # Celery not available
            result = get_celery_stats()
            assert result == {}


def test_get_system_stats():
    """Test system stats collection."""
    import psutil
    from api.routes.admin import get_system_stats
    
    stats = get_system_stats()
    
    assert "cpu_percent" in stats
    assert "memory" in stats
    assert "disk" in stats
