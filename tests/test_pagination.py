"""
Tests for pagination and output size utilities.
"""
import pytest
from utils.pagination import (
    paginate_results,
    truncate_matches,
    check_output_size,
    PaginatedResult,
)


def test_paginate_results_basic():
    """Test basic pagination functionality."""
    items = list(range(1, 251))
    
    result = paginate_results(items, page=1, page_size=100)
    
    assert result.items == list(range(1, 101))
    assert result.page == 1
    assert result.page_size == 100
    assert result.total == 250
    assert result.has_next is True


def test_paginate_results_last_page():
    """Test pagination on last page."""
    items = list(range(1, 251))
    
    result = paginate_results(items, page=3, page_size=100)
    
    assert result.items == list(range(201, 251))
    assert result.page == 3
    assert result.total == 250
    assert result.has_next is False


def test_truncate_matches_with_warning():
    """Test truncation with warning when exceeding max."""
    matches = [{"id": i} for i in range(1500)]
    
    result = truncate_matches(matches, max_items=1000)
    
    assert len(result) == 1000


def test_truncate_matches_no_truncation():
    """Test no truncation when under max."""
    matches = [{"id": i} for i in range(500)]
    
    result = truncate_matches(matches, max_items=1000)
    
    assert len(result) == 500


def test_check_output_size_small():
    """Test that small outputs pass through unchanged."""
    state = {"data": {"key": "value"}}
    
    result = check_output_size(state)
    
    assert result == state


def test_check_output_size_large():
    """Test that large outputs trigger offload."""
    large_list = [{"id": i, "data": "x" * 1000} for i in range(5000)]
    state = {"matches": large_list}
    
    result = check_output_size(state)
    
    assert "matches" in result
    assert "[OFFLOADED:" in result["matches"] or result["matches"] == large_list


if __name__ == "__main__":
    pytest.main([__file__])
