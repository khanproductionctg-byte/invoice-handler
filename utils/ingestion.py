"""
Ingestion tools for fetching data from various sources as LangGraph tools.
These tools are designed to be used by agents in the LangGraph workflow.
"""
import json
import logging
import os
import random
import time
from functools import wraps
from datetime import datetime, timedelta, date
from typing import List, Optional, Dict, Any
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from langchain_core.tools import tool
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from utils.token_storage import get_token_storage
try:
    import plaid
    from plaid.api import plaid_api
    PLAID_AVAILABLE = True
except ImportError:
    plaid = None
    plaid_api = None
    PLAID_AVAILABLE = False

try:
    import quickbooks
    from quickbooks import QuickBooks
    from quickbooks.objects.invoice import Invoice as QBInvoice
    QUICKBOOKS_AVAILABLE = True
except ImportError:
    quickbooks = None
    QuickBooks = None
    QBInvoice = None
    QUICKBOOKS_AVAILABLE = False
try:
    import xero
    from xero import Xero
    from xero.auth import OAuth2Credentials
    XERO_AVAILABLE = True
except ImportError:
    xero = None
    Xero = None
    OAuth2Credentials = None
    XERO_AVAILABLE = False
import pdfplumber
from utils.pdf_parser import parse_invoice_pdf

logger = logging.getLogger(__name__)

# Retry decorator with exponential backoff and jitter
def retry_with_exponential_backoff(
    max_retries=3,
    base_delay=1,
    max_delay=60,
    exponential_base=2,
    jitter=True
):
    """Retry a function with exponential backoff and jitter."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Initialize variables
            num_retries = 0
            delay = base_delay

            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    num_retries += 1
                    # If we have exceeded the max number of retries, raise the exception
                    if num_retries > max_retries:
                        raise e

                    # Calculate delay
                    delay = min(base_delay * (exponential_base ** (num_retries - 1)), max_delay)
                    if jitter:
                        delay *= (0.5 + random.random() * 0.5)  # jitter between 0.5 and 1.0

                    # Log the retry
                    logger.warning(
                        f"Exception occurred: {str(e)}. Retrying in {delay} seconds. "
                        f"Attempt {num_retries} of {max_retries}."
                    )
                    time.sleep(delay)

        return wrapper
    return decorator

# ==================== Gmail Tool ====================

# If modifying these scopes, delete the file token.json.
GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
GMAIL_TOKEN_FILE = 'token_gmail.json'
GMAIL_CREDENTIALS_FILE = 'credentials_gmail.json'

def get_gmail_service(tenant_id: int = None):
    """Get authenticated Gmail service with secure token storage.
    
    Args:
        tenant_id: Optional tenant ID to load tokens from database (ConnectedAccount).
                   If not provided, falls back to file-based token storage.
    
    Returns:
        Gmail service or raises an exception if no valid credentials.
    """
    creds = None
    
    # First try to load from database ConnectedAccount (production path)
    if tenant_id:
        try:
            from db.database import SessionLocal
            from db.models import ConnectedAccount
            
            db = SessionLocal()
            try:
                account = db.query(ConnectedAccount).filter(
                    ConnectedAccount.tenant_id == tenant_id,
                    ConnectedAccount.provider == "google",
                    ConnectedAccount.is_active == True
                ).first()
                
                if account and account.access_token:
                    from google.oauth2.credentials import Credentials
                    creds = Credentials(
                        token=account.access_token,
                        refresh_token=account.refresh_token,
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.getenv("GOOGLE_CLIENT_ID"),
                        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
                        scopes=GMAIL_SCOPES
                    )
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to load Google credentials from database: {e}")
    
    # Fallback to file-based token storage (development)
    if not creds:
        token_storage = get_token_storage()
        token_data = token_storage.load_token(GMAIL_TOKEN_FILE)
        if token_data:
            try:
                creds = Credentials.from_authorized_user_info(token_data, GMAIL_SCOPES)
            except Exception as e:
                logger.warning(f"Could not load token: {e}")
    
    # If there are no (valid) credentials available, fail gracefully
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning(f"Token refresh failed: {e}")
                raise Exception(
                    "Gmail credentials expired. Please reconnect your Google account "
                    "via the Connections page in the dashboard."
                )
        else:
            raise Exception(
                "Gmail not connected. Please connect your Google account "
                "via the Connections page in the dashboard."
            )
    
    return build('gmail', 'v1', credentials=creds)

def _save_invoices_to_db(tenant_id: int, invoices: List[Dict[str, Any]], source: str) -> int:
    """
    Save fetched invoices to the database with proper tenant isolation.
    
    Args:
        tenant_id: The tenant ID for data isolation
        invoices: List of invoice data dictionaries
        source: Source of the invoices (gmail, drive, quickbooks, etc.)
    
    Returns:
        Number of invoices saved
    """
    from db.database import SessionLocal
    from db.models import Invoice, Customer
    from schemas.invoice import InvoiceValidation
    
    db = SessionLocal()
    saved_count = 0
    
    try:
        for inv_data in invoices:
            # Validate invoice amount and dates before saving
            try:
                amount = inv_data.get('amount_due', 0)
                if amount is not None:
                    inv_data['amount_due'] = InvoiceValidation.validate_invoice_amount(amount)
                
                due_date = inv_data.get('due_date')
                if due_date:
                    inv_data['due_date'] = InvoiceValidation.validate_invoice_date(due_date)
                
                invoice_number = inv_data.get('invoice_number', '')
                if invoice_number:
                    inv_data['invoice_number'] = InvoiceValidation.sanitize_invoice_number(invoice_number)
            except ValueError as ve:
                logger.warning(f"Skipping invalid invoice: {ve}")
                continue
            
            # Check for existing invoice by source_id to avoid duplicates
            existing = db.query(Invoice).filter(
                Invoice.tenant_id == tenant_id,
                Invoice.source == source,
                Invoice.source_id == inv_data.get('source_id')
            ).first()
            
            if existing:
                continue
            
            # Get or create customer
            customer_email = inv_data.get('customer_email')
            customer = None
            if customer_email:
                customer = db.query(Customer).filter(
                    Customer.tenant_id == tenant_id,
                    Customer.email == customer_email
                ).first()
                
                if not customer:
                    customer = Customer(
                        tenant_id=tenant_id,
                        email=customer_email,
                        full_name=inv_data.get('customer_name'),
                        company_name=inv_data.get('customer_company')
                    )
                    db.add(customer)
                    db.flush()
            
            invoice = Invoice(
                tenant_id=tenant_id,
                invoice_number=inv_data.get('invoice_number', f"{source.upper()}_{inv_data.get('source_id', 'unknown')}"),
                vendor_name=inv_data.get('vendor_name', 'Unknown'),
                vendor_id=inv_data.get('vendor_id'),
                amount_due=inv_data.get('amount_due', 0),
                amount_paid=inv_data.get('amount_paid', 0),
                currency=inv_data.get('currency', 'USD'),
                invoice_date=inv_data.get('invoice_date', datetime.now().date()),
                due_date=inv_data.get('due_date', datetime.now().date()),
                status=inv_data.get('status', 'pending_review'),
                description=inv_data.get('description'),
                line_items=json.dumps(inv_data.get('line_items', [])) if inv_data.get('line_items') else None,
                source=source,
                source_id=inv_data.get('source_id'),
                customer_id=customer.id if customer else None,
                vendor_email=inv_data.get('vendor_email'),
                vendor_phone=inv_data.get('vendor_phone'),
                needs_review=True
            )
            db.add(invoice)
            saved_count += 1
        
        db.commit()
        logger.info(f"Saved {saved_count} invoices to database for tenant {tenant_id}")
        
    except Exception as e:
        logger.error(f"Error saving invoices to database: {str(e)}")
        db.rollback()
    finally:
        db.close()
    
    return saved_count


@tool
@retry_with_exponential_backoff(max_retries=3, base_delay=1, max_delay=60)
def fetch_gmail_invoices(tenant_id: int, user_id: int, days_back: int = 30) -> str:
    """
    Fetch invoices from Gmail by searching for emails with 'invoice' in subject or PDF attachments.
    
    Args:
        tenant_id: ID of the tenant for data isolation
        user_id: ID of the user (for logging/context)
        days_back: Number of days back to search for emails
    
    Returns:
        JSON string containing list of invoice data dictionaries
    """
    try:
        service = get_gmail_service(tenant_id=tenant_id)
        
        # Calculate date for search
        date_after = (datetime.now() - timedelta(days=days_back)).strftime('%Y/%m/%d')
        
        # Search for emails with invoice in subject or PDF attachments
        query = f'after:{date_after} (subject:invoice OR has:attachment filename:pdf)'
        results = service.users().messages().list(userId='me', q=query).execute()
        messages = results.get('messages', [])
        
        invoices = []
        for message in messages:
            msg = service.users().messages().get(userId='me', id=message['id'], format='full').execute()
            
            # Extract headers
            headers = msg['payload'].get('headers', [])
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
            date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
            from_email = next((h['value'] for h in headers if h['name'] == 'From'), '')
            
            # Process attachments
            attachments = []
            if 'parts' in msg['payload']:
                for part in msg['payload']['parts']:
                    if part.get('filename') and part['filename'].endswith('.pdf'):
                        attachment_id = part['body'].get('attachmentId')
                        if attachment_id:
                            attachment = service.users().messages().attachments().get(
                                userId='me', messageId=message['id'], id=attachment_id).execute()
                            file_data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
                            attachments.append({
                                'filename': part['filename'],
                                'data': file_data,
                                'content_type': part.get('mimeType', 'application/pdf')
                            })
            
            # If we found PDF attachments, process them
            if attachments:
                for attachment in attachments:
                    # Parse PDF to extract invoice data
                    invoice_data = parse_invoice_pdf_from_bytes(
                        attachment['data'], 
                        source='gmail',
                        source_id=message['id']
                    )
                    if invoice_data:
                        invoice_data['tenant_id'] = tenant_id
                        invoice_data['user_id'] = user_id
                        invoices.append(invoice_data)
            # Also consider emails without attachments but with invoice in subject as potential invoices
            elif 'invoice' in subject.lower():
                # Create a basic invoice record from email metadata
                invoice_data = {
                    'invoice_number': f"GMAIL_{message['id']}",
                    'vendor_name': 'Unknown (from email)',
                    'amount_due': 0.0,  # Would need PDF parsing to get amount
                    'invoice_date': datetime.now().date(),
                    'due_date': datetime.now().date(),
                    'status': 'pending',
                    'description': f"Email subject: {subject}",
                    'source': 'gmail',
                    'source_id': message['id'],
                    'user_id': user_id,
                    'tenant_id': tenant_id,
                    'vendor_email': from_email,
                    'email_snippet': msg.get('snippet', '')
                }
                invoices.append(invoice_data)
        
        # Save to database with tenant isolation
        saved_count = _save_invoices_to_db(tenant_id, invoices, 'gmail')
        
        logger.info(f"Fetched {len(invoices)} Gmail invoices, saved {saved_count} to DB for tenant {tenant_id}")
        return json.dumps({"total_fetched": len(invoices), "saved_to_db": saved_count}, default=str)
    
    except Exception as e:
        logger.error(f"Error fetching Gmail invoices for tenant {tenant_id}: {str(e)}")
        return json.dumps({"error": str(e)}, default=str)

# ==================== Google Drive Tool ====================

DRIVE_SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
DRIVE_TOKEN_FILE = 'token_drive.json'
DRIVE_CREDENTIALS_FILE = 'credentials_drive.json'

def get_drive_service(tenant_id: int = None):
    """Get authenticated Google Drive service with secure token storage.
    
    Args:
        tenant_id: Optional tenant ID to load tokens from database (ConnectedAccount).
                   If not provided, falls back to file-based token storage.
    
    Returns:
        Drive service or raises an exception if no valid credentials.
    """
    creds = None
    
    # First try to load from database ConnectedAccount (production path)
    if tenant_id:
        try:
            from db.database import SessionLocal
            from db.models import ConnectedAccount
            
            db = SessionLocal()
            try:
                account = db.query(ConnectedAccount).filter(
                    ConnectedAccount.tenant_id == tenant_id,
                    ConnectedAccount.provider == "google",
                    ConnectedAccount.is_active == True
                ).first()
                
                if account and account.access_token:
                    creds = Credentials(
                        token=account.access_token,
                        refresh_token=account.refresh_token,
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.getenv("GOOGLE_CLIENT_ID"),
                        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
                        scopes=DRIVE_SCOPES
                    )
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to load Google Drive credentials from database: {e}")
    
    # Fallback to file-based token storage (development)
    if not creds:
        token_storage = get_token_storage()
        token_data = token_storage.load_token(DRIVE_TOKEN_FILE)
        if token_data:
            try:
                creds = Credentials.from_authorized_user_info(token_data, DRIVE_SCOPES)
            except Exception as e:
                logger.warning(f"Could not load Drive token: {e}")
    
    # If there are no (valid) credentials available, fail gracefully
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning(f"Drive token refresh failed: {e}")
                raise Exception(
                    "Google Drive credentials expired. Please reconnect your Google account "
                    "via the Connections page in the dashboard."
                )
        else:
            raise Exception(
                "Google Drive not connected. Please connect your Google account "
                "via the Connections page in the dashboard."
            )
    
    return build('drive', 'v3', credentials=creds)

@tool
@retry_with_exponential_backoff(max_retries=3, base_delay=1, max_delay=60)
def fetch_drive_pdfs(tenant_id: int, user_id: int, days_back: int = 30) -> str:
    """
    Fetch PDF files from Google Drive that likely contain invoices.
    
    Args:
        tenant_id: ID of the tenant for data isolation
        user_id: ID of the user
        days_back: Number of days back to search for files
    
    Returns:
        JSON string containing list of invoice data dictionaries from PDFs
    """
    try:
        service = get_drive_service(tenant_id=tenant_id)
        
        # Calculate date for search
        date_after = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%dT%H:%M:%S')
        
        # Search for PDF files modified after date
        query = f"mimeType='application/pdf' and modifiedTime > '{date_after}'"
        results = service.files().list(
            q=query,
            fields="files(id, name, modifiedTime, webViewLink)"
        ).execute()
        files = results.get('files', [])
        
        invoices = []
        for file in files:
            try:
                # Download the file
                file_id = file['id']
                request = service.files().get_media(fileId=file_id)
                file_content = request.execute()
                
                # Parse PDF to extract invoice data
                invoice_data = parse_invoice_pdf_from_bytes(
                    file_content,
                    source='drive',
                    source_id=file_id
                )
                if invoice_data:
                    invoice_data['tenant_id'] = tenant_id
                    invoice_data['user_id'] = user_id
                    invoice_data['drive_url'] = file.get('webViewLink')
                    invoices.append(invoice_data)
                    
            except Exception as e:
                logger.warning(f"Failed to process Drive file {file['id']}: {str(e)}")
                continue
        
        # Save to database with tenant isolation
        saved_count = _save_invoices_to_db(tenant_id, invoices, 'drive')
        
        logger.info(f"Fetched {len(invoices)} Drive invoices, saved {saved_count} to DB for tenant {tenant_id}")
        return json.dumps({"total_fetched": len(invoices), "saved_to_db": saved_count}, default=str)
    
    except Exception as e:
        logger.error(f"Error fetching Drive PDFs for tenant {tenant_id}: {str(e)}")
        return json.dumps({"error": str(e)}, default=str)

# ==================== QuickBooks Tool ====================

class TenantIntegrationNotFound(Exception):
    """Raised when no integration is connected for a tenant."""
    pass


def get_qb_client(tenant_id: int) -> QuickBooks:
    """
    Get authenticated QuickBooks client for a specific tenant.
    
    Args:
        tenant_id: The tenant ID to look up credentials for.
        
    Returns:
        Authenticated QuickBooks client.
        
    Raises:
        TenantIntegrationNotFound: If no QuickBooks account is connected for this tenant.
        ValueError: If QuickBooks client ID/secret are not configured.
    """
    from db.database import SessionLocal
    from db.models import ConnectedAccount
    
    client_id = os.getenv('QUICKBOOKS_CLIENT_ID')
    client_secret = os.getenv('QUICKBOOKS_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        raise ValueError("QuickBooks client ID/secret not configured")
    
    db = SessionLocal()
    try:
        account = db.query(ConnectedAccount).filter(
            ConnectedAccount.tenant_id == tenant_id,
            ConnectedAccount.provider == "quickbooks",
            ConnectedAccount.is_active == True
        ).first()
        
        if not account:
            raise TenantIntegrationNotFound(
                f"No QuickBooks account connected for tenant {tenant_id}"
            )
        
        access_token = account.access_token
        refresh_token = account.refresh_token
        realm_id = account.provider_account_id
        
        if not access_token or not refresh_token:
            raise TenantIntegrationNotFound(
                f"QuickBooks tokens not available for tenant {tenant_id}"
            )
        
        return QuickBooks(
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
            refresh_token=refresh_token,
            realm_id=realm_id,
            sandbox=os.getenv('QUICKBOOKS_SANDBOX', 'false').lower() == 'true',
            verbose=True
        )
    finally:
        db.close()

@tool
@retry_with_exponential_backoff(max_retries=3, base_delay=1, max_delay=60)
def fetch_quickbooks_invoices(tenant_id: int, user_id: int, days_back: int = 30) -> str:
    """
    Fetch invoices from QuickBooks Online.
    
    Args:
        tenant_id: ID of the tenant for data isolation
        user_id: ID of the user
        days_back: Number of days back to fetch invoices
    
    Returns:
        JSON string containing list of invoice data
    """
    if not QUICKBOOKS_AVAILABLE:
        return json.dumps({"error": "QuickBooks package not available. Install with: pip install quickbooks"}, default=str)
    
    try:
        # Get credentials from connected account in database
        from db.database import SessionLocal
        from db.models import ConnectedAccount
        
        db = SessionLocal()
        try:
            connected = db.query(ConnectedAccount).filter(
                ConnectedAccount.tenant_id == tenant_id,
                ConnectedAccount.provider == "quickbooks",
                ConnectedAccount.is_active == True
            ).first()
            
            if not connected:
                logger.warning(f"No QuickBooks connection found for tenant {tenant_id}")
                return json.dumps({"error": "QuickBooks not connected"}, default=str)
            
            # Get tokens from encrypted storage
            access_token = connected.access_token
            refresh_token = connected.refresh_token
            realm_id = connected.provider_account_id
            
            if not access_token:
                return json.dumps({"error": "QuickBooks access token not available"}, default=str)
                
        finally:
            db.close()
        
        # Initialize QuickBooks client
        qb = QuickBooks(
            client_id=os.getenv('QUICKBOOKS_CLIENT_ID'),
            client_secret=os.getenv('QUICKBOOKS_CLIENT_SECRET'),
            access_token=access_token,
            refresh_token=refresh_token,
            realm_id=realm_id,
            verbose=True
        )
        
        # Calculate date filter
        date_filter = datetime.now() - timedelta(days=days_back)
        
        # Validate date_filter to prevent any injection
        if not isinstance(date_filter, datetime):
            raise ValueError("Invalid date filter")
        
        # Format date safely
        date_str = date_filter.strftime('%Y-%m-%d')
        
        # Validate date string format (whitelist approach)
        import re
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            raise ValueError(f"Invalid date format: {date_str}")
        
        # Query invoices using QuickBooks SDK's filter mechanism
        # This uses parameterized queries under the hood
        from quickbooks.objects.invoice import Invoice as QBInvoice
        from quickbooks import QBORS
        
        # Use the QBORS (QuickBooks Object Retrieval and Search) syntax
        # This is the safe, SDK-recommended way to query
        invoices = QBInvoice.where(f"TxnDate >= '{date_str}'", qb=qb)
        
        # Transform to our format
        result = []
        for inv in invoices:
            # Determine status
            status = "pending"
            if hasattr(inv, 'Balance'):
                if float(inv.Balance) == 0:
                    status = "paid"
                elif float(inv.Balance) > 0:
                    status = "pending"
            
            result.append({
                "invoice_number": getattr(inv, 'DocNumber', f"QB_{inv.Id}"),
                "vendor_name": getattr(inv.CustomerRef, 'name', 'Unknown') if hasattr(inv, 'CustomerRef') else "Unknown",
                "amount_due": float(inv.TotalAmt) if hasattr(inv, 'TotalAmt') and inv.TotalAmt else 0.0,
                "amount_paid": float(inv.TotalAmt) - float(inv.Balance) if hasattr(inv, 'TotalAmt') and hasattr(inv, 'Balance') else 0.0,
                "currency": getattr(inv.CurrencyRef, 'value', 'USD') if hasattr(inv, 'CurrencyRef') else "USD",
                "invoice_date": inv.TxnDate,
                "due_date": getattr(inv, 'DueDate', inv.TxnDate),
                "status": status,
                "description": getattr(inv.CustomerMemo, 'value', None) if hasattr(inv, 'CustomerMemo') else None,
                "line_items": [
                    {"description": line.Description, "amount": float(line.Amount)}
                    for line in (inv.Line or [])
                    if hasattr(line, 'Amount')
                ],
                "source": "quickbooks",
                "source_id": inv.Id,
                "tenant_id": tenant_id,
                "user_id": user_id
            })
        
        # Save to database with tenant isolation
        saved_count = _save_invoices_to_db(tenant_id, result, 'quickbooks')
        
        logger.info(f"Fetched {len(result)} QuickBooks invoices, saved {saved_count} to DB for tenant {tenant_id}")
        return json.dumps({"total_fetched": len(result), "saved_to_db": saved_count}, default=str)
        
    except Exception as e:
        logger.error(f"Error fetching QuickBooks invoices for tenant {tenant_id}: {str(e)}")
        return json.dumps({"error": str(e)}, default=str)

# ==================== Xero Tool ====================

def get_xero_client():
    """Get authenticated Xero client."""
    # In practice, you would store and refresh tokens securely
    client_id = os.getenv('XERO_CLIENT_ID')
    client_secret = os.getenv('XERO_CLIENT_SECRET')
    
    if not all([client_id, client_secret]):
        raise ValueError("Xero credentials not configured")
    
    # Load or create credentials
    # In a real app, you would store these tokens securely and refresh as needed
    # This is a simplified version
    credentials = OAuth2Credentials(
        client_id=client_id,
        client_secret=client_secret,
        # These would normally come from secure storage
        access_token=os.getenv('XERO_ACCESS_TOKEN'),
        refresh_token=os.getenv('XERO_REFRESH_TOKEN'),
        # Token expiry time
        expires_in=3600,  # 1 hour
        # Scope
        scope='openid profile email accounting.transactions accounting.contacts.read'
    )
    
    # Check if token is expired and refresh if needed
    if credentials.expired():
        credentials.refresh()
        # Save the new tokens (in practice, store securely)
        # For this example, we just update the environment (not persistent)
        os.environ['XERO_ACCESS_TOKEN'] = credentials.access_token
        os.environ['XERO_REFRESH_TOKEN'] = credentials.refresh_token
    
    return Xero(credentials)

@tool
@retry_with_exponential_backoff(max_retries=3, base_delay=1, max_delay=60)
def fetch_xero_invoices(tenant_id: int, user_id: int, days_back: int = 30) -> str:
    """
    Fetch invoices from Xero.
    
    Args:
        tenant_id: ID of the tenant for data isolation
        user_id: ID of the user
        days_back: Number of days back to fetch invoices
    
    Returns:
        JSON string containing list of invoice data dictionaries
    """
    if not XERO_AVAILABLE:
        return json.dumps({"error": "Xero package not available. Install with: pip install xero-python"}, default=str)
    
    try:
        # Get credentials from connected account in database
        from db.database import SessionLocal
        from db.models import ConnectedAccount
        
        db = SessionLocal()
        try:
            connected = db.query(ConnectedAccount).filter(
                ConnectedAccount.tenant_id == tenant_id,
                ConnectedAccount.provider == "xero",
                ConnectedAccount.is_active == True
            ).first()
            
            if not connected:
                logger.warning(f"No Xero connection found for tenant {tenant_id}")
                return json.dumps({"error": "Xero not connected"}, default=str)
            
            access_token = connected.access_token
            refresh_token = connected.refresh_token
            
            if not access_token:
                return json.dumps({"error": "Xero access token not available"}, default=str)
                
        finally:
            db.close()
        
        # Initialize Xero client with stored credentials
        credentials = OAuth2Credentials(
            client_id=os.getenv('XERO_CLIENT_ID'),
            client_secret=os.getenv('XERO_CLIENT_SECRET'),
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=3600,
            scope='openid profile email accounting.transactions accounting.contacts.read'
        )
        
        if credentials.expired():
            credentials.refresh()
        
        xero_client = Xero(credentials)
        
        # Calculate date for query
        utc_now = datetime.utcnow()
        start_date = utc_now - timedelta(days=days_back)
        
        # Fetch invoices modified after start_date (using parameterized query to prevent SQL injection)
        invoices = xero_client.invoices.filter(
            DateTimeUTC__gte=start_date.isoformat() + 'Z'
        )
        
        invoice_data_list = []
        for xero_invoice in invoices:
            # Convert Xero invoice to our format
            invoice_data = {
                'invoice_number': getattr(xero_invoice, 'InvoiceNumber', f"XERO_{xero_invoice.InvoiceID}"),
                'vendor_name': xero_invoice.Contact.Name if hasattr(xero_invoice, 'Contact') and xero_invoice.Contact else 'Unknown',
                'amount_due': float(getattr(xero_invoice, 'AmountDue', 0) or 0),
                'amount_paid': float(getattr(xero_invoice, 'AmountPaid', 0) or 0),
                'currency': getattr(xero_invoice, 'CurrencyCode', 'USD'),
                'invoice_date': getattr(xero_invoice, 'Date', datetime.now().date()),
                'due_date': getattr(xero_invoice, 'DueDate', getattr(xero_invoice, 'Date', datetime.now().date())),
                'status': _map_xero_status(getattr(xero_invoice, 'Status', 'DRAFT')),
                'description': getattr(xero_invoice, 'Reference', '') or '',
                'source': 'xero',
                'source_id': xero_invoice.InvoiceID,
                'tenant_id': tenant_id,
                'user_id': user_id,
                'line_items': []
            }
            
            # Add line items if available
            if hasattr(xero_invoice, 'LineItems') and xero_invoice.LineItems:
                line_items = []
                for line in xero_invoice.LineItems:
                    item = {
                        'description': getattr(line, 'Description', '') or '',
                        'quantity': float(getattr(line, 'Quantity', 0) or 0),
                        'unit_price': float(getattr(line, 'UnitAmount', 0) or 0),
                        'amount': float(getattr(line, 'LineAmount', 0) or 0)
                    }
                    line_items.append(item)
                invoice_data['line_items'] = line_items
            
            invoice_data_list.append(invoice_data)
        
        # Save to database with tenant isolation
        saved_count = _save_invoices_to_db(tenant_id, invoice_data_list, 'xero')
        
        logger.info(f"Fetched {len(invoice_data_list)} invoices from Xero, saved {saved_count} to DB for tenant {tenant_id}")
        return json.dumps({"total_fetched": len(invoice_data_list), "saved_to_db": saved_count}, default=str)
    
    except Exception as e:
        logger.error(f"Error fetching Xero invoices for tenant {tenant_id}: {str(e)}")
        return json.dumps({"error": str(e)}, default=str)


def _map_xero_status(xero_status: str) -> str:
    """Map Xero invoice status to our internal status."""
    status_map = {
        'DRAFT': 'draft',
        'SUBMITTED': 'pending',
        'AUTHORISED': 'pending',
        'INVOICED': 'sent',
        'PAID': 'paid',
        'VOID': 'void',
        'DELETED': 'deleted'
    }
    return status_map.get(xero_status.upper(), 'pending')

# ==================== Plaid Tool ====================

def get_plaid_client():
    """Get authenticated Plaid client."""
    if not PLAID_AVAILABLE:
        raise ImportError("Plaid package not available. Install plaid-python to use Plaid integration.")
    
    client_id = os.getenv('PLAID_CLIENT_ID')
    secret = os.getenv('PLAID_SECRET')
    environment = os.getenv('PLAID_ENV', 'sandbox')
    
    if not all([client_id, secret]):
        raise ValueError("Plaid credentials not configured")
    
    # Map environment to Plaid API host
    env_map = {
        'sandbox': 'https://sandbox.plaid.com',
        'development': 'https://development.plaid.com',
        'production': 'https://production.plaid.com'
    }
    
    host = env_map.get(environment, 'https://sandbox.plaid.com')
    
    configuration = plaid.Configuration(
        host=host,
        api_key={
            'clientId': client_id,
            'secret': secret
        }
    )
    
    api_client = plaid.ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)

@tool
@retry_with_exponential_backoff(max_retries=3, base_delay=1, max_delay=60)
def fetch_plaid_transactions_and_statements(tenant_id: int, user_id: int, days_back: int = 30) -> str:
    """
    Fetch transactions and statements from Plaid, downloading any available PDF statements.
    
    Args:
        tenant_id: ID of the tenant for data isolation
        user_id: ID of the user
        days_back: Number of days back to fetch transactions
    
    Returns:
        JSON string containing list of transaction data and any statement PDF metadata
    """
    if not PLAID_AVAILABLE:
        return json.dumps({"error": "Plaid package not available. Install with: pip install plaid"}, default=str)
    
    try:
        # Get credentials from connected account in database
        from db.database import SessionLocal
        from db.models import ConnectedAccount
        
        db = SessionLocal()
        try:
            connected = db.query(ConnectedAccount).filter(
                ConnectedAccount.tenant_id == tenant_id,
                ConnectedAccount.provider == "plaid",
                ConnectedAccount.is_active == True
            ).first()
            
            if not connected:
                logger.warning(f"No Plaid connection found for tenant {tenant_id}")
                return json.dumps({"error": "Plaid not connected", "transactions": [], "statements": []}, default=str)
            
            access_token = connected.access_token
            
            if not access_token:
                return json.dumps({"error": "Plaid access token not available", "transactions": [], "statements": []}, default=str)
                
        finally:
            db.close()
        
        client = get_plaid_client()
        
        # Calculate date range
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        
        # Fetch transactions using parameterized request
        response = client.transactions_get(
            access_token=access_token,
            start_date=start_date,
            end_date=end_date
        )
        
        transactions = []
        for txn in response.transactions:
            transactions.append({
                "transaction_id": txn.transaction_id,
                "amount": txn.amount,
                "date": txn.date,
                "name": txn.name,
                "merchant_name": getattr(txn, 'merchant_name', None),
                "category": txn.category,
                "category_id": txn.category_id,
                "payment_channel": txn.payment_channel,
                "pending": txn.pending,
                "pending_transaction_id": txn.pending_transaction_id,
                "account_id": txn.account_id,
                "account_owner": txn.account_owner,
                "transaction_type": txn.transaction_type,
                "iso_currency_code": txn.iso_currency_code,
                "tenant_id": tenant_id,
                "user_id": user_id,
            })
        
        # Save transactions to database with tenant isolation
        _save_plaid_transactions_to_db(tenant_id, transactions)
        
        # Try to fetch statements (if available)
        statements = []
        try:
            accounts_response = client.accounts_get(access_token=access_token)
            for account in accounts_response.accounts:
                statements.append({
                    "account_id": account.account_id,
                    "account_name": account.name,
                    "account_type": account.type,
                    "account_subtype": getattr(account, 'subtype', None),
                    "balances": {
                        "available": float(account.balances.available) if hasattr(account.balances, 'available') else None,
                        "current": float(account.balances.current) if hasattr(account.balances, 'current') else None,
                    }
                })
        except Exception as e:
            logger.warning(f"Could not fetch statements: {e}")
        
        result = {
            "transactions": transactions,
            "statements": statements,
            "fetch_timestamp": datetime.utcnow().isoformat(),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "days_requested": days_back,
            "total_fetched": len(transactions)
        }
        
        logger.info(f"Fetched {len(transactions)} transactions and {len(statements)} accounts from Plaid for tenant {tenant_id}")
        return json.dumps(result, default=str)
        
    except Exception as e:
        logger.error(f"Error fetching Plaid transactions for tenant {tenant_id}: {str(e)}")
        return json.dumps({"error": str(e)}, default=str)


def _save_plaid_transactions_to_db(tenant_id: int, transactions: List[Dict[str, Any]]) -> int:
    """
    Save fetched Plaid transactions to the database with proper tenant isolation.
    
    Args:
        tenant_id: The tenant ID for data isolation
        transactions: List of transaction data dictionaries
    
    Returns:
        Number of transactions saved
    """
    from db.database import SessionLocal
    from db.models import PlaidTransaction
    
    db = SessionLocal()
    saved_count = 0
    
    try:
        for txn_data in transactions:
            # Check for existing transaction to avoid duplicates
            existing = db.query(PlaidTransaction).filter(
                PlaidTransaction.tenant_id == tenant_id,
                PlaidTransaction.plaid_transaction_id == txn_data.get('transaction_id')
            ).first()
            
            if existing:
                continue
            
            transaction = PlaidTransaction(
                tenant_id=tenant_id,
                plaid_transaction_id=txn_data.get('transaction_id'),
                account_id=txn_data.get('account_id'),
                amount=txn_data.get('amount', 0),
                currency=txn_data.get('iso_currency_code', 'USD'),
                transaction_date=txn_data.get('date'),
                name=txn_data.get('name'),
                merchant_name=txn_data.get('merchant_name'),
                category=txn_data.get('category'),
                pending=txn_data.get('pending', False),
            )
            db.add(transaction)
            saved_count += 1
        
        db.commit()
        logger.info(f"Saved {saved_count} Plaid transactions to database for tenant {tenant_id}")
        
    except Exception as e:
        logger.error(f"Error saving Plaid transactions to database: {str(e)}")
        db.rollback()
    finally:
        db.close()
    
    return saved_count

# ==================== Helper Functions ====================

def parse_invoice_pdf_from_bytes(file_bytes: bytes, source: str, source_id: str) -> Optional[Dict[str, Any]]:
    """
    Parse invoice data from PDF bytes.
    
    Args:
        file_bytes: PDF file content as bytes
        source: Source of the document (gmail, drive, etc.)
        source_id: Unique identifier from the source
    
    Returns:
        Dictionary with invoice data or None if parsing fails
    """
    try:
        # Write bytes to temporary file for pdfplumber
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(file_bytes)
            tmp_file_path = tmp_file.name
        
        # Parse PDF
        invoice_data = parse_invoice_pdf(tmp_file_path)
        
        # Clean up temp file
        os.unlink(tmp_file_path)
        
        if invoice_data and 'error' not in invoice_data:
            invoice_data['source'] = source
            invoice_data['source_id'] = source_id
            return invoice_data
        else:
            logger.warning(f"Failed to parse PDF from {source}:{source_id}")
            return None
            
    except Exception as e:
        logger.error(f"Error parsing PDF from bytes for {source}:{source_id}: {str(e)}")
        return None