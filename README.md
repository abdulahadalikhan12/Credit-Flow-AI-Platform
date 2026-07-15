# CreditFlow AI Platform

CreditFlow is a multi-tenant, credit-based SaaS platform for AI-assisted content generation and social publishing. It is built as 13 independently deployable backend microservices using FastAPI, communicating asynchronously over RabbitMQ, and using Redis for caching, JWT session state, and streaming fan-out. The frontend is a React (Vite) application served via Nginx.

---

## Service Architecture

### 1. Platform Topology
The platform consists of the following components:
*   **API Gateway**: Stateless reverse-proxy (FastAPI). Verification of RS256 JWTs against Redis JTIs, per-IP and per-account sliding-window rate limiting, Stripe/LinkedIn webhook signature verification/deduplication, and Redis pub/sub SSE token streaming.
*   **Auth Service**: Handles user credentials (bcrypt), verification emails, password recovery, and issues RS256 JWT access tokens.
*   **User/Tenant Service**: Manages accounts (individual workspace created on signup; team workspaces), workspace members (Owner, Admin, Member), and team invites.
*   **Billing Service**: Coordinates Stripe Checkout sessions for plans and proration. Employs the Transactional Outbox pattern to safely publish billing events to RabbitMQ.
*   **Credits/Marketplace**: Append-only transaction ledger (`credits_ledger`) and credit sales marketplace. Peer-to-peer credit transfers are processed inside atomic database transactions.
*   **Usage/Metering Service**: Real-time Redis counters for fast generation pre-checks, reconciled periodically with a PostgreSQL ledger via a background worker.
*   **AI Generation Service**: Wraps OpenRouter for streaming chat completions (text) and Pollinations.ai for image generation. Streams token chunks to Redis Pub/Sub channels for API Gateway SSE fan-out.
*   **Content Service**: Draft creation and versioned history tracking for posts. Supports manual image uploads to local volumes.
*   **Scheduler Service**: A Celery Beat scanner that checks for due scheduled posts and emits triggers to RabbitMQ, supporting recurring schedules (daily, weekly, monthly).
*   **Social Publishing Service**: Manages LinkedIn Oauth connections (encrypted with Fernet at rest) and UGC publishing (attaching images via LinkedIn's Images API if available).
*   **Scraper Service**: Web crawler respecting `robots.txt` that saves raw unstructured HTML data to MongoDB.
*   **Notification Service**: Connects to Resend for sending transactional emails and posts billing/publishing alerts to Slack webhooks.
*   **Admin/Ops Service**: Listens to `#` on the broker to record a global audit trail, and exposes endpoints to revoke JWT sessions by deleting JTI keys from Redis.

---

## Local Development & Setup

### Prerequisites
1.  [Docker and Docker Compose](https://docs.docker.com/engine/install/)
2.  (Optional) Python 3.11+ (for local scripts/tests)

### 1. Configure Credentials
Copy `.env.example` to `.env` and fill in API keys:
```bash
cp .env.example .env
```
For sandbox/local testing:
*   If `LINKEDIN_CLIENT_ID` is left empty or as placeholder, the Social service will operate in **Mock Connection Mode** automatically.
*   If `OPENROUTER_API_KEY` is not present, the AI service will run in **Simulated Token-by-Token Streaming Mode** automatically, making it 100% testable offline.
*   Stripe Webhooks and Checkout will automatically degrade to simulated sandbox redirects if payment keys are invalid.

### 2. Run the Stack
Start all services (databases, queues, cache, microservices, and frontend) using Docker Compose:
```bash
docker-compose up --build
```
This command:
1.  Starts PostgreSQL, MongoDB, Redis, and RabbitMQ.
2.  Runs the database initialization script to dynamically create 11 separate Postgres databases (one for each microservice).
3.  Boots up all 13 backend services (automatically waiting for database readiness and bootstrapping schema tables on boot).
4.  Launches the React frontend.

### 3. Verify Services
Open the following urls:
*   **React Frontend Dashboard**: [http://localhost:3000](http://localhost:3000)
*   **API Gateway entrypoint**: [http://localhost:8000/health](http://localhost:8000/health)
*   **RabbitMQ Management Console**: [http://localhost:15672](http://localhost:15672) (User: `guest`, Pass: `guest`)

---

## Testing Scenarios

1.  **Signup & Verification**: Register on the signup page. Click the "Complete Sandbox Verification Link Click" button on screen to simulate clicking the email verification link.
2.  **AI Streaming Content**: Head to the **Content Studio**, type a prompt, and click **Generate Text**. Watch tokens stream chunk-by-chunk in real-time.
3.  **Upgrade Billing**: Go to **Billing**, select Pro or Team plan, and click Upgrade. If your Stripe secret key is valid, it redirects to the Stripe Sandbox Checkout; otherwise, it redirects to a simulated success page.
4.  **Marketplace**: List credits for sale from one workspace. Switch workspaces (or create another account) to buy credits peer-to-peer.
5.  **Audit Logs & Revocation**: Log in with an account having `superadmin` role (or edit headers). Navigate to **Audit Trail** to see the RabbitMQ events logged dynamically, or **Active Sessions** to revoke live access tokens instantly.
