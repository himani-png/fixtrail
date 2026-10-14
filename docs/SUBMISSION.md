# Devpost submission text

Copy each section into the matching Devpost field. Before submitting, replace anything in [brackets], update the
"Status" line, and add the demo video link.

---

## Project name
FixTrail

## Tagline
A neutral, tamper-evident repair record for renters and landlords, reported by voice through Alexa+.

## Inspiration
Repair disputes between tenants and landlords usually come down to one question: who told whom, and when? Tenants say
"I reported this five times"; landlords say "I was never told." The evidence is scattered across calls, texts, and
memory, and a tenant's private notes are easy to dismiss because anyone can write anything. I wanted a record that is
fair to both sides and hard to fake, and that's as easy to keep as saying one sentence when water is on the floor.

## What it does
- A tenant reports a problem by voice: "Alexa, the kitchen sink is leaking." FixTrail logs it and **emails the
  landlord immediately**, with a private link to respond.
- The landlord can acknowledge, schedule a repair, mark it fixed, or say they couldn't get in, with **no account
  needed**. Every response is emailed to the tenant.
- The tenant can ask "what's still broken?", "remind my landlord", "I called my landlord", "the sink is fixed", or
  "make my repair report", and add photos by uploading them or simply **replying to a FixTrail email**.
- Every event goes into **one shared, append-only, hash-chained record**, labeled **verified** (FixTrail saw it
  happen) or **tenant-/landlord-reported** (FixTrail couldn't see it, like a phone call).
- **Every email carries the record's fingerprint.** Those emails sit in both parties' inboxes, so if anyone (even
  FixTrail's operator) rewrites history and recomputes every hash, old fingerprints stop matching. The demo shows
  this attack being caught.
- A printable report shows the full timeline and response times, such as "No landlord response in 12 days."

## How we built it
- **MCP server** in Python with the official MCP Python SDK: 10 tools over **Streamable HTTP** (spec 2025-11-25),
  mounted in a FastAPI app with web pages for the landlord, timeline, photos, reports, and verification.
- **Agent Skill** (`skills/fixtrail/SKILL.md`) following the open Agent Skills specification, validated with the
  reference tool.
- **Alexa+ simulator:** the Alexa+ MCP Toolkit isn't available to participants, so, as the hackathon resources allow,
  I built a web app that plays Alexa+'s role. The browser handles speech; a **Strands Agents SDK** agent connects to
  FixTrail's MCP endpoint and runs on **Amazon Bedrock** (or an offline model for testing), following the Agent Skill.
- **Tamper evidence:** SQLite with triggers that block edits and deletes, a SHA-256 hash chain over canonical JSON,
  and fingerprint checks against emails.
- **AWS:** Amazon SES for sending email and receiving photo replies, S3 for photos and received mail, SNS to notify
  FixTrail, and Bedrock for the simulator, with a Dockerfile for hosting. [Status: written and tested offline with
  botocore's Stubber; going live once my AWS account is set up.]
- 120 automated tests, built step by step with Claude Code as a first-time developer.

## Challenges we ran into
- **Real Alexa+ access** isn't available to participants, so I designed the simulator to use the exact same MCP
  endpoint Alexa+ would.
- **A trust gap in my own design:** a hash chain alone can be rewritten by whoever runs the server. Putting the
  fingerprint in every email turned both parties into outside witnesses.
- **Alexa+'s 500 ms limit** meant tools reply first and send emails in the background.
- **Dependency conflicts and hidden defaults:** Strands requires an older MCP SDK, and the MCP SDK only accepts
  `localhost` by default, which would have rejected Alexa+ on a real domain. Both are in the friction log.
- **AWS credits ran out** partway through, so everything runs locally without AWS and switches on with one setting.

## Accomplishments that we're proud of
- The design is **neutral**: it protects honest landlords as much as honest tenants.
- **Honest labels:** the system never claims more than it can prove.
- The **tamper demo**: FixTrail's own check says "Record intact", and an old email still catches the rewrite.
- A first-time developer shipping an MCP server, an Agent Skill, a simulator, and 120 tests.

## What we learned
MCP and Streamable HTTP, Agent Skills, the Strands Agents SDK, hash chains, email authentication (SPF, DKIM, DMARC),
and how much trust depends on what you choose *not* to claim.

## What's next for FixTrail
A real Alexa+ add-on with account linking, certified-mail integration where the law requires it, multi-property
support for landlords, exports formatted for housing agencies and mediators, more languages, and Ring integration to
record when a repair person actually arrived.

## Built with
python · fastapi · model-context-protocol · mcp-python-sdk · agent-skills · strands-agents · amazon-bedrock ·
amazon-ses · amazon-s3 · amazon-sns · sqlite · docker · jinja2 · web-speech-api · claude-code

## Links
- Code: https://github.com/himani-png/fixtrail
- Demo video: [YouTube or Vimeo link]
- AWS services: https://github.com/himani-png/fixtrail/blob/main/docs/AWS.md
- Friction log: https://github.com/himani-png/fixtrail/blob/main/docs/FRICTION_LOG.md
- Product feedback: https://github.com/himani-png/fixtrail/blob/main/docs/PRODUCT_FEEDBACK.md
