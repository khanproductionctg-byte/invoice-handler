"""
Email sending utilities using SendGrid.
"""
import logging
from typing import Dict, Any
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, body: str, is_html: bool = False) -> Dict[str, Any]:
    """
    Send an email using SendGrid.

    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Email body content
        is_html: Whether the body is HTML

    Returns:
        Dictionary with success status and details
    """
    try:
        # Get SendGrid API key from environment
        api_key = os.getenv("SENDGRID_API_KEY")
        if not api_key:
            logger.error("SENDGRID_API_KEY not found in environment")
            return {
                "success": False,
                "error": "SENDGRID_API_KEY not configured"
            }
        
        # Get sender email from environment
        from_email = os.getenv("SENDGRID_FROM_EMAIL")
        if not from_email:
            logger.error("SENDGRID_FROM_EMAIL not found in environment")
            return {
                "success": False,
                "error": "SENDGRID_FROM_EMAIL not configured"
            }
        
        # Create SendGrid client
        sg = SendGridAPIClient(api_key)
        
        # Create email message
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject,
            plain_text_content=body if not is_html else None,
            html_content=body if is_html else None
        )
        
        # Send email
        response = sg.send(message)
        
        logger.info(f"Email sent to {to_email}. Status code: {response.status_code}")
        
        return {
            "success": True,
            "status_code": response.status_code,
            "message_id": response.headers.get("X-Message-Id")
        }
        
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


def send_email_template(to_email: str, subject: str, template_data: Dict[str, Any], template_id: str) -> Dict[str, Any]:
    """
    Send an email using a SendGrid dynamic template.

    Args:
        to_email: Recipient email address
        subject: Email subject
        template_data: Data to populate the template
        template_id: SendGrid template ID

    Returns:
        Dictionary with success status and details
    """
    try:
        # Get SendGrid API key from environment
        api_key = os.getenv("SENDGRID_API_KEY")
        if not api_key:
            logger.error("SENDGRID_API_KEY not found in environment")
            return {
                "success": False,
                "error": "SENDGRID_API_KEY not configured"
            }
        
        # Get sender email from environment
        from_email = os.getenv("SENDGRID_FROM_EMAIL")
        if not from_email:
            logger.error("SENDGRID_FROM_EMAIL not found in environment")
            return {
                "success": False,
                "error": "SENDGRID_FROM_EMAIL not configured"
            }
        
        # Create SendGrid client
        sg = SendGridAPIClient(api_key)
        
        # Create email message with template
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject
        )
        message.template_id = template_id
        message.dynamic_template_data = template_data
        
        # Send email
        response = sg.send(message)
        
        logger.info(f"Template email sent to {to_email}. Status code: {response.status_code}")
        
        return {
            "success": True,
            "status_code": response.status_code,
            "message_id": response.headers.get("X-Message-Id")
        }
        
    except Exception as e:
        logger.error(f"Failed to send template email to {to_email}: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }