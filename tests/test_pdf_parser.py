"""
Test for the enhanced PDF parser with LLM structured output.
"""
import pytest
import logging
from unittest.mock import Mock, patch, mock_open
import json

logger = logging.getLogger(__name__)

from utils.pdf_parser import (
    extract_text_from_pdf,
    extract_text_with_ocr,
    parse_invoice_with_llm,
    parse_invoice_pdf,
    InvoiceData,
    InvoiceLineItem
)

# Sample invoice text for testing
SAMPLE_INVOICE_TEXT = """
INVOICE #INV-2026-001

From: Acme Corporation
123 Business Ave
New York, NY 10001

To: XYZ Company
456 Client St
Los Angeles, CA 90001

Invoice Date: March 28, 2026
Due Date: April 27, 2026

Description: Consulting Services

Quantity    Description              Unit Price    Amount
2           Software Development     $150.00       $300.00
1           Project Management       $200.00       $200.00

Subtotal:                           $500.00
Tax (10%):                          $50.00
Total Due:                          $550.00

Thank you for your business!
"""

# Expected parsed result
EXPECTED_PARSED = {
    "vendor_name": "Acme Corporation",
    "invoice_number": "INV-2026-001",
    "invoice_date": "2026-03-28",
    "due_date": "2026-04-27",
    "amount_due": 550.0,
    "currency": "USD",
    "line_items": [
        {
            "description": "Software Development",
            "quantity": 2.0,
            "unit_price": 150.0,
            "amount": 300.0
        },
        {
            "description": "Project Management",
            "quantity": 1.0,
            "unit_price": 200.0,
            "amount": 200.0
        }
    ],
    "description": "INVOICE #INV-2026-001\n\nFrom: Acme Corporation\n123 Business Ave\nNew York, NY 10001\n\nTo: XYZ Company\n456 Client St\nLos Angeles, CA 90001\n\nInvoice Date: March 28, 2026\nDue Date: April 27, 2026\n\nDescription: Consulting Services\n\nQuantity    Description              Unit Price    Amount\n2           Software Development     $150.00       $300.00\n1           Project Management       $200.00       $200.00\n\nSubtotal:                           $500.00\nTax (10%):                          $50.00\nTotal Due:                          $550.00\n\nThank you for your business!",
    "confidence_score": 0.9  # This will vary based on LLM
}

def test_extract_text_from_pdf():
    """Test text extraction from PDF (mocked)."""
    with patch('pdfplumber.open') as mock_pdf_open:
        # Mock pdfplumber to return sample text
        mock_page = Mock()
        mock_page.extract_text.return_value = SAMPLE_INVOICE_TEXT
        mock_pdf = Mock()
        mock_pdf.pages = [mock_page]
        mock_pdf_open.return_value.__enter__.return_value = mock_pdf
        
        text = extract_text_from_pdf("/fake/path.pdf")
        assert SAMPLE_INVOICE_TEXT.strip() == text

def test_extract_text_from_pdf_ocr_fallback():
    """Test OCR fallback when pdfplumber returns little text."""
    with patch('pdfplumber.open') as mock_pdf_open, \
         patch('utils.pdf_parser.OCR_AVAILABLE', True), \
         patch('utils.pdf_parser.extract_text_with_ocr') as mock_ocr:
        
        # Mock pdfplumber to return very little text (simulating scanned PDF)
        mock_page = Mock()
        mock_page.extract_text.return_value = " "  # Minimal text
        mock_pdf = Mock()
        mock_pdf.pages = [mock_page]
        mock_pdf_open.return_value.__enter__.return_value = mock_pdf
        
        # Mock OCR to return our sample text
        mock_ocr.return_value = SAMPLE_INVOICE_TEXT
        
        text = extract_text_from_pdf("/fake/scanned.pdf")
        assert text == SAMPLE_INVOICE_TEXT.strip()
        mock_ocr.assert_called_once_with("/fake/scanned.pdf")

def test_parse_invoice_with_llm():
    """Test LLM-based structured parsing."""
    with patch('utils.pdf_parser.get_llm') as mock_get_llm:
        # Mock LLM and parser
        mock_llm = Mock()
        mock_llm.invoke.return_value = json.dumps({
            "vendor_name": "Acme Corporation",
            "invoice_number": "INV-2026-001",
            "invoice_date": "2026-03-28",
            "due_date": "2026-04-27",
            "amount_due": 550.0,
            "currency": "USD",
            "line_items": [
                {"description": "Software Development", "quantity": 2.0, "unit_price": 150.0, "amount": 300.0},
                {"description": "Project Management", "quantity": 1.0, "unit_price": 200.0, "amount": 200.0}
            ],
            "description": "Test description"
        })
        mock_get_llm.return_value = mock_llm
        
        # Mock the JsonOutputParser to avoid complex setup
        with patch('utils.pdf_parser.JsonOutputParser') as mock_parser_class:
            mock_parser = Mock()
            mock_parser.parse.return_value = Mock()
            mock_parser.parse.return_value.dict.return_value = {
                "vendor_name": "Acme Corporation",
                "invoice_number": "INV-2026-001",
                "invoice_date": "2026-03-28",
                "due_date": "2026-04-27",
                "amount_due": 550.0,
                "currency": "USD",
                "line_items": [
                    {"description": "Software Development", "quantity": 2.0, "unit_price": 150.0, "amount": 300.0},
                    {"description": "Project Management", "quantity": 1.0, "unit_price": 200.0, "amount": 200.0}
                ],
                "description": "Test description",
                "confidence_score": 0.95
            }
            mock_parser_class.return_value = mock_parser
            
            result = parse_invoice_with_llm(SAMPLE_INVOICE_TEXT)
            
            assert result is not None
            assert result["vendor_name"] == "Acme Corporation"
            assert result["invoice_number"] == "INV-2026-001"
            assert result["amount_due"] == 550.0
            assert len(result["line_items"]) == 2

def test_parse_invoice_pdf_rule_based():
    """Test rule-based parsing fallback."""
    result = parse_invoice_pdf_rule_based(SAMPLE_INVOICE_TEXT, "/fake/path.pdf")
    
    # Check that we extracted the key fields correctly
    assert result["vendor_name"] == "Acme Corporation"
    assert result["invoice_number"] == "INV-2026-001"
    assert result["invoice_date"] == "2026-03-28"
    assert result["due_date"] == "2026-04-27"
    assert result["amount_due"] == 550.0
    assert result["currency"] == "USD"
    assert len(result["line_items"]) == 2
    assert result["line_items"][0]["description"] == "Software Development"
    assert result["line_items"][0]["quantity"] == 2.0
    assert result["line_items"][0]["amount"] == 300.0

def test_parse_invoice_pdf_integration():
    """Test the main parse_invoice_pdf function."""
    with patch('utils.pdf_parser.extract_text_from_pdf') as mock_extract, \
         patch('utils.pdf_parser.parse_invoice_with_llm') as mock_llm_parse:
        
        # Mock text extraction
        mock_extract.return_value = SAMPLE_INVOICE_TEXT
        
        # Mock LLM parsing to return high confidence result
        mock_llm_parse.return_value = {
            "vendor_name": "Acme Corporation",
            "invoice_number": "INV-2026-001",
            "invoice_date": "2026-03-28",
            "due_date": "2026-04-27",
            "amount_due": 550.0,
            "currency": "USD",
            "line_items": [
                {"description": "Software Development", "quantity": 2.0, "unit_price": 150.0, "amount": 300.0},
                {"description": "Project Management", "quantity": 1.0, "unit_price": 200.0, "amount": 200.0}
            ],
            "description": "Test description",
            "confidence_score": 0.9
        }
        
        result = parse_invoice_pdf("/fake/path.pdf")
        
        # Should use LLM result since confidence is high
        assert result["vendor_name"] == "Acme Corporation"
        assert result["confidence_score"] == 0.9

def test_parse_invoice_pdf_fallback_to_rule_based():
    """Test fallback to rule-based when LLM confidence is low."""
    with patch('utils.pdf_parser.extract_text_from_pdf') as mock_extract, \
         patch('utils.pdf_parser.parse_invoice_with_llm') as mock_llm_parse:
        
        # Mock text extraction
        mock_extract.return_value = SAMPLE_INVOICE_TEXT
        
        # Mock LLM parsing to return low confidence result
        mock_llm_parse.return_value = {
            "vendor_name": "Acme Corporation",
            "confidence_score": 0.2  # Low confidence
        }
        
        result = parse_invoice_pdf("/fake/path.pdf")
        
        # Should fall back to rule-based parsing
        assert result["vendor_name"] == "Acme Corporation"
        assert result["invoice_number"] == "INV-2026-001"  # From rule-based
        assert "confidence_score" not in result or result.get("confidence_score", 0) < 0.5

if __name__ == "__main__":
    pytest.main([__file__])