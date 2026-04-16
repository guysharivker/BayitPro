# WhatsApp Building Maintenance MVP (Backend)

Minimal FastAPI backend that simulates a WhatsApp-driven maintenance operations workflow.

## Stack
- Python
- FastAPI
- SQLite
- SQLAlchemy ORM
- Pydantic
- Anthropic SDK (optional, for LLM classification)

## Project structure
```text
app/
  main.py
  db.py
  models.py
  schemas.py
  services/
    message_parser.py
    ticket_service.py
    whatsapp_service.py
    seed_service.py
    llm_service.py
    llm_prompts.py
  api/
    routes_webhook.py
    routes_tickets.py
    routes_messages.py
    routes_suppliers.py
    routes_buildings.py
    routes_areas.py
    routes_company.py
```

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Server starts on `http://127.0.0.1:8000`.

## Seed sample data
```bash
curl -X POST http://127.0.0.1:8000/seed
```

If you already have an old database file from the previous MVP schema, reset it with:
```bash
curl -X POST "http://127.0.0.1:8000/seed?reset=true"
```

## Main API endpoints
- `POST /webhook/whatsapp`
- `POST /webhook/twilio` (Twilio WhatsApp inbound adapter)
- `GET /tickets`
- `GET /tickets/{ticket_id}`
- `GET /messages`
- `GET /suppliers`
- `GET /buildings`
- `GET /areas`
- `GET /areas/{id}/summary`
- `GET /company/dashboard`
- `POST /seed`

## Twilio WhatsApp sandbox (optional demo mode)
Set environment variables before running the app:
```bash
export TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxx"
export TWILIO_AUTH_TOKEN="xxxxxxxxxxxxxxxxxxxxxxxx"
export TWILIO_WHATSAPP_FROM="whatsapp:+14155238886"
export ANTHROPIC_API_KEY="sk-ant-..."
```

Then configure Twilio sandbox incoming webhook URL:
`https://<your-ngrok-url>/webhook/twilio`

## Example webhook calls

### 1) Resident creates a new cleaning ticket
```bash
curl -X POST http://127.0.0.1:8000/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+972500000001",
    "text": "יש לכלוך בלובי בבניין רחוב הרצל 22",
    "image_url": null,
    "timestamp": "2026-04-04T12:00:00"
  }'
```

### 2) Same sender updates within 48h (same building), no explicit ticket ref
```bash
curl -X POST http://127.0.0.1:8000/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+972500000001",
    "text": "עדכון: עדיין מלוכלך בבניין רחוב הרצל 22",
    "image_url": null,
    "timestamp": "2026-04-04T16:00:00"
  }'
```

### 3) Supplier marks ticket in progress using explicit reference
```bash
curl -X POST http://127.0.0.1:8000/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+972500000101",
    "text": "#1 בטיפול",
    "image_url": null,
    "timestamp": "2026-04-04T17:00:00"
  }'
```

### 4) Supplier marks ticket done with proof image URL
```bash
curl -X POST http://127.0.0.1:8000/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+972500000101",
    "text": "#1 בוצע",
    "image_url": "https://example.com/proof-cleaning.jpg",
    "timestamp": "2026-04-04T18:00:00"
  }'
```

### 5) Inspect tickets and messages
```bash
curl http://127.0.0.1:8000/tickets
curl http://127.0.0.1:8000/tickets/1
curl http://127.0.0.1:8000/messages
curl http://127.0.0.1:8000/suppliers
```

## Ticket matching logic
For each inbound message, the system chooses ticket target in this order:

1. If text includes explicit reference (`#123` or `TCK-0123`), attach to that ticket if found.
2. Else, if the sender has an open ticket in the last 48 hours for the same extracted building text, attach to the most recent match.
3. Else, create a new ticket.

## Business logic summary
- Workspace hierarchy:
  - Company -> Areas -> Buildings
  - Each area can have its own WhatsApp number
- Role inferred from `contacts.phone_number` (`RESIDENT`, `MANAGER`, `SUPPLIER`).
- Incoming Twilio messages are mapped by `To` number to the relevant area.
- Classification uses Claude if `ANTHROPIC_API_KEY` is set, with regex fallback if the API or package is unavailable.
- Supplier assigned by category mapping.
- SLA due time set by category hours at creation.
- Supplier update keywords:
  - `בוצע` / `done` => `DONE` + `completed_at`
  - `בטיפול` / `in progress` => `IN_PROGRESS`
- Outbound WhatsApp is simulated by:
  - sending via Twilio API when credentials are configured
  - storing outbound rows in `messages` table.
