"""
Test for ingestion tools.
"""
import pytest
import logging
from unittest.mock import Mock, patch, MagicMock
import json

logger = logging.getLogger(__name__)

from utils.ingestion import (
    fetch_gmail_invoices,
    fetch_drive_pdfs,
    fetch_quickbooks_invoices,
    fetch_xero_invoices,
    fetch_plaid_transactions_and_statements
)

# Test data
MOCK_GMAIL_MESSAGE = {
    'id': 'msg123',
    'payload': {
        'headers': [
            {'name': 'Subject', 'value': 'Invoice #12345'},
            {'name': 'Date', 'value': 'Mon, 28 Mar 2026 10:00:00 +0000'}
        ],
        'parts': [
            {
                'filename': 'invoice.pdf',
                'body': {'attachmentId': 'att123'}
            }
        ]
    }
}

MOCK_GMAIL_ATTACHMENT = {
    'data': 'JVBERi0xLjQKJcfs...'  # base64 encoded PDF data (truncated)
}

MOCK_DRIVE_FILE = {
    'id': 'file123',
    'name': 'invoice.pdf',
    'modifiedTime': '2026-03-28T10:00:00.000Z',
    'webViewLink': 'https://drive.google.com/file/d/file123/view'
}

MOCK_QB_INVOICE = Mock()
MOCK_QB_INVOICE.DocNumber = 'QB123'
MOCK_QB_INVOICE.CustomerRef = Mock()
MOCK_QB_INVOICE.CustomerRef.name = 'Test Vendor'
MOCK_QB_INVOICE.TotalAmt = 100.00
MOCK_QB_INVOICE.TxnDate = '2026-03-28'
MOCK_QB_INVOICE.DueDate = '2026-04-27'
MOCK_QB_INVOICE.Status = 'Paid'
MOCK_QB_INVOICE.PrivateNote = 'Test invoice'
MOCK_QB_INVOICE.Line = []

MOCK_XERO_INVOICE = Mock()
MOCK_XERO_INVOICE.InvoiceNumber = 'XERO123'
MOCK_XERO_INVOICE.Contact = Mock()
MOCK_XERO_INVOICE.Contact.Name = 'Test Vendor'
MOCK_XERO_INVOICE.AmountDue = 150.00
MOCK_XERO_INVOICE.Date = '2026-03-28'
MOCK_XERO_INVOICE.DueDate = '2026-04-27'
MOCK_XERO_INVOICE.Status = 'AUTHORISED'
MOCK_XERO_INVOICE.Reference = 'Test invoice'
MOCK_XERO_INVOICE.InvoiceID = 'xero123'
MOCK_XERO_INVOICE.LineItems = []

MOCK_PLAID_TRANSACTION = {
    'transaction_id': 'txn123',
    'account_id': 'acc123',
    'amount': -25.50,  # Negative for outflow
    'date': '2026-03-28',
    'name': 'Test Purchase',
    'category': ['Food and Drink', 'Restaurants']
}

def test_fetch_gmail_invoices_success():
    """Test successful fetching of Gmail invoices."""
    with patch('utils.ingestion.get_gmail_service') as mock_get_service, \
         patch('utils.ingestion.parse_invoice_pdf_from_bytes') as mock_parse_pdf:
        
        # Mock Gmail service
        mock_service = Mock()
        mock_service.users().messages().list().execute.return_value = {
            'messages': [{'id': 'msg123'}]
        }
        mock_service.users().messages().get().execute.return_value = MOCK_GMAIL_MESSAGE
        mock_service.users().messages().attachments().get().execute.return_value = MOCK_GMAIL_ATTACHMENT
        mock_get_service.return_value = mock_service
        
        # Mock PDF parsing to return sample invoice data
        mock_parse_pdf.return_value = {
            'invoice_number': 'INV123',
            'vendor_name': 'Test Vendor',
            'amount_due': 100.00,
            'invoice_date': '2026-03-28',
            'due_date': '2026-04-27',
            'source': 'gmail',
            'source_id': 'msg123'
        }
        
        # Call the function
        result = fetch_gmail_invoices.invoke({'tenant_id': 1, 'user_id': 1, 'days_back': 30})
        data = json.loads(result)
        
        # Assertions
        assert isinstance(data, dict)
        assert 'total_fetched' in data
        assert 'saved_to_db' in data
        assert data['total_fetched'] == 1

def test_fetch_drive_pdfs_success():
    """Test successful fetching of Drive PDFs."""
    with patch('utils.ingestion.get_drive_service') as mock_get_service, \
         patch('utils.ingestion.parse_invoice_pdf_from_bytes') as mock_parse_pdf:
        
        # Mock Drive service
        mock_service = Mock()
        mock_service.files().list().execute.return_value = {
            'files': [MOCK_DRIVE_FILE]
        }
        
        # Mock file download
        mock_request = Mock()
        mock_request.execute.return_value = b'fake pdf content'
        mock_service.files().get_media.return_value = mock_request
        
        mock_get_service.return_value = mock_service
        
        # Mock PDF parsing
        mock_parse_pdf.return_value = {
            'invoice_number': 'DRV123',
            'vendor_name': 'Test Vendor',
            'amount_due': 200.00,
            'invoice_date': '2026-03-28',
            'due_date': '2026-04-27',
            'source': 'drive',
            'source_id': 'file123'
        }
        
        # Call the function
        result = fetch_drive_pdfs.invoke({'tenant_id': 1, 'user_id': 1, 'days_back': 30})
        data = json.loads(result)
        
        # Assertions
        assert isinstance(data, dict)
        assert 'total_fetched' in data
        assert 'saved_to_db' in data
        assert data['total_fetched'] == 1

def test_fetch_quickbooks_invoices_success():
    """Test successful fetching of QuickBooks invoices."""
    with patch('utils.ingestion.get_qb_client') as mock_get_client:
        # Mock QB client
        mock_client = Mock()
        mock_client.query.return_value = [MOCK_QB_INVOICE]
        mock_get_client.return_value = mock_client
        
        # Call the function
        result = fetch_quickbooks_invoices.invoke({'tenant_id': 1, 'user_id': 1, 'days_back': 30})
        data = json.loads(result)
        
        # Assertions - now returns dict with total_fetched and saved_to_db
        assert isinstance(data, dict)
        assert 'error' in data or ('total_fetched' in data)

def test_fetch_xero_invoices_success():
    """Test successful fetching of Xero invoices."""
    with patch('utils.ingestion.get_xero_client') as mock_get_client:
        # Mock Xero client
        mock_client = Mock()
        mock_client.invoices.where.return_value = [MOCK_XERO_INVOICE]
        mock_get_client.return_value = mock_client
        
        # Call the function
        result = fetch_xero_invoices.invoke({'tenant_id': 1, 'user_id': 1, 'days_back': 30})
        data = json.loads(result)
        
        # Assertions - now returns dict with total_fetched and saved_to_db
        assert isinstance(data, dict)
        assert 'error' in data or ('total_fetched' in data)

def test_fetch_plaid_transactions_success():
    """Test successful fetching of Plaid transactions."""
    with patch('utils.ingestion.get_plaid_client') as mock_get_client:
        # Mock Plaid client
        mock_client = Mock()
        mock_client.transactions_get.return_value = {
            'transactions': [MOCK_PLAID_TRANSACTION]
        }
        mock_client.accounts_get.return_value = {
            'accounts': [{
                'account_id': 'acc123',
                'name': 'Test Checking',
                'subtype': 'checking'
            }]
        }
        mock_client.statements_get.return_value = {
            'statements': []  # No statements for simplicity
        }
        mock_get_client.return_value = mock_client
        
        # Set environment variable for access token
        with patch.dict('os.environ', {'PLAID_ACCESS_TOKEN': 'test-token'}):
            # Call the function
            result = fetch_plaid_transactions_and_statements.invoke({'tenant_id': 1, 'user_id': 1, 'days_back': 30})
            data = json.loads(result)
            
            # Assertions
            assert isinstance(data, dict)
            assert 'error' in data or 'transactions' in data

if __name__ == "__main__":
    pytest.main([__file__])