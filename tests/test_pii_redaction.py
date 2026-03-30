"""
Tests for PII redaction utilities.
"""
import pytest
from datetime import datetime, date
from decimal import Decimal
from typing import List, Dict, Any
from pydantic import BaseModel

from utils.pii_redactor import (
    deep_redact,
    PII_FIELDS,
    sanitize_for_llm,
    _matches_pii_value,
)


class TestDeepRedact:
    """Test suite for deep_redact function."""
    
    def test_redacts_vendor_email_by_key(self):
        """Test that vendor_email is redacted by key name."""
        data = {"vendor_email": "john@example.com", "vendor_name": "Acme Corp"}
        result = deep_redact(data)
        
        assert result["vendor_email"] == "[REDACTED]"
        assert result["vendor_name"] == "Acme Corp"
        assert data["vendor_email"] == "john@example.com"  # Original unchanged
    
    def test_redacts_vendor_phone_by_key(self):
        """Test that vendor_phone is redacted by key name."""
        data = {"vendor_phone": "555-123-4567", "vendor_name": "Acme Corp"}
        result = deep_redact(data)
        
        assert result["vendor_phone"] == "[REDACTED]"
        assert result["vendor_name"] == "Acme Corp"
    
    def test_redacts_ssn_by_pattern(self):
        """Test that SSN is redacted by pattern match."""
        data = {"description": "Patient SSN: 123-45-6789 for records"}
        result = deep_redact(data)
        
        assert "[REDACTED]" in result["description"]
        assert "123-45-6789" not in result["description"]
    
    def test_redacts_credit_card_by_pattern(self):
        """Test that credit card numbers are redacted by pattern."""
        data = {"notes": "Card on file: 4111-1111-1111-1111"}
        result = deep_redact(data)
        
        assert "[REDACTED]" in result["notes"]
        assert "4111-1111-1111-1111" not in result["notes"]
    
    def test_redacts_email_by_pattern(self):
        """Test that email addresses are redacted by pattern."""
        data = {"contact": "Please contact john.doe@company.co.uk"}
        result = deep_redact(data)
        
        assert "[REDACTED]" in result["contact"]
        assert "john.doe@company.co.uk" not in result["contact"]
    
    def test_handles_nested_dict_10_levels(self):
        """Test nested dicts up to 10 levels deep."""
        def create_nested(level: int) -> Dict[str, Any]:
            if level == 0:
                return {"vendor_email": "test@example.com"}
            return {"level": level, "data": create_nested(level - 1)}
        
        nested = create_nested(10)
        result = deep_redact(nested)
        
        assert result["data"]["data"]["data"]["data"]["data"]["data"]["data"]["data"]["data"]["data"]["vendor_email"] == "[REDACTED]"
    
    def test_does_not_mutate_original(self):
        """Test that original object is never mutated."""
        original = {"vendor_email": "test@example.com", "name": "Test"}
        result = deep_redact(original)
        
        assert original["vendor_email"] == "test@example.com"
        assert result["vendor_email"] == "[REDACTED]"
    
    def test_handles_list_of_dicts(self):
        """Test redaction in lists of dictionaries."""
        data = [
            {"vendor_email": "a@test.com", "name": "A"},
            {"vendor_email": "b@test.com", "name": "B"},
        ]
        result = deep_redact(data)
        
        assert result[0]["vendor_email"] == "[REDACTED]"
        assert result[1]["vendor_email"] == "[REDACTED]"
        assert result[0]["name"] == "A"
    
    def test_handles_pydantic_model(self):
        """Test redaction of Pydantic models."""
        class Invoice(BaseModel):
            vendor_email: str
            vendor_name: str
            amount: Decimal
        
        invoice = Invoice(vendor_email="test@example.com", vendor_name="Test", amount=Decimal("100.00"))
        result = deep_redact(invoice)
        
        assert result.vendor_email == "[REDACTED]"
        assert result.vendor_name == "Test"
        assert invoice.vendor_email == "test@example.com"  # Original unchanged
    
    def test_redacts_access_token_by_key(self):
        """Test that access_token is redacted by key name."""
        data = {"access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."}
        result = deep_redact(data)
        
        assert result["access_token"] == "[REDACTED]"
    
    def test_redacts_sensitive_fields(self):
        """Test redaction of various sensitive fields."""
        sensitive_data = {
            "ssn": "123-45-6789",
            "tax_id": "12-3456789",
            "bank_account": "123456789",
            "routing_number": "021000021",
            "plaid_token": "plaid-sandbox-xxx",
            "client_secret": "sk-xxx",
            "api_key": "sk-xxx",
            "account_number": "12345678",
        }
        result = deep_redact(sensitive_data)
        
        for key in sensitive_data:
            assert result[key] == "[REDACTED]", f"Field {key} should be redacted"


class TestSanitizeForLlm:
    """Test suite for sanitize_for_llm function."""
    
    def test_keeps_only_safe_fields(self):
        """Test that only LLM-safe fields are kept."""
        invoice = {
            "vendor_name": "Acme Corp",
            "amount_due": 100.00,
            "due_date": "2024-12-31",
            "invoice_number": "INV-001",
            "line_items": "Item 1, Item 2",
            "currency": "USD",
            "vendor_email": "secret@example.com",
            "vendor_phone": "555-123-4567",
        }
        
        result = sanitize_for_llm(invoice)
        
        assert "vendor_name" in result
        assert "amount_due" in result
        assert "vendor_email" not in result
        assert "vendor_phone" not in result
    
    def test_redacts_pii_in_safe_fields(self):
        """Test that PII patterns in safe fields are still redacted."""
        invoice = {
            "vendor_name": "Contact john@evil.com for payment",
            "description": "SSN in description: 123-45-6789",
        }
        
        result = sanitize_for_llm(invoice)
        
        assert "[REDACTED]" in result["vendor_name"]
        assert "[REDACTED]" in result["description"]


class TestMatchesPiiValue:
    """Test suite for PII value pattern matching."""
    
    def test_matches_email_pattern(self):
        """Test email pattern detection."""
        assert _matches_pii_value("test@example.com")
        assert _matches_pii_value("user.name@company.co.uk")
        assert not _matches_pii_value("not an email")
    
    def test_matches_phone_pattern(self):
        """Test phone pattern detection."""
        assert _matches_pii_value("555-123-4567")
        assert _matches_pii_value("555 123 4567")
        assert _matches_pii_value("5551234567")
        assert not _matches_pii_value("123456")
    
    def test_matches_ssn_pattern(self):
        """Test SSN pattern detection."""
        assert _matches_pii_value("123-45-6789")
        assert not _matches_pii_value("123456789")
    
    def test_matches_credit_card_pattern(self):
        """Test credit card pattern detection."""
        assert _matches_pii_value("4111-1111-1111-1111")
        assert _matches_pii_value("4111 1111 1111 1111")
        assert _matches_pii_value("4111111111111111")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
