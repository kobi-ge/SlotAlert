# 🚀 SlotAlert (תור פנוי)

> **Automated, Zero-Overbooking Last-Minute Appointment Cancellation Recovery via WhatsApp on a First-Come, First-Served Basis.**

SlotAlert is a high-performance, lightweight Micro-SaaS built for service businesses (clinics, salons, therapists, studios). When a client cancels an appointment at the last minute, SlotAlert matches waitlisted customers by day and time preferences, dispatches instant WhatsApp notifications with interactive claim buttons, guarantees **zero overbooking** using atomic PostgreSQL + Redis conditional locks, and closes the loop by alerting the business owner the millisecond a slot is won.

---

## 📐 System Architecture

```text
+------------------+         +-----------------------+         +----------------------+
|  Customer Opt-In |         | Business Owner Mobile |         | Background Worker    |
|   (/b/{slug})    |         |  Dashboard PWA (/dash)|         | (Redis Queue + Loop) |
+--------+---------+         +-----------+-----------+         +----------+-----------+
         |                               |                                |
         | Registers Phone & Prefs       | Publishes Canceled Slot        | Batches WhatsApp
         v                               v                                v
+------------------+         +-----------------------+         +----------------------+
|  PostgreSQL 16   | <====== |  Matching Engine      | ======> | Meta WhatsApp Cloud  |
|  - businesses    |         |  - Day of Week (IL)   |         | API (Graph v20.0)    |
|  - services      |         |  - Time Window Match  |         | (Interactive Buttons)|
|  - customers     |         |  - 24h Spam Guard     |         +----------+-----------+
|  - preferences   |         +-----------------------+                    |
|  - slots         |                                                      | Customer Clicks
|  - broadcast_log |                                                      | "אני רוצה את התור!"
+--------+---------+                                                      v
         |                   +-----------------------+         +----------------------+
         |                   |  Atomic Claim Engine  | <====== | Webhook Handler      |
         +================== |  - Redis Distributed  |         | (/webhooks/whatsapp) |
                             |    Key Mutex Lock     |         +----------------------+
                             |  - Conditional UPDATE |
                             |    WHERE status='OPEN'|
                             |    AND version = v    |
                             +-----------+-----------+
                                         |
                                         |  Slot Claimed!
                                         v
                             +-----------------------+
                             | Real-Time Feedback    |
                             | 1. Winner Customer    |
                             | 2. Rejection/Losers   |
                             | 3. Owner Alert (SMS)  |
                             +-----------------------+
```

---

## ⚡ Local Development Quickstart

Run the entire application locally with 3 commands:

```bash
# 1. Start Postgres (5432) and Redis (6337)
docker compose up -d

# 2. Setup Virtual Environment & Dependencies
python -m venv venv
.\venv\Scripts\activate            # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt

# 3. Run Migrations, Seed Demo Data & Start Server
alembic upgrade head
python -m src.database.seed
uvicorn src.main:app --reload --port 8000
```

Access the interfaces:
- **Interactive OpenAPI Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Healthcheck**: [http://localhost:8000/health](http://localhost:8000/health)
- **Customer Opt-In Page**: [http://localhost:8000/b/shiran-clinic](http://localhost:8000/b/shiran-clinic)
- **Business Login**: [http://localhost:8000/login/shiran-clinic](http://localhost:8000/login/shiran-clinic)
- **Business Dashboard**: [http://localhost:8000/dashboard/shiran-clinic?token=master-secret-key](http://localhost:8000/dashboard/shiran-clinic?token=master-secret-key)

---

## 🧪 Automated Testing

Execute the complete 24-test suite covering concurrency, background queue, webhook parsing, PWA opt-in, mobile dashboard, and security:

```bash
pytest -v -s
```

### Concurrency Stress Benchmark:
A 20-client simultaneous race condition test (`test_concurrency.py`) confirms:
- **Exactly 1 winner** claims the slot (`200 OK`, `version` incremented from 1 $\rightarrow$ 2).
- **19 competitors** receive clean conflict rejections (`409 Conflict`).
- **Zero overbooking guaranteed**.

---

## 📱 Core Scenarios & User Flows

### Scenario A: Customer Opt-in (`/b/{slug}`)
1. The customer navigates to `http://localhost:8000/b/shiran-clinic`.
2. Selects interested services, preferred days (`א`-`ו`), and time of day (`בוקר`, `צהריים`, `ערב`).
3. Enters their Israeli phone number (automatically normalized to E.164 `+972...`).
4. Upon submission:
   - Persisted idempotently (phone updates name and preferences cleanly without duplicate key conflicts).
   - Welcome WhatsApp notification dispatched automatically.

### Scenario B: Business Owner Broadcast & Dispatch (`/dashboard/{slug}`)
1. The business owner logs in frictionlessly using a 4-digit PIN sent via WhatsApp (or Magic Link).
2. Taps **"+ פרסם תור שהתבטל"**.
3. Selects service, date, and start time.
4. The dashboard calculates matching waitlisted candidates in real-time.
5. Tapping **"שלח התראה לכל הממתינים עכשיו!"**:
   - Creates the slot in `SENDING` status.
   - Pushes the broadcast task to the Redis asynchronous queue.
   - The queue worker evaluates the **24-Hour Spam Guard** (max 2 alerts per customer per rolling 24 hours).
   - Dispatches interactive WhatsApp messages to eligible recipients.
   - Sets slot status to `OPEN`.

### Scenario C: FCFS Atomic Slot Claiming
1. Recipient receives an interactive WhatsApp card with button: **"אני רוצה את התור! 🎉"**.
2. When tapped, Meta delivers an interactive webhook payload to `/webhooks/whatsapp`.
3. The atomic claim engine acquires a Redis distributed mutex and executes an atomic conditional PostgreSQL query:
   ```sql
   UPDATE slots
   SET status = 'CLAIMED', claimed_by_customer_id = :cust_id, version = version + 1
   WHERE id = :slot_id AND status = 'OPEN' AND version = :current_version;
   ```
4. **Immediate Feedback**:
   - The winning customer receives a personalized confirmation message.
   - Subsequent claimants receive a polite "התור כבר נתפס" notification.
   - The business owner receives an **instant WhatsApp alert**:
     > *"🎉 יש! התור ל-{service} בתאריך {time} נתפס הרגע ע\"י {customer} ({phone})!"*

---

## 🛠️ API Cheatsheet

| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :---: |
| `GET` | `/health` | Application, DB, and Redis health status | No |
| `GET` | `/b/{slug}` | Customer registration PWA landing page | No |
| `GET` | `/api/v1/public/b/{slug}` | Public business profile and services list | No |
| `POST` | `/api/v1/public/b/{slug}/register` | Idempotent customer waitlist opt-in | No |
| `GET` | `/login/{slug}` | Business owner passwordless login page | No |
| `POST` | `/api/v1/auth/{slug}/request-pin` | Request 4-digit PIN dispatched to owner WhatsApp | No |
| `POST` | `/api/v1/auth/{slug}/verify-pin` | Verify PIN and return 30-day JWT access token | No |
| `GET` | `/dashboard/{slug}` | Business management mobile PWA | Yes (Token) |
| `GET` | `/api/v1/business/{slug}/dashboard` | Business metrics & recent slots feed | Yes (Token) |
| `POST` | `/api/v1/business/{slug}/preview-candidates` | Live matched candidate count | No |
| `POST` | `/api/v1/business/{slug}/quick-publish` | Atomically create slot and queue broadcast | Yes (Token) |
| `GET` | `/api/v1/business/{slug}/waitlist` | List all active waitlisted customers | Yes (Token) |
| `POST` | `/api/v1/business/{slug}/waitlist` | Manually register a customer to waitlist | Yes (Token) |
| `POST` | `/api/v1/slots/{slot_id}/claim` | Atomically claim an open slot | No |
| `GET` | `/webhooks/whatsapp` | Meta webhook verification handshake | No |
| `POST` | `/webhooks/whatsapp` | Meta interactive button clicks & delivery receipts | No |

---

## 🔐 Environment Variables Reference

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `PROJECT_NAME` | Project title displayed in OpenAPI | `"SlotAlert"` |
| `ENVIRONMENT` | Deployment environment (`development` / `production`) | `"development"` |
| `BASE_WEB_URL` | Public base URL used for claim links | `"http://localhost:8000"` |
| `ALLOWED_ORIGINS` | CORS allowed origin domains list | `["*"]` |
| `DATABASE_URL` | Async PostgreSQL connection string | `postgresql+asyncpg://...` |
| `REDIS_URL` | Redis cache and task queue connection string | `redis://localhost:6337/0` |
| `WHATSAPP_API_TOKEN` | Meta Graph API bearer access token | `None` (uses Mock provider) |
| `WHATSAPP_PHONE_NUMBER_ID`| Meta WhatsApp business phone number ID | `None` |
| `WHATSAPP_VERIFY_TOKEN` | Secret token verified during Meta Webhook setup | `"slotalert-webhook-verify-token"` |
| `WHATSAPP_APP_SECRET` | App Secret used for `X-Hub-Signature-256` HMAC validation | `None` |
| `WHATSAPP_API_VERSION` | Meta Graph API version | `"v20.0"` |
| `JWT_SECRET` | Cryptographic secret for signing access tokens | `"slotalert-jwt-secret-key-..."` |
| `JWT_ALGORITHM` | JWT signing algorithm | `"HS256"` |
| `ACCESS_TOKEN_EXPIRE_DAYS` | JWT validity duration | `30` |
| `MASTER_ADMIN_KEY` | Master key for emergency owner dashboard access | `"master-secret-key"` |
| `WEB_CONCURRENCY` | Number of Uvicorn worker processes | `2` (local) / `4` (production) |
| `AUTO_SEED` | Automatically run seed script on container start | `false` |

---

## 🚢 Production Deployment Guide

### Option 1: Docker Compose Production Stack (Recommended)

1. **Configure Production Environment**:
   ```bash
   cp .env.production.example .env.production
   nano .env.production    # Fill in production passwords, domain, and Meta WhatsApp tokens
   ```

2. **Launch Stack**:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

The stack automatically boots:
- **`app`**: Multi-stage minimal container (`python:3.11-slim`), non-root user `slotalert`, running Uvicorn behind Gunicorn/Uvicorn workers.
- **`postgres`**: PostgreSQL 16 on persistent volume with automated healthcheck and startup migrations (`alembic upgrade head`).
- **`redis`**: Redis 7 on persistent volume with memory limits (`--maxmemory 256mb --maxmemory-policy noeviction`).
- **`caddy`**: Edge reverse proxy with automated Let's Encrypt SSL certificates, static asset caching, and security headers.

### Option 2: VPS (DigitalOcean / AWS EC2 / Hetzner)
1. Install Docker & Docker Compose plugin on Ubuntu 22.04/24.04:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
2. Clone repository & point DNS A record to your VPS IP address.
3. Set `DOMAIN=yourdomain.com` in `.env.production`.
4. Run `docker compose -f docker-compose.prod.yml up -d --build`.
   *(Caddy will automatically provision and renew valid SSL certificates).*

### Option 3: Render / Railway / Fly.io
1. Connect GitHub repository to Render/Railway.
2. Select **Dockerfile** as the build method.
3. Attach managed PostgreSQL and managed Redis services.
4. Inject environment variables from `.env.production.example`.
5. SlotAlert will automatically wait for dependencies, run `alembic upgrade head`, and start the worker queue inside the application lifespan.

---

## 🔒 Security & Best Practices

- **Zero Monoliths**: Clean layer separation between `models`, `schemas`, `services`, `routers`, and `tasks`.
- **Non-Root Container**: Production image executes under a restricted system user (`slotalert:slotalert`).
- **HMAC Webhook Verification**: All incoming Meta webhooks validate `X-Hub-Signature-256` using SHA-256 HMAC.
- **Strict Rate-Limiting**: Spam guard guarantees no customer receives more than 2 cancellation alerts within 24 hours.
- **Unsubscribe Compliance**: Customers can opt out at any time via interactive button or text keywords (`STOP`, `הסר`, `ביטול`).
