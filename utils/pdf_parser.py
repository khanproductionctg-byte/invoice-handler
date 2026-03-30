"""
PDF parsing utilities for extracting invoice data from PDF files.
Uses pdfplumber for text extraction, OCR fallback for scanned PDFs,
and LLM for structured data extraction.
"""
import logging
import re
import json
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import pdfplumber
import pandas as pd
from io import BytesIO

logger = logging.getLogger(__name__)

# For OCR fallback - scanned PDF support
# Install with: pip install pdf2image pytesseract
# Also install tesseract-ocr separately for your OS:
# - Windows: https://github.com/UB-Mannheim/tesseract/wiki
# - Mac: brew install tesseract
# - Linux: sudo apt-get install tesseract-ocr
try:
    from pdf2image import convert_from_bytes
    import pytesseract
    OCR_AVAILABLE = True
    logger.info("OCR support enabled for scanned PDFs")
except ImportError:
    OCR_AVAILABLE = False
    logging.warning(
        "OCR dependencies not available. Scanned PDFs will not be processed.\n"
        "To enable OCR support, run:\n"
        "  pip install pdf2image pytesseract\n"
        "And install Tesseract OCR for your OS."
    )

# For LLM structured output
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from langchain_community.llms import Ollama

logger = logging.getLogger(__name__)

# Define Pydantic model for structured invoice data
class InvoiceLineItem(BaseModel):
    description: str = Field(description="Description of the line item")
    quantity: Union[int, float] = Field(description="Quantity of the item", default=1.0)
    unit_price: Optional[float] = Field(description="Unit price of the item", default=None)
    amount: Optional[float] = Field(description="Total amount for the line item", default=None)

class InvoiceData(BaseModel):
    vendor_name: str = Field(description="Name of the vendor")
    invoice_number: Optional[str] = Field(description="Invoice number", default=None)
    invoice_date: Optional[str] = Field(description="Invoice date in YYYY-MM-DD format", default=None)
    due_date: Optional[str] = Field(description="Due date in YYYY-MM-DD format", default=None)
    amount_due: Optional[float] = Field(description="Total amount due", default=None)
    currency: str = Field(description="Currency code (e.g., USD)", default="USD")
    line_items: List[InvoiceLineItem] = Field(description="List of line items", default_factory=list)
    description: Optional[str] = Field(description="Additional description or notes", default=None)
    confidence_score: Optional[float] = Field(description="Confidence score of the extraction (0-1)", default=None)

# Initialize LLM for structured output (assuming Ollama with nemotron-3-super)
# In production, this would be configured via environment variables
def get_llm():
    """Get LLM instance for structured output."""
    try:
        # Using Ollama with nemotron-3-super model
        return Ollama(model="nemotron-3-super", format="json")
    except Exception as e:
        logger.warning(f"Could not initialize Ollama LLM: {str(e)}. Falling back to rule-based parsing.")
        return None

def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract text from PDF using pdfplumber, with OCR fallback for scanned PDFs.

    Args:
        file_path: Path to the PDF file

    Returns:
        Extracted text string
    """
    text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            # First try to extract text with pdfplumber
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            
            # If we got very little text, it might be a scanned PDF
            if len(text.strip()) < 100 and OCR_AVAILABLE:
                logger.info(f"PDF {file_path} appears to be scanned (little text). Attempting OCR.")
                text = extract_text_with_ocr(file_path)
            elif len(text.strip()) < 100:
                logger.warning(f"PDF {file_path} has very little text and OCR is not available.")
                
    except Exception as e:
        logger.error(f"Error opening PDF {file_path} with pdfplumber: {str(e)}")
        # Try OCR as last resort if available
        if OCR_AVAILABLE:
            logger.info(f"Attempting OCR fallback for {file_path} after pdfplumber failure.")
            text = extract_text_with_ocr(file_path)
        else:
            raise
    
    return text.strip()

def extract_text_with_ocr(file_path: str) -> str:
    """
    Extract text from PDF using OCR (requires pdf2image and pytesseract).

    Args:
        file_path: Path to the PDF file

    Returns:
        Extracted text string via OCR
    """
    if not OCR_AVAILABLE:
        raise ImportError("OCR dependencies (pdf2image, pytesseract) are not installed.")
    
    try:
        # Convert PDF to images
        images = convert_from_bytes(open(file_path, 'rb').read())
        text = ""
        for i, image in enumerate(images):
            # Apply OCR to each image
            page_text = pytesseract.image_to_string(image)
            text += page_text + "\n"
            logger.debug(f"OCR processed page {i+1}/{len(images)}")
        
        return text
    except Exception as e:
        logger.error(f"OCR failed for {file_path}: {str(e)}")
        return ""

def parse_invoice_with_llm(text: str) -> Optional[Dict[str, Any]]:
    """
    Use LLM to extract structured invoice data from text.

    Args:
        text: Raw text extracted from PDF

    Returns:
        Dictionary with structured invoice data or None if fails
    """
    from utils.prompt_guard import sanitize_for_prompt
    
    llm = get_llm()
    if not llm:
        logger.warning("LLM not available for structured parsing.")
        return None
    
    # Sanitize input text to prevent prompt injection
    sanitized_text = sanitize_for_prompt(text)
    
    # Define the prompt for the LLM
    prompt_template = """
    You are an expert at extracting structured data from invoices.
    Extract the following information from the invoice text below and return it as a JSON object.
    
    Important rules:
    1. Return ONLY valid JSON, no additional text
    2. If a field is not found, use null (for strings/numbers) or empty array (for line_items)
    3. For dates, use YYYY-MM-DD format
    4. For amounts, use numbers without currency symbols
    5. Currency should be a 3-letter ISO code (e.g., USD, EUR)
    6. Line items should be an array of objects with: description, quantity, unit_price, amount
    7. If you cannot determine a value with reasonable confidence, leave it as null/empty
    
    Invoice text:
    {text}
    
    JSON output:
    """
    
    prompt = PromptTemplate(
        template=prompt_template,
        input_variables=["text"]
    )
    
    # Set up the JSON parser
    parser = JsonOutputParser(pydantic_object=InvoiceData)
    
    try:
        # Format the prompt with sanitized text (limit length to 8000 chars)
        formatted_prompt = prompt.format(text=sanitized_text[:8000])
        
        # Get LLM response
        response = llm.invoke(formatted_prompt)
        
        # Parse the JSON
        parsed_data = parser.parse(response)
        
        # Calculate a simple confidence score based on how many fields we found
        # This is a simplified approach - in practice, you might want something more sophisticated
        non_null_fields = sum(1 for v in parsed_data.values() 
                            if v is not None and v != "" and v != [])
        total_fields = len([f for f in parsed_data.model_fields.keys() 
                           if f not in ['confidence_score', 'line_items']])  # Exclude special fields
        confidence = non_null_fields / total_fields if total_fields > 0 else 0.0
        
        # Add confidence score
        parsed_data['confidence_score'] = confidence
        
        logger.info(f"LLM parsed invoice with confidence {confidence:.2f}")
        return parsed_data.dict()
        
    except Exception as e:
        logger.error(f"LLM parsing failed: {str(e)}")
        return None

def parse_invoice_pdf(file_path: str) -> Dict[str, Any]:
    """
    Parse an invoice PDF and extract structured data.
    Tries LLM extraction first, falls back to rule-based parsing.

    Args:
        file_path: Path to the PDF file

    Returns:
        Dictionary containing extracted invoice data
    """
    try:
        logger.info(f"Parsing PDF invoice: {file_path}")
        
        # Extract text from PDF
        text = extract_text_from_pdf(file_path)
        
        if not text:
            logger.warning(f"No text extracted from {file_path}")
            return {
                "error": "No text could be extracted from the PDF",
                "file_path": file_path
            }
        
        # Try LLM-based parsing first
        logger.info("Attempting LLM-based structured extraction")
        llm_result = parse_invoice_with_llm(text)
        
        if llm_result and llm_result.get('confidence_score', 0) > 0.5:
            # LLM parsing succeeded with reasonable confidence
            logger.info(f"LLM parsing successful: {llm_result}")
            return llm_result
        
        # Fall back to rule-based parsing
        logger.info("Falling back to rule-based parsing")
        rule_based_result = parse_invoice_pdf_rule_based(text, file_path)
        
        # If we have both, we could combine them, but for now we'll use whichever is better
        if llm_result:
            # Use LLM result but potentially override with rule-based for critical fields
            # For simplicity, we'll use LLM if confidence > 0.3, else rule-based
            if llm_result.get('confidence_score', 0) > 0.3:
                return llm_result
        
        return rule_based_result
        
    except Exception as e:
        logger.error(f"Failed to parse PDF invoice {file_path}: {str(e)}")
        # Return partial data with error indication
        return {
            "error": f"Failed to parse PDF: {str(e)}",
            "file_path": file_path
        }

def parse_invoice_pdf_rule_based(text: str, file_path: str) -> Dict[str, Any]:
    """
    Rule-based PDF parsing (original implementation) as fallback.

    Args:
        text: Raw text extracted from PDF
        file_path: Path to the PDF file (for error reporting)

    Returns:
        Dictionary containing extracted invoice data
    """
    logger.info(f"Using rule-based parsing for {file_path}")
    
    invoice_data = {
        "invoice_number": None,
        "vendor_name": None,
        "invoice_date": None,
        "due_date": None,
        "amount_due": None,
        "currency": "USD",
        "line_items": [],
        "description": None
    }
    
    try:
        # Extract invoice number
        invoice_number_patterns = [
            r'invoice\s*#?\s*:?\s*([A-Z0-9\-]+)',
            r'invoice\s*number\s*#?\s*:?\s*([A-Z0-9\-]+)',
            r'#\s*:?\s*([A-Z0-9\-]+)\s*invoice',
        ]
        
        for pattern in invoice_number_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                invoice_data["invoice_number"] = match.group(1).strip()
                break
        
        # Extract vendor name (usually at top of invoice)
        lines = text.split('\n')
        for i, line in enumerate(lines[:15]):  # Check first 15 lines
            if line.strip() and len(line.strip()) > 3:
                # Simple heuristic: first non-empty line that looks like a company name
                if not any(keyword in line.lower() for keyword in ['invoice', 'date', 'bill', 'amount', 'total', 'due']):
                    invoice_data["vendor_name"] = line.strip()
                    break
        
        # Extract dates
        date_patterns = [
            r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
        ]
        
        date_matches = []
        for pattern in date_patterns:
            matches = re.findall(pattern, text)
            date_matches.extend(matches)
        
        # Try to parse dates and assign to invoice_date and due_date
        parsed_dates = []
        for date_str in date_matches:
            try:
                # Try different formats
                for fmt in ['%m/%d/%Y', '%m/%d/%y', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y']:
                    try:
                        parsed_date = datetime.strptime(date_str, fmt).date()
                        parsed_dates.append(parsed_date)
                        break
                    except ValueError:
                        continue
            except Exception:
                continue
        
        if len(parsed_dates) >= 2:
            # Assume first is invoice date, second is due date (common pattern)
            invoice_data["invoice_date"] = parsed_dates[0].isoformat()
            invoice_data["due_date"] = parsed_dates[1].isoformat()
        elif len(parsed_dates) == 1:
            invoice_data["invoice_date"] = parsed_dates[0].isoformat()
            # Due date would need to be inferred or left None
        
        # Extract amount due
        amount_patterns = [
            r'total\s*[:\s]*[$€£]?\s*(\d+\.?\d*)',
            r'amount\s*due\s*[:\s]*[$€£]?\s*(\d+\.?\d*)',
            r'balance\s*[:\s]*[$€£]?\s*(\d+\.?\d*)',
            r'[$€£]\s*(\d+\.?\d*)',
        ]
        
        for pattern in amount_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    amount = float(match.group(1))
                    invoice_data["amount_due"] = amount
                    break
                except ValueError:
                    continue
        
        # Extract currency
        currency_patterns = [
            r'USD|EUR|GBP|CAD|AUD|JPY|CHF|CNY',
        ]
        
        for pattern in currency_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                invoice_data["currency"] = match.group(0).upper()
                break
        
        # Extract line items from tables if available
        # Note: This requires accessing the PDF again for table extraction
        # We'll do a second pass with pdfplumber for tables
        try:
            with pdfplumber.open(file_path) as pdf:
                tables = []
                for page in pdf.pages:
                    page_tables = page.extract_tables()
                    if page_tables:
                        tables.extend(page_tables)
                
                if tables:
                    # Assume the largest table with headers is the line items table
                    line_items = []
                    for table in tables:
                        if len(table) > 1 and len(table[0]) >= 3:  # Header + at least one row
                            # Try to identify quantity, description, amount columns
                            headers = [str(h).lower() if h else "" for h in table[0]]
                            desc_idx = None
                            qty_idx = None
                            amount_idx = None
                            
                            for i, header in enumerate(headers):
                                if any(word in header for word in ['description', 'item', 'desc']):
                                    desc_idx = i
                                elif any(word in header for word in ['quantity', 'qty', 'units']):
                                    qty_idx = i
                                elif any(word in header for word in ['amount', 'total', 'price']):
                                    amount_idx = i
                            
                            # If we found expected columns, extract data
                            if desc_idx is not None and amount_idx is not None:
                                for row in table[1:]:  # Skip header
                                    if len(row) > max(desc_idx, amount_idx):
                                        item = {
                                            "description": str(row[desc_idx]) if desc_idx < len(row) else "",
                                            "quantity": 1.0,  # Default
                                            "unit_price": None,
                                            "amount": None
                                        }
                                        # Try to extract quantity
                                        if qty_idx is not None and qty_idx < len(row) and row[qty_idx]:
                                            try:
                                                item["quantity"] = float(str(row[qty_idx]))
                                            except ValueError:
                                                pass
                                        
                                        # Try to extract amount
                                        if amount_idx < len(row) and row[amount_idx]:
                                            try:
                                                item["amount"] = float(str(row[amount_idx]).replace('$', '').replace(',', ''))
                                            except ValueError:
                                                pass
                                        
                                        # If we have amount and quantity, calculate unit price
                                        if item["amount"] is not None and item["quantity"] is not None and item["quantity"] != 0:
                                            item["unit_price"] = item["amount"] / item["quantity"]
                                        
                                        line_items.append(item)
                    
                    invoice_data["line_items"] = line_items
        except Exception as e:
            logger.warning(f"Could not extract tables from PDF: {str(e)}")
        
        # Set description as first 500 chars of text
        invoice_data["description"] = text[:500].strip() if text else None
        
        logger.info(f"Parsed invoice data (rule-based): {invoice_data}")
        return invoice_data
        
    except Exception as e:
        logger.error(f"Rule-based parsing failed for {file_path}: {str(e)}")
        return {
            "error": f"Rule-based parsing failed: {str(e)}",
            "file_path": file_path
        }