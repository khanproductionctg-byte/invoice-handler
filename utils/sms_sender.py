"""
SMS sending utilities using Twilio.
"""
import logging
from typing import Dict, Any, List
import os
from twilio.rest import Client

logger = logging.getLogger(__name__)


def send_sms(to_number: str, message: str) -> Dict[str, Any]:
    """
    Send an SMS using Twilio.

    Args:
        to_number: Recipient phone number (in E.164 format)
        message: SMS message content

    Returns:
        Dictionary with success status and details
    """
    try:
        # Get Twilio credentials from environment
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_FROM_NUMBER")
        
        if not all([account_sid, auth_token, from_number]):
            missing = []
            if not account_sid: missing.append("TWILIO_ACCOUNT_SID")
            if not auth_token: missing.append("TWILIO_AUTH_TOKEN")
            if not from_number: missing.append("TWILIO_FROM_NUMBER")
            logger.error(f"Missing Twilio credentials: {', '.join(missing)}")
            return {
                "success": False,
                "error": f"Missing Twilio credentials: {', '.join(missing)}"
            }
        
        # Validate phone number format (basic check)
        if not to_number.startswith("+"):
            logger.error(f"Phone number {to_number} is not in E.164 format")
            return {
                "success": False,
                "error": "Phone number must be in E.164 format (e.g., +1234567890)"
            }
        
        # Create Twilio client
        client = Client(account_sid, auth_token)
        
        # Send SMS
        message_obj = client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
        
        logger.info(f"SMS sent to {to_number}. SID: {message_obj.sid}")
        
        return {
            "success": True,
            "sid": message_obj.sid,
            "status": message_obj.status
        }
        
    except Exception as e:
        logger.error(f"Failed to send SMS to {to_number}: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


def send_sms_bulk(to_numbers: List[str], message: str) -> List[Dict[str, Any]]:
    """
    Send SMS to multiple recipients.

    Args:
        to_numbers: List of recipient phone numbers
        message: SMS message content

    Returns:
        List of result dictionaries for each number
    """
    results = []
    for number in to_numbers:
        result = send_sms(number, message)
        results.append({"to": number, **result})
    return results