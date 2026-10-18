# msasoup WhatsApp Gateway

## Architecture and rollout

**Manual sharing (available as a library component):**
- For an approved public book source URL, generate a Telegram inline URL button with `book_keyboard`.
- Tapping the button opens WhatsApp with a prefilled title and source link. The user chooses a recipient and presses Send.
- This does not attach a PDF, upload a file or send a message automatically.

**Business delivery (disabled by default):**
- Requires Meta WhatsApp Business Platform, a configured sender phone number, access token, recipient opt-in, and a compliant messaging context.
- `deliver_document` sends an HTTPS document link through the Cloud API only after `consent=True` and `confirmed=True` are supplied by a trusted caller.
- Set `WHATSAPP_DELIVERY_ENABLED=true`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` and optionally `WHATSAPP_GRAPH_VERSION` in deployment secrets. Never commit credentials.
- A valid publicly accessible PDF document URL is required for document messages; an Internet Archive details page is **not** a document URL. Validate the real document's content type and download rights before using this gateway.
- Business-initiated conversations may require approved message templates; messaging windows, recipient consent, and Meta policy must be checked by the application.
- API success acknowledges acceptance, **not** delivery. Handle WhatsApp status webhooks for delivered/read/failed outcomes.

**Telegram integration:**
- `book_keyboard` returns inline button JSON for an existing Telegram message sender.
- `process_callback` validates `TELEGRAM_ALLOWED_USER_IDS` and creates a *pending* request. It does not deliver automatically.
- An inbound Telegram webhook or polling worker, book index, pending-request database, opt-in confirmation UI and verified document URL resolver must be added to make the entire workflow operational.
- GitHub Actions is a scheduler and test runner, not an always-online Telegram update listener.

## Security checklist

- Restrict Telegram user IDs; never trust a client-supplied `consent` boolean.
- Authenticate Telegram update sources and Meta webhook signatures.
- Validate source URLs and avoid sending arbitrary or private URLs.
- Rate-limit requests; add idempotency keys and an audit trail.
- Store recipient phone numbers securely, with retention and deletion controls.
- Send only material for which redistribution is authorized.
- Never post Telegram or Meta credentials in issues or logs.

## Testing

`python -m unittest discover -s tests -v`

No live WhatsApp or Telegram delivery is exercised by unit tests.
