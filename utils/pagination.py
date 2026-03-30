"""
Pagination and output size utilities for workflow results.
Prevents OOM from unbounded lists and large state checkpoints.
"""
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from config.plan_limits import MAX_RECONCILIATION_ITEMS, MAX_WORKFLOW_OUTPUT_MB

logger = logging.getLogger(__name__)


@dataclass
class PaginatedResult:
    items: List[Any]
    page: int
    page_size: int
    total: int
    has_next: bool


def paginate_results(
    items: List[Any],
    page: int,
    page_size: int = 100,
) -> PaginatedResult:
    """
    Paginate a list of items.

    Args:
        items: Full list of items to paginate
        page: Page number (1-indexed)
        page_size: Number of items per page

    Returns:
        PaginatedResult with items for requested page
    """
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size

    return PaginatedResult(
        items=items[start:end],
        page=page,
        page_size=page_size,
        total=total,
        has_next=end < total,
    )


def truncate_matches(
    matches: List[Dict[str, Any]],
    max_items: int = MAX_RECONCILIATION_ITEMS,
) -> List[Dict[str, Any]]:
    """
    Truncate matches list with warning log if exceeding max.

    Args:
        matches: List of matches to potentially truncate
        max_items: Maximum number of items to keep

    Returns:
        Truncated list of matches
    """
    original_count = len(matches)
    if original_count > max_items:
        logger.warning(
            f"Truncated {original_count} matches to {max_items}",
            extra={
                "original": original_count,
                "truncated_to": max_items,
            }
        )
        return matches[:max_items]
    return matches


def check_output_size(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check if workflow output exceeds size limit.
    Offloads large fields to S3/storage if needed.

    Args:
        state: Workflow state dictionary

    Returns:
        Modified state with large fields offloaded and replaced with URLs
    """
    max_bytes = MAX_WORKFLOW_OUTPUT_MB * 1024 * 1024

    try:
        state_json = json.dumps(state)
        current_size = len(state_json.encode())
    except Exception as e:
        logger.warning(f"Failed to serialize state for size check: {e}")
        return state

    if current_size > max_bytes:
        logger.warning(
            f"Workflow output exceeds {MAX_WORKFLOW_OUTPUT_MB}MB, offloading large fields",
            extra={
                "current_size_mb": round(current_size / (1024 * 1024), 2),
                "max_size_mb": MAX_WORKFLOW_OUTPUT_MB,
            }
        )

        large_fields = ["matches", "discrepancies", "chasing_data", "reporting_data"]
        offloaded_refs: Dict[str, str] = {}

        for field in large_fields:
            if field in state and state[field]:
                try:
                    field_json = json.dumps(state[field])
                    field_size = len(field_json.encode())
                    if field_size > 1024 * 1024:
                        url = _offload_to_storage(field, field_json)
                        offloaded_refs[field] = url
                        state[field] = f"[OFFLOADED:{field}:{url}]"
                        logger.info(f"Offloaded {field} ({field_size} bytes) to {url}")
                except Exception as e:
                    logger.warning(f"Failed to offload {field}: {e}")

    return state


def _offload_to_storage(field_name: str, content: str) -> str:
    """
    Offload content to S3 or similar storage.
    Returns the reference URL.

    This is a placeholder - implement actual S3/gcs upload based on infrastructure.
    """
    try:
        import boto3
        import uuid
        from datetime import datetime

        bucket = "invoice-handler-workflow-outputs"
        key = f"{datetime.utcnow().strftime('%Y%m%d')}/{uuid.uuid4()}_{field_name}.json"

        s3_client = boto3.client("s3")
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode(),
            ContentType="application/json",
        )

        return f"s3://{bucket}/{key}"
    except Exception as e:
        logger.error(f"S3 offload failed, using fallback: {e}")
        return f"memory://{field_name}_{uuid.uuid4()}"
