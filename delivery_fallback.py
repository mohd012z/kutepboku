"""Classify email failures and offer a rights-checked Telegram fallback.

Callers must persist outcomes and send user/admin notifications separately.
"""
import smtplib
import ssl

from logger_config import logger
from whatsapp_gateway import valid_public_url


def classify_email_failure(exc):
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "SMTP_AUTH", False
    if isinstance(exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused)):
        return "SMTP_REJECTED", False
    if isinstance(exc, (TimeoutError, ConnectionError, smtplib.SMTPServerDisconnected)):
        return "SMTP_TRANSIENT", True
    if isinstance(exc, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        return "SMTP_CONFIGURATION", False
    return "SMTP_FAILURE", False


def fallback_source_link(book):
    """Only expose the previously approved source URL; no arbitrary links."""
    if not isinstance(book, dict) or book.get("rights_verified") is not True:
        return None
    if book.get("distribution_allowed") is not True:
        return None
    url = book.get("source_url")
    if not isinstance(url, str) or not valid_public_url(url):
        return None
    return url


def send_email_with_fallback(*, job_id, book, send_email, notify_user,
                             notify_admin=None, telegram_chat_verified=False):
    """Execute a verified queued job; never log PII, URLs or exception strings.

    send_email() must enforce recipient verification and actual SMTP transport.
    notify_user(text) must target the authenticated user's verified Telegram chat.
    """
    if not isinstance(job_id, str) or not job_id:
        raise ValueError("Delivery job ID required")
    try:
        send_email()
    except Exception as exc:
        category, retryable = classify_email_failure(exc)
        logger.error("email_delivery_failed job_id=%s category=%s retryable=%s",
                     job_id, category, retryable)
        url = fallback_source_link(book)
        notification = "Email delivery could not be completed."
        if retryable:
            notification += " You may retry later."
        if telegram_chat_verified and url:
            notification += "\nYou can open the verified source here: " + url
        try:
            notify_user(notification)
        except Exception:
            logger.error("user_notification_failed job_id=%s", job_id)
        if notify_admin is not None:
            try:
                notify_admin("msasoup email failure: job " + job_id + ", category " + category)
            except Exception:
                logger.error("admin_notification_failed job_id=%s", job_id)
        return {"status": "RETRY_PENDING" if retryable else "FAILED",
                "category": category, "retryable": retryable,
                "fallback_link_offered": bool(telegram_chat_verified and url)}
    logger.info("email_delivery_accepted job_id=%s", job_id)
    return {"status": "ACCEPTED", "retryable": False, "fallback_link_offered": False}
