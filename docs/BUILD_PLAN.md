# FixTrail Build Plan

> This is the original build plan and the instructions for AI coding assistants (Claude Code).
> For what FixTrail is and how to run it, see the [README](../README.md). The design review is in
> [DESIGN_REVIEW.md](DESIGN_REVIEW.md).

> **Hackathon:** Amazon Developer Hackathon
> **Primary track:** Alexa+ (self-hosted MCP server over Streamable HTTP, plus an Agent Skill and an Alexa+ simulator web app)
> **Mini challenge:** AWS Builder (Amazon Bedrock + Strands Agents SDK power the simulator; SES + S3 in production)
> **Optional stretch:** Ring integration (repair-visit evidence via Ring APIs)
> **Built with:** Claude Code

---

## 0. Instructions for Claude Code (read this first)

You are helping a **first-time developer** build this project for a hackathon. Please:

1. **Work phase by phase** (see Section 8). Finish one phase, run its checks, and explain what you did in plain language before moving on.
2. **Explain as you go.** The developer is new to Python, MCP, and AWS. Briefly explain each new concept, command, and file.
3. **Verify, don't assume.** Before writing MCP code, check the current official MCP Python SDK docs and confirm the installed version supports **MCP spec 2025-11-25 or later** and the **Streamable HTTP** transport. If the SDK API differs from examples in this file, follow the real SDK.
4. **Follow the hackathon's Alexa+ resources** (summarized in "Hackathon resources" below). They allow simulating Alexa+ with a web app; a real Alexa+ connection is optional. Do not invent a connection method. If something is unclear, tell the developer to ask at hackathon office hours.
5. **Never commit secrets.** Use a `.env` file (listed in `.gitignore`) and provide `.env.example`.
6. **Ask before** creating AWS resources, spending money, or deploying.
7. **Keep it simple.** Prefer fewer dependencies and readable code over clever code.
8. **Keep a friction log** (Section 11) whenever something is confusing, broken, or poorly documented. It earns up to a 10% judging bonus.
9. **Read the design review** ([DESIGN_REVIEW.md](DESIGN_REVIEW.md)). It explains why key design choices exist, such as the honest labels and email fingerprints. Don't remove or weaken them.

### Hackathon resources (what the official Resources page says)
- **Alexa+ track:** "Build a working MCP (Model Context Protocol) integration on the open standards for Agent Skills and Streamable HTTP transports. You can simulate an Alexa+ experience using your preferred agentic tools via a web app." So the deliverables are: (1) the MCP server over Streamable HTTP, (2) an Agent Skill following the [Agent Skills](https://agentskills.io/) standard (a folder with a `SKILL.md`), and (3) a web app that simulates Alexa+.
- **AWS Builder mini challenge:** "incorporate AWS services with documented integrations: Amazon Bedrock, AgentCore, the Strands SDK, Kiro, SageMaker, and more. The AWS free tier is enough to get started."
- **Open Source mini challenge (optional):** contribute to any open-source repository during the hackathon window.
- **AWS credits:** "October 7th Update: we are out of credit codes." Any AWS cost is on the developer's own account, so keep usage small and set a billing alert.
- **Live office hours:** schedule and join link are on the hackathon landing page.
- **Open question for office hours:** is a web-app simulation of Alexa+ acceptable for the demo video, or must it show the real Alexa+? (The Resources page suggests simulation is fine.)

---

## 1. The Problem

When something breaks in a rental home (heat, water leak, mold, broken lock), tenants report it to the landlord. Disputes often follow:

- Tenants say "I reported this five times." Landlords say "I was never told."
- Landlords say "I sent a plumber and the tenant didn't let them in." Tenants disagree.
- Housing offices, mediators, and courts need **dated, trustworthy records**, and usually nobody has them. Records are scattered across texts, calls, and memory.

A tenant's private notes are weak evidence, because anyone can write anything. A good solution has to be **fair to both sides** and **hard to fake**.

## 2. The Solution

FixTrail is a **neutral, shared, tamper-evident repair record**.

- The tenant reports problems **by voice through Alexa+** ("Alexa, the heater stopped working again").
- Every report is **automatically sent to the landlord** by email, so there is proof the landlord was notified.
- The tenant can attach **timestamped photos** of the problem in two ways: through a **web upload page**, or by **replying to a FixTrail email with photos attached**.
- The landlord gets a **secure link** to respond: acknowledged, repair scheduled, fixed.
- Every event goes into an **append-only log** with server timestamps and a **hash chain**, so entries cannot be edited, deleted, or backdated without detection.
- Either side can generate a **clean, dated report** of the full history.

**Key design principle:** FixTrail does not take sides. It protects honest tenants (proof they reported and were ignored) **and** honest landlords (proof they responded quickly). Fake claims are hard to make because every claim is sent to the other party immediately.

**Honesty labels:** Events the system can verify (for example, an email it actually sent) are marked **verified**. Events only the tenant claims (for example, "I phoned the landlord") are logged but clearly marked **tenant-reported (unverified)**.

## 3. Example Voice Interactions

| Tenant says | What happens |
|---|---|
| "Alexa, the kitchen sink is leaking." | Issue created, landlord emailed, confirmation spoken, tenant gets a confirmation email ("Reply with photos to add them") |
| "Alexa, what's still broken?" | "2 open issues. The sink leak has been open 9 days, landlord acknowledged it 7 days ago. The heater has been open 3 days, no landlord response yet." |
| "Alexa, remind my landlord about the heater." | A follow-up email is sent and logged as verified |
| "Alexa, I called the landlord about the sink." | Logged as tenant-reported (unverified) |
| "Alexa, the sink is fixed." | Tenant confirms the fix, issue closed |
| "Alexa, make my repair report." | Report generated, link sent to the tenant's email |

## 4. Architecture

```
 Tenant's voice
      |
   Alexa+  --(MCP over Streamable HTTP)-->  FixTrail Server (Python)
                                              |-- MCP tools (/mcp)
                                              |-- Web pages (tenant photos, landlord replies, reports)
                                              |-- Event log (append-only, hash-chained)
                                              |-- Storage: SQLite (local) / persistent storage (prod)
                                              |-- Email out: console (local) / AWS SES (prod)
                                              |-- Email in (photo replies): inbox/ folder (local) / SES receiving (prod)
                                              |-- Photos: local folder (local) / AWS S3 (prod)

 Tenant's email app --(reply with photo)--> SES receiving --> FixTrail inbound handler --> Event log

 Alexa+ simulator (web page /simulator)
   mic (browser speech recognition) --> Strands agent + Amazon Bedrock model + FixTrail Agent Skill
        --(MCP over Streamable HTTP)--> FixTrail /mcp --> spoken reply (browser speech synthesis)
```

The simulator stands in for Alexa+ exactly where Alexa+ would sit: it is an MCP client that discovers FixTrail's tools and calls them. A real Alexa+ connection, if access becomes available, uses the same `/mcp` endpoint.

**One server, two faces:**

1. **MCP endpoint** at `/mcp` for Alexa+ (and for testing with MCP Inspector).
2. **Web pages** for things voice can't do well: uploading photos, landlord responses, viewing reports.

Suggested approach: a FastAPI (or Starlette) app that serves the web pages, with the MCP SDK's Streamable HTTP app mounted at `/mcp`. Confirm the exact mounting method in current SDK docs.

**Local vs. production:** Every external service sits behind a small interface so the project runs fully locally with no AWS account.

| Concern | Local dev | Production |
|---|---|---|
| Database | SQLite file | Decide in Phase 7 (see note) |
| Email | Print to console + save to `outbox/` | AWS SES |
| Photos | `uploads/` folder | AWS S3 |
| Inbound email (photo replies) | Drop `.eml` files into `inbox/` and run an ingest script | AWS SES email receiving |

> **Note on production storage:** Some AWS hosting options (like App Runner) do not keep local files between deploys, so a SQLite file there can be lost. In Phase 7, Claude Code should recommend the simplest persistent option, such as a small EC2/Lightsail instance with SQLite on disk, or DynamoDB, and explain the tradeoff.

## 5. Data Model

### `properties`
| field | type | notes |
|---|---|---|
| id | text (uuid) | |
| address | text | |
| tenant_name | text | |
| tenant_email | text | |
| landlord_name | text | |
| landlord_email | text | |

For the hackathon demo, one property configured via `.env` or a seed script is fine.

### `issues`
| field | type | notes |
|---|---|---|
| id | text (uuid) | |
| property_id | text | |
| title | text | e.g. "Kitchen sink leaking" |
| location | text | e.g. "kitchen" |
| category | text | heat, water, electrical, pest, mold, lock, appliance, other |
| urgency | text | emergency, urgent, routine |
| status | text | open, acknowledged, scheduled, landlord_marked_fixed, closed, disputed |
| created_at | text | server UTC timestamp |

Issue `status` is **derived from events**. It is a cached convenience, and events are the source of truth.

### `events` (append-only, the heart of the system)
| field | type | notes |
|---|---|---|
| id | integer | auto-increment, sequential |
| issue_id | text | |
| type | text | see list below |
| actor | text | tenant, landlord, system |
| verification | text | verified, tenant_reported, or landlord_reported |
| payload | text (JSON) | details, e.g. message text, photo hash |
| created_at | text | **server** UTC timestamp, never client-supplied |
| prev_hash | text | hash of the previous event |
| hash | text | sha256(prev_hash + canonical JSON of this event's fields) |

**Event types:**
- `issue_reported`: tenant created an issue
- `landlord_notified`: system sent an email (verified; payload stores the message ID and a copy of the text)
- `follow_up_sent`: system sent a reminder (verified)
- `tenant_contact_claimed`: tenant says they called or texted (tenant_reported)
- `photo_added`: payload stores the S3/local key, the **sha256 of the image file**, and `source` (`web_upload` or `email_reply`). For email photos, also store the sender address, the email's Message-ID, and the SES spam/authentication verdicts. If the image has an EXIF "taken at" date, store it as extra info, but the **verified time is always the server's receipt time**.
- `landlord_acknowledged`, `landlord_scheduled` (payload: date/time), `landlord_marked_fixed`, `landlord_comment`
- `access_issue`: landlord reports they couldn't get in (labeled `landlord_reported`)
- `tenant_confirmed_fixed`, `tenant_disputed_fix`

### `tokens`
| field | type | notes |
|---|---|---|
| token | text | long random secret (about 256 bits) |
| issue_id | text | |
| purpose | text | `landlord` (the `/respond/{token}` link) or `photo_reply` (the `photos+{token}@domain` Reply-To address) |
| created_at | text | |

One table serves both kinds of secret link. A token only works for its own purpose, so a landlord link can't be used to email in photos, and vice versa.

**Verification labels follow one rule:** `verified` means FixTrail itself witnessed the act (it received the report or photo, sent the email, or recorded the landlord's click). `tenant_reported` and `landlord_reported` mean someone described something FixTrail could not see, such as a phone call or a visit where nobody answered the door.

### Tamper-evidence rules
- The app code **never** runs `UPDATE` or `DELETE` on `events`. Enforce this in the data-access layer, and add a SQLite trigger that blocks updates and deletes on `events`.
- Each event's `hash` links to the previous event (hash chain). Provide a `verify_chain()` function and a `/verify` page that recomputes all hashes and reports **"Record intact"** or **the first broken entry**.
- Use canonical JSON (sorted keys, no extra whitespace) when hashing, so results are reproducible.

### Who guards the record? Fingerprints in every email
The hash chain alone has a known weakness: whoever runs the server could rewrite the whole log and recompute every hash, and `/verify` would still pass. To close this gap, FixTrail **anchors the chain outside its own control**:

- **Every email FixTrail sends** (to tenant or landlord) ends with a footer like:
  `Record fingerprint after event #14: 3f9a…c21` (show the first and last characters; include the full hash in a plain-text line for checking).
- These emails sit in the tenant's and landlord's inboxes, where FixTrail cannot change them. If history is rewritten later, fingerprints in old emails will no longer match.
- The **verify page** gets a "Check a fingerprint" box: paste an event number and fingerprint from any old email, and it confirms whether that event's hash still matches.
- Tenant and landlord become **each other's witnesses**, which fits the neutral design.
- Implementation: after each `append_event()`, read the newest hash and pass it, with the event number, into the email footer template. Add a `check_fingerprint(event_id, hash)` function plus a test showing that a rewritten log fails an old fingerprint.
- **Demo moment:** rewrite the database and recompute all hashes, show `/verify` still passing, then paste the fingerprint from an old email and show it failing. This proves the record is guarded by outside witnesses, not just by FixTrail.

## 6. MCP Tools (for Alexa+)

Write clear tool descriptions. Alexa+ uses them to decide which tool to call. Return short, speakable text (Alexa reads it aloud) plus structured data where the SDK supports it.

| Tool | Inputs | Behavior | Spoken response example |
|---|---|---|---|
| `report_issue` | title, location, category?, urgency? | Creates issue, logs `issue_reported`, emails landlord, logs `landlord_notified` | "Got it. I logged the kitchen sink leak and emailed your landlord." |
| `list_open_issues` | none | Lists open issues with days open and the latest landlord response | "You have 2 open issues…" |
| `get_issue_history` | issue (title or id) | Short spoken summary of the timeline | "The heater was reported 12 days ago. Your landlord was emailed twice and hasn't responded." |
| `send_follow_up` | issue | Emails landlord a reminder, logs `follow_up_sent` | "I sent your landlord a reminder about the heater." |
| `log_contact_attempt` | issue, method (call, text, in person), note? | Logs `tenant_contact_claimed` as tenant_reported | "Noted. I've marked it as something you reported, since I can't verify calls." |
| `confirm_fixed` | issue | Logs `tenant_confirmed_fixed`, closes issue | "Great, I've closed the sink issue." |
| `dispute_fix` | issue, reason | Logs `tenant_disputed_fix`, emails landlord | "I've recorded that the heater still isn't working and told your landlord." |
| `generate_report` | issue? (default: all) | Builds report, emails the tenant a link | "Your report is ready. I've emailed you the link." |
| `get_photo_upload_link` | issue | Emails the tenant a message with the upload page link; replying to that email with photos also works | "I've emailed you. Reply with photos, or use the link inside." |

**Matching issues by name:** Users will say "the heater," not an ID. Implement simple fuzzy matching on title and location among open issues. If more than one matches, return a short clarifying question.

## 7. Web Pages

Keep these simple, clean, and mobile-friendly. Plain HTML templates (Jinja2) plus minimal CSS is fine.

1. **Tenant dashboard** (`/`): open and closed issues with days open and a status badge.
2. **Issue timeline** (`/issues/{id}`): every event in order, with timestamp, actor, and a **verified** or **tenant-reported** label, plus photos.
3. **Photo upload** (`/issues/{id}/photos`): upload image, store file, compute sha256, log `photo_added`.
4. **Landlord response page** (`/respond/{token}`): no login. Shows the issue and photos, with buttons: Acknowledge, Schedule repair (date picker), Mark fixed, Couldn't get access, Add comment. Each button logs an event.
5. **Report** (`/reports/{id}`): printable, dated summary (property, each issue, full timeline, days open, response times, photo thumbnails, verification labels, chain-integrity status). PDF export is a stretch goal.
6. **Verify** (`/verify`): runs `verify_chain()` and shows the result, plus a "Check a fingerprint" box where anyone can paste an event number and fingerprint from an old email.

### 7b. Second photo channel: reply by email

Tenants often take photos on their phone at the moment a problem happens. Replying to an email is the easiest possible way to send them.

**How it works:**
1. Whenever an issue is created (and when `get_photo_upload_link` is called), the tenant receives an email such as: *"FixTrail logged: Kitchen sink leaking. Reply to this email with photos to add them to the record."*
2. The email's **Reply-To** address identifies the issue, for example `photos+<issue_token>@<your-domain>`. The token is long and random, so it can't be guessed.
3. The tenant replies with one or more photos attached, with no app or login needed.
4. FixTrail receives the email, checks it, extracts the image attachments, stores them (S3 in production), computes each file's sha256, and appends a `photo_added` event with `source: email_reply`.
5. FixTrail sends a short confirmation: *"2 photos added to: Kitchen sink leaking."*

**Checks before accepting (to keep the record trustworthy):**
- The sender address must match the tenant's registered email.
- The issue token must be valid and the issue must exist.
- Use the SPF/DKIM and spam/virus verdicts that SES provides for received mail, and reject messages that fail.
- Accept only image types (JPEG, PNG, HEIC; convert HEIC to JPEG for display) and enforce a size limit.
- Ignore the email's body text for the record, or store it only as a tenant comment labeled tenant-reported.

**Implementation notes (Claude Code: verify against current AWS docs):**
- Production: an SES **email receiving** rule set stores incoming mail in S3, then triggers processing (for example an SNS notification or Lambda that calls a protected FixTrail endpoint). SES email receiving is only available in certain AWS regions and requires a domain you control with an MX record pointing to SES. Check region support and setup steps first.
- Local development: an `inbox/` folder plus `scripts/ingest_email.py` that parses `.eml` files with Python's built-in `email` library and runs the same processing code. This lets you build and test without any AWS setup.
- Put the shared logic in `app/inbound_email.py` so local and production use identical code.
- If domain or region setup blocks you, the web upload page still works, so record the blocker in the friction log and move on.

**Demo security note:** For the hackathon, a single configured tenant with a simple passcode on tenant pages is acceptable. Landlord pages use unguessable tokens. Document these limits honestly in the README "Limitations" section.

## 8. Build Phases (do these in order)

### Priorities: scope is the biggest risk
A polished, working core beats an ambitious project that's half finished.

| Must have (the demo depends on it) | Nice to have | Skip unless ahead of schedule |
|---|---|---|
| Phases 1–6: setup, event log + email fingerprints, tools, web pages, reports, Agent Skill + Alexa+ simulator | Photos by email, local version (5b); AWS deploy with real email (7) | Real SES email receiving; real Alexa+ device connection (6d); Ring (8) |

**Progress (October 14, 2026):** Phases 1–6c are built (120 tests passing). The simulator runs in offline mode; Bedrock, SES, S3, and SNS code is written and stub-tested, waiting only for an AWS account. Also done: Dockerfile (built and run locally), demo data and tamper demo scripts, privacy and terms pages, security headers, README, screenshots, AWS.md, and PRODUCT_FEEDBACK.md. Remaining: AWS account and go-live (Phase 7), demo video, submission.

**About Phase 1.5:** the hackathon's Resources page allows simulating Alexa+ with a web app, so the real-Alexa+ smoke test below is now optional reference material (Phase 6d), not a blocker.

### Phase 1: Setup and "hello world" MCP server
- Create the repo structure (Section 9), virtual environment, `requirements.txt`, `.gitignore`, `.env.example`, `LICENSE` (MIT).
- Install the official MCP Python SDK and confirm the version and spec support.
- Create one tool, `ping`, that returns "FixTrail is running."
- Run the server with Streamable HTTP at `/mcp`.
- **Check:** Connect with **MCP Inspector**, list tools, call `ping`.
- **Explain to developer:** What MCP is, what a "tool" is, what Streamable HTTP means.

### Phase 1.5: Real Alexa+ connection (optional reference for Phase 6d)
Only needed if the team gets real Alexa+ access. Verified against Amazon's Alexa+ add-on docs (October 2026). Official pages: [Docs home](https://developer.amazon.com/docs/alexaplus/add-ons/home.html), [Set up your environment](https://developer.amazon.com/docs/alexaplus/add-ons/set-up-your-development-environment.html), [MCP QuickStart](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html), [Authentication](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-authentication.html), [Account linking](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-account-linking.html).

**Prerequisites (sort these out first):**
- **Access.** The docs say the MCP Toolkit is "available to select partners only," and setup uses an AWS account registered with an Alexa Solutions Architect plus a private npm registry (CodeArtifact). Ask the hackathon organizers how participants get access.
- **Operating system.** The CLI officially supports macOS or Ubuntu, not Windows. On Windows, use WSL (Ubuntu inside Windows).
- **Node.js 24 or later.**
- **Accounts:** a free Alexa developer account (an existing Amazon account works) and an AWS account.

**Steps:**
1. Install and log in: `npm install -g @alexa-ai/cli`, then `alexa-ai configure` (opens a browser for Login with Amazon).
2. Run the server and expose it over public HTTPS with a tunnel such as `cloudflared`.
3. Create the add-on, either with the docs' coding-agent path or manually: `alexa-ai new mcp --name "FixTrail" --locale en-US --mcp-server-url "<tunnel URL>/mcp"`.
4. Fill in `addon-package/addon.json`: short description (up to 123 characters), full description, 3–4 example phrases, **privacy policy and terms URLs**, and icons (six sizes plus one carousel image).
5. Deploy with `alexa-ai deploy`, then test in the Alexa+ web simulator. Run `alexa-ai deploy` again whenever tools change, because Alexa+ refreshes tool info only on deploy.

- **Check:** Alexa+ calls `ping` successfully.
- **If it doesn't work:** write a friction log entry, ask at office hours, and rely on the simulator (Phase 6b–6c).

**Requirements that affect the whole design (already followed, so a real connection stays possible):**
- **Spec and transport:** MCP spec 2025-11-25 over Streamable HTTP (Phase 1 already does this).
- **Speed:** responses must come back in **under 500 ms**. Tools must never wait on slow work, so send emails in the background after replying.
- **Account linking (OAuth 2.1 with PKCE S256) is optional in the docs,** but recommended when tools access user-specific data or take actions for the user, which FixTrail does. Plan: run the smoke test without it, then add it in Phase 6 if time allows (the single-tenant demo works without it). If added, the server must:
  - return `401` or `403` without a valid token, **without** a `WWW-Authenticate` header
  - host `/.well-known/oauth-protected-resource` (fields `resource`, `authorization_servers`, `scopes_supported`)
  - support PKCE S256 and static client registration
  - The MCP Python SDK has built-in auth hooks (`token_verifier`, `auth_server_provider`); check them before writing custom code.
- **Learning from other entrants:** reading another participant's public code to understand the OAuth setup is fine, but don't copy it.

### Phase 2: Database and event log
- SQLite schema for all tables, with a trigger blocking UPDATE/DELETE on `events`.
- Data-access layer with an `append_event()` function that sets the server timestamp and computes the hash.
- `verify_chain()` function.
- `check_fingerprint(event_id, hash)` function (see "Who guards the record?").
- Seed script for one demo property.
- **Check:** pytest tests show that events append correctly, the hash chain verifies, manual tampering in the DB is detected, UPDATE/DELETE are blocked, and **a fully rewritten and rehashed log fails an old fingerprint check**.

### Phase 3: Core MCP tools
- Implement `report_issue`, `list_open_issues`, `get_issue_history`, `log_contact_attempt`, `confirm_fixed`, `dispute_fix`.
- Email goes through a `Mailer` interface. For now, `ConsoleMailer` prints and saves to `outbox/`.
- Every outgoing email includes the record fingerprint footer with the event number.
- Fuzzy issue matching.
- **Check:** In MCP Inspector, run a full scenario: report, list, history, confirm fixed. Inspect `outbox/` and the events table.

### Phase 4: Web pages
- FastAPI app serving templates, with MCP mounted at `/mcp` in the same process.
- Dashboard, timeline, photo upload (local storage + sha256), landlord response page with tokens, verify page.
- Landlord emails include the `/respond/{token}` link.
- **Check:** Report an issue via MCP, open the landlord link from `outbox/`, click "Schedule repair," and see it appear on the tenant timeline and in `list_open_issues`.

### Phase 5: Follow-ups and reports
- `send_follow_up`, `generate_report`, `get_photo_upload_link` tools.
- Report page with response-time stats (for example, "Landlord first responded after 6 days").
- **Check:** The generated report looks clean when printed from the browser.

### Phase 5b: Photos by email reply (local version)
- Tenant confirmation emails with a per-issue Reply-To token (Section 7b).
- `app/inbound_email.py` with the sender, token, and attachment checks.
- `scripts/ingest_email.py` to process `.eml` files from `inbox/`.
- **Check:** Save a sample reply email with a photo as an `.eml` file, run the ingest script, and see the photo appear on the issue timeline labeled "via email." Test that emails from the wrong sender or with a bad token are rejected.
- Production wiring (SES receiving) happens in Phase 7.

### Phase 6: Agent Skill and Alexa+ simulator
The hackathon's Alexa+ track asks for an MCP integration on the open standards for Agent Skills and Streamable HTTP, and allows simulating Alexa+ with a web app.

**6a. Agent Skill** (no AWS needed)
- `skills/fixtrail/SKILL.md` following the [Agent Skills specification](https://agentskills.io/specification): frontmatter with `name` and `description`, then instructions on when and how to use FixTrail's MCP tools.
- Cover: voice style (short, speakable answers), passing the tenant's own words as the issue, never inventing facts, and the honest labels (verified vs. tenant-reported).
- **Check:** the skill passes the reference validator (or a manual check against the spec), and an agent loaded with it handles the Section 3 scenarios.

**6b. Alexa+ simulator page** (no AWS needed)
- `/simulator`: a microphone button using the browser's built-in speech recognition, spoken replies with the browser's speech synthesis (free in Chrome and Edge), a typed-input fallback, and a chat transcript.
- Make it clear on the page that it simulates Alexa+.
- **Check:** works in Chrome and Edge; typed input works in any browser.

**6c. The agent** (needs AWS for Bedrock)
- A Strands Agents SDK agent using an Amazon Bedrock model, connected to FixTrail's `/mcp` as an MCP client, with the Agent Skill as its instructions.
- Keep the model small and cheap; credits are no longer available, so costs are on the developer's account.
- Build and test first with a stand-in model; switch on Bedrock once the AWS account exists. Ask before enabling anything that costs money.
- **Check:** complete the Section 3 voice scenarios in the simulator.

**6d. Real Alexa+** (optional)
- Only if access becomes available; see Phase 1.5.

- **Throughout:** tune tool descriptions and spoken responses based on how the agent behaves, and log any friction.

### Phase 7: AWS deployment (ask developer before creating resources)
- Choose hosting plus persistent storage (see Section 4 note) and explain the options and costs.
- Implement `SESMailer` (AWS SES; note SES sandbox mode requires verifying sender and recipient emails, which is fine for a demo).
- Implement `S3PhotoStore`.
- Set up SES email receiving for photo replies (needs a domain and a supported region; see Section 7b).
- Containerize with a `Dockerfile`.
- Document all AWS services used in `docs/AWS.md` (required for the AWS Builder mini challenge): Bedrock and Strands (simulator), SES, S3, and hosting.
- Set a billing alert first. There are no hackathon credits, so prefer free-tier options and small models.
- **Check:** The public HTTPS URL works, real emails arrive, and photos are stored in S3.

### Phase 8 (stretch): Ring integration
- Using the Ring simulator/APIs provided by the hackathon, detect a visitor event at the door during a scheduled repair window and log it as `repair_visit_detected` (verified by device) with the time.
- Only attempt this after Phases 1–7 work.

### Phase 9: Polish and submission
- Complete this README's "Running locally," "Deploying," and "Limitations" sections with real, tested commands.
- Add screenshots to `docs/`.
- Run the full demo script (Section 10) end to end.
- Complete the submission checklist (Section 12).

## 9. Repository Structure

```
fixtrail/
├── README.md
├── LICENSE
├── .env.example
├── .gitignore
├── requirements.txt
├── Dockerfile
├── app/
│   ├── main.py            # FastAPI app; mounts MCP at /mcp
│   ├── mcp_tools.py       # MCP tool definitions (thin wrappers)
│   ├── services.py        # what each action does; shared by tools and web pages
│   ├── web.py             # web pages: dashboard, timeline, landlord, photos, reports, verify
│   ├── db.py              # schema, append_event, verify_chain, check_fingerprint
│   ├── models.py          # status derivation, issue matching, wording
│   ├── mailer.py          # Mailer interface, ConsoleMailer, SESMailer (Phase 7)
│   ├── photos.py          # PhotoStore interface, LocalPhotoStore, S3PhotoStore (Phase 7)
│   ├── inbound_email.py   # checks + processing for photo reply emails
│   ├── reports.py         # report stats, built only from the event log
│   ├── simulator.py       # Alexa+ simulator agent: Strands + Bedrock (Phase 6)
│   ├── config.py          # loads .env
│   └── templates/         # Jinja2 HTML templates
├── skills/
│   └── fixtrail/
│       └── SKILL.md       # Agent Skill (Phase 6a)
├── scripts/
│   ├── seed.py            # demo property and sample data
│   ├── try_it.py          # run a voice scenario against a running server
│   ├── make_test_reply.py # local: create a tenant photo-reply .eml in inbox/
│   └── ingest_email.py    # local: process .eml files from inbox/
├── tests/
│   ├── test_event_log.py
│   ├── test_tools.py
│   ├── test_web.py
│   └── test_inbound_email.py
└── docs/
    ├── AWS.md
    ├── FRICTION_LOG.md
    ├── PRODUCT_FEEDBACK.md
    └── screenshots/
```

## 10. Demo Video Script (under 3 minutes, best material first)

**Framing:** FixTrail is **evidence for when things go wrong**, not a promise that repairs get done faster. It works even if the landlord never clicks anything, because proof of notice comes from the emails themselves.

1. **0:00–0:20 Hook.** "Repair disputes come down to one question: who told whom, and when? FixTrail keeps a record of that both sides can trust." (Don't use a statistic unless you've verified it.)
2. **0:20–1:00 Voice flow.** In the Alexa+ simulator (or real Alexa+, if available), the tenant says the heater is broken, the landlord's email arrives (point out the fingerprint footer), then "Alexa, what's still broken?" Say clearly that the simulator stands in for Alexa+ and uses the same MCP endpoint.
3. **1:00–1:25 Two landlords.** For one issue, the landlord ignores it, and the timeline still shows proof of notice and days unanswered. For another, the landlord schedules a repair, and the record protects them too.
4. **1:25–2:10 Trust.** Show verified vs. tenant-reported labels and a photo's fingerprint. Then the key moment: rewrite the database and recompute every hash, show `/verify` still passing, paste the fingerprint from an old email, and show it **failing**. "FixTrail can't secretly rewrite history, because both parties hold witnesses."
5. **2:10–2:40 Report.** "Alexa, make my repair report," then show the clean dated report.
6. **2:40–2:55 Close.** Who it helps (tenants, fair landlords, housing advocates and mediators) and that it runs on Alexa+ and AWS.

Use only your own footage and royalty-free or no music. No third-party trademarks without permission.

## 11. Friction Log Template (`docs/FRICTION_LOG.md`)

Add an entry every time something is confusing or broken:

```
### Entry N: <short title>
- Tool/API/SDK:
- Task attempted:
- Steps taken:
- Expected:
- Actually happened:
- Severity: critical / high / medium / low
- Workaround:
- Suggestion for Amazon:
```

## 12. Submission Checklist

- [ ] Text description of the project (what it does, how it works)
- [ ] GitHub repo with all source, assets, and run instructions
- [ ] Repo is **public with an open-source LICENSE**, or private and shared with testing@devpost.com and the Amazon reviewers listed on the **official Devpost page** (verify the list there; add reviewers at submission time, because invites expire after 7 days)
- [ ] Code actually calls MCP (a real server entry point, not just mentioned in the README)
- [ ] Demo video under 3 minutes, public on YouTube or Vimeo, in English, showing the MCP server working with Alexa+ (confirm at office hours that the Alexa+ simulator is acceptable)
- [ ] Agent Skill included (`skills/fixtrail/SKILL.md`) and referenced in the description
- [ ] Product feedback for every tool used (MCP SDK, MCP Inspector, Alexa+ docs, Strands, Bedrock, SES, S3, etc.): what you used it for, what worked, what needs work, onboarding experience, whether you'd use it again
- [ ] Track: Alexa+. Mini challenge: AWS Builder, with `docs/AWS.md` describing the services used
- [ ] Optional: Open Source mini challenge (a contribution to any open-source repo during the hackathon window)
- [ ] Friction log (`docs/FRICTION_LOG.md`) for the up to 10% bonus
- [ ] Optional: feature requests (critical / important / nice-to-have)

## 13. Limitations and Responsible Use (keep in final README)

- FixTrail is a **record-keeping tool, not legal advice**. Tenant laws and notice requirements vary by state and city. Whether records are accepted as evidence is up to the relevant court or agency.
- Tenant-reported events (calls, in-person conversations) cannot be verified and are labeled as such.
- Email delivery proves a message was sent, not that it was read. Messages from an unfamiliar service may land in spam.
- Some leases or local laws require specific notice methods (for example, certified mail). FixTrail's emails may not satisfy those requirements on their own.
- FixTrail proves notice and documents what happened. It cannot force a landlord to make repairs. Its value is the evidence a tenant can bring to a housing inspector, mediator, or court.
- Email fingerprints protect against rewriting history only if the parties keep the emails.
- The hackathon version supports one property and simple authentication. A production version would need full accounts, multi-property support, data export, and stronger security and privacy controls.
- Photos and records may contain personal information. Store only what's needed, and let users export and delete their own accounts (the event log of an active dispute should be preserved for both parties; document this policy clearly).

## 14. Running Locally

See "Run it locally" in the [README](../README.md) (tested commands for Windows, macOS, and Linux).

## 15. Deploying

See [AWS.md](AWS.md) and the `Dockerfile`.
