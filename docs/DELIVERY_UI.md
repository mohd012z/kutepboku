# Telegram Delivery Center UI

This PR adds a **native inline-keyboard UI module** (`delivery_ui.py`), not an active Telegram bot listener.

Navigation:
1. `/start` -> Home: Find eBooks, My Library, Delivery Settings.
2. Show `book_card(book_id, title, author, source_url)` for verified catalogue results.
3. Tap **Send / Share** -> `destination_menu`.
4. Choose **Telegram**, **Email**, or **WhatsApp Auto** -> confirmation screen.
5. Confirm -> create a **pending** delivery job only.
6. **WhatsApp Share** opens WhatsApp with a prefilled authorized source link; user must press Send.

### Required runtime integration
- A Telegram webhook/polling update receiver must call `route_callback` and render the returned message via `editMessageText` or `sendMessage`.
- The update receiver must answer Telegram callback queries.
- Search, book index and library storage must be connected. The existing `agent.py` is outbound-only.
- `enqueue_request` must be a durable, idempotent, authorized queue, not a direct sending function.
- Telegram: validate authorized destination chat and send document or message only after confirmation.
- Email: verify recipient ownership, use an authenticated email provider, enforce attachment size limits and anti-spam controls.
- WhatsApp: require recorded opt-in, approved Meta Business credentials, actual publicly retrievable document URLs, template/message-window compliance and delivery-status webhooks.
- Do not infer rights to distribute a file from its mere presence in a catalogue.
- `TELEGRAM_ALLOWED_USER_IDS` is a comma-separated allowlist; empty denies all.

### Testing
`python -m unittest discover -s tests -v`

No actual email, Telegram, or WhatsApp delivery is implemented by this UI module.
