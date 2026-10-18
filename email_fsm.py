"""Pure email FSM transitions for the persistent Telegram router.

Integrate these functions with SessionManager and Telegram message/callback
handlers. They do not send email or assert that an address is verified.
"""
import re

STATE_CHOOSE_DELIVERY = "CHOOSE_DELIVERY"
STATE_WAITING_FOR_EMAIL = "WAITING_FOR_EMAIL"
STATE_VERIFY_EMAIL = "VERIFY_EMAIL"
STATE_CONFIRM_EMAIL = "CONFIRM_EMAIL"
STATE_DELIVERY_QUEUED = "DELIVERY_QUEUED"
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,63}$")


def normalize_email(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) > 254 or not EMAIL_PATTERN.fullmatch(value):
        return None
    local, domain = value.rsplit("@", 1)
    if len(local) > 64 or ".." in local or ".." in domain or domain.startswith("-"):
        return None
    return local + "@" + domain.lower()


def begin_email(state, data):
    if state != STATE_CHOOSE_DELIVERY or not isinstance(data, dict) or not data.get("selected_book"):
        raise ValueError("Email cannot be selected from this state")
    return STATE_WAITING_FOR_EMAIL, {**data, "delivery_channel": "email"}


def accept_email(state, data, email):
    if state != STATE_WAITING_FOR_EMAIL or not isinstance(data, dict) or not data.get("selected_book"):
        raise ValueError("Not awaiting an email address")
    address = normalize_email(email)
    if not address:
        return {"ok": False, "state": state, "data": data,
                "message": "Please enter a valid email address or send /cancel."}
    next_data = {**data, "pending_email": address}
    next_data.pop("email_verified", None)
    return {"ok": True, "state": STATE_VERIFY_EMAIL, "data": next_data,
            "message": "Verify ownership of this email address before delivery."}


def mark_email_verified(state, data, *, verified_address, verification_evidence):
    """Call only after a trusted server-side verification service confirms ownership.

    verification_evidence must be an authenticated verification record, not a
    user-supplied boolean or Telegram callback value.
    """
    if state != STATE_VERIFY_EMAIL or not isinstance(data, dict):
        raise ValueError("Email verification not expected")
    if not verification_evidence or normalize_email(verified_address) != data.get("pending_email"):
        raise PermissionError("Email ownership has not been verified")
    return STATE_CONFIRM_EMAIL, {**data, "email_verified": True}


def confirm_email_delivery(state, data, *, confirmed, enqueue_job):
    """Enqueue a durable job; never send inline in the Telegram callback."""
    if state != STATE_CONFIRM_EMAIL or not isinstance(data, dict):
        raise ValueError("Delivery confirmation not expected")
    if not confirmed or data.get("email_verified") is not True:
        raise PermissionError("Verified recipient and confirmation required")
    if not data.get("selected_book") or not data.get("pending_email"):
        raise ValueError("Missing delivery details")
    job_id = enqueue_job(data["selected_book"], data["pending_email"])
    if not job_id:
        raise RuntimeError("Delivery job was not persisted")
    return STATE_DELIVERY_QUEUED, {"delivery_job_id": str(job_id)}
