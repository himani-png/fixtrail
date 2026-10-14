# Product Feedback

Feedback on every tool FixTrail uses, written for the Amazon Devices, Alexa+, and AWS teams. Each entry says what I
used the tool for, what worked, what needs work, what onboarding was like, and whether I'd use it again.
Detailed, reproducible problems are in the [friction log](FRICTION_LOG.md).

**Status of each integration (October 14, 2026)**

| Tool | Status in FixTrail |
|---|---|
| MCP Python SDK, MCP Inspector | Used throughout, running live |
| Strands Agents SDK | Running live in the Alexa+ simulator (with an offline model) |
| Agent Skills spec and validator | Used; the FixTrail skill validates |
| Alexa+ add-on docs | Read in detail; toolkit not available to participants (see below) |
| Amazon Bedrock | Integration written; waiting on an AWS account (credits ran out) |
| Amazon SES, Amazon S3, Amazon SNS | Integrations written and tested offline with botocore's Stubber; not yet live |

---

## MCP Python SDK (`mcp`)

- **Used for:** FixTrail's MCP server: 10 tools over Streamable HTTP (spec 2025-11-25), mounted inside a FastAPI app,
  plus the in-process `Client` for tests.
- **What worked:** Declaring tools is pleasant: a typed Python function plus `Annotated[..., Field(description=...)]`
  produces a clean input schema. The in-process `Client(server)` makes end-to-end tool tests fast and reliable.
  The 2.x error for the old `FastMCP` import points straight to the migration guide, which is excellent.
- **What needs work:**
  - DNS-rebinding protection only allows `localhost` by default, and the rejection (`421 Invalid Host header`) only
    appears in logs. A server that works locally silently fails once it's behind a real domain. A startup warning
    when `host` is localhost but a public URL is likely would save people.
  - The session manager can only be started once per process, which makes testing with real HTTP awkward.
  - Mounting inside FastAPI needs the session manager started in FastAPI's lifespan; this deserves a short official
    recipe.
- **Onboarding:** Good, once I read the installed source. Most online examples are for 1.x.
- **Would I use it again?** Yes.

## MCP Inspector (`@modelcontextprotocol/inspector`)

- **Used for:** Manually listing and calling FixTrail's tools during development.
- **What worked:** The CLI mode (`--cli --method tools/call`) is great for scripted checks. Starting the UI with
  `--transport http --server-url ...` pre-fills the connection.
- **What needs work:** The UI opens on STDIO with a sample `mcp-server-everything` command. A first-timer (me) tried
  for a while to connect to an HTTP server that way, and the error (`spawn ... ENOENT`) doesn't hint at the
  Transport Type setting. The browser also remembers the last transport, which brought STDIO back after I'd fixed it.
  v1 shows a deprecation banner, but v2 needs Node 22.19+.
- **Onboarding:** Confusing at first, smooth once configured.
- **Would I use it again?** Yes, mainly the CLI mode.

## Strands Agents SDK (`strands-agents`)

- **Used for:** The Alexa+ simulator's agent: it connects to FixTrail's `/mcp` with `MCPClient(url=...)`, uses the
  FixTrail Agent Skill as its system prompt, and runs either an Amazon Bedrock model or my offline stand-in model.
- **What worked:** `MCPClient` as a tool provider is the simplest MCP client setup I've seen: pass a URL, hand it to
  `Agent(tools=[...])`, done. Implementing the `Model` interface for an offline stand-in was straightforward because
  it uses the Bedrock Converse streaming format, so my tests exercise the real agent loop and real MCP calls.
- **What needs work:**
  - `strands-agents` 1.61.0 requires `mcp<2.2`, so installing it silently downgraded the MCP SDK from 2.3.0. I had
    to verify my server on the older SDK before pinning.
  - The agent appends to the `messages` list you pass in. That's reasonable, but it surprised me when I computed
    "new messages" from the list's length.
  - Online examples disagree on import paths; the official examples were the reliable source.
- **Onboarding:** Fast, especially for MCP.
- **Would I use it again?** Yes.

## Agent Skills (specification and `skills-ref`)

- **Used for:** `skills/fixtrail/SKILL.md`, which teaches any agent when and how to use FixTrail's tools, how to
  answer by voice, and the honesty rules (unverified claims, no legal advice).
- **What worked:** The format is simple and well specified. Progressive disclosure (name and description first, body
  on demand) is a good fit for voice assistants with many skills.
- **What needs work:** The spec says to run `skills-ref validate`, but `pip install skills-ref` installs a command
  named `agentskills`.
- **Would I use it again?** Yes.

## Alexa+ add-on documentation (MCP Toolkit)

- **Used for:** Planning a real Alexa+ connection: CLI, add-on manifest, authentication, account linking, and the
  500 ms response-time requirement (which shaped FixTrail's design: emails are sent in the background).
- **What worked:** The authentication and account-linking pages are precise. Being explicit that `WWW-Authenticate`
  isn't supported, and that account linking is optional, saves guesswork. The 500 ms requirement is clearly stated.
- **What needs work:**
  - The toolkit is "available to select partners only", with no access path described for hackathon participants.
    The hackathon page allows a simulation instead, but the submission requirements still say "working with Alexa+".
    One clear statement would help.
  - The CLI officially supports only macOS and Ubuntu, and needs Node 24+. Many students are on Windows.
  - The minimal path for an add-on with no user accounts is spread across four pages.
- **Onboarding:** Blocked on access, so I built a simulator that plays Alexa+'s role over the same MCP endpoint.
- **Would I use it again?** Yes, once access is available.

## Amazon Bedrock (via Strands)

- **Used for:** The simulator's AI model (`SIMULATOR_MODE=bedrock`, default model `us.amazon.nova-lite-v1:0`).
- **Status:** Written and wired up, not yet run: AWS credit codes ran out on October 7, and I'm setting up my own
  account. I'll update this section after the first live run.
- **Early feedback:** Strands' `BedrockModel` makes switching between a local stand-in and Bedrock a one-line change,
  which made it easy to build and test everything first.

## Amazon SES, Amazon S3, and Amazon SNS (via boto3)

- **Used for:** SES sends FixTrail's emails (raw MIME, so the Reply-To photo address and the plain-text fingerprint
  footer arrive untouched) and receives photo replies. S3 stores photos (encrypted) and received emails. SNS tells
  FixTrail when a reply arrives.
- **What worked:** botocore's `Stubber` let me test every SES and S3 call against AWS's real API definitions without
  an account, which is excellent for students. The SES docs on sandbox limits (verified recipients, 200 emails a day,
  1 per second) and on which regions support receiving are clear.
- **What needs work:**
  - Receiving email requires a domain you control (MX records). There's no lightweight option for prototypes, and
    free platform subdomains (like GitHub Pages or Vercel) can't be used.
  - Verifying SNS message signatures in Python needs extra libraries; an official small helper in boto3 would help.
- **Status:** Not yet live (no AWS account yet). See [AWS.md](AWS.md).
- **Would I use it again?** Yes.

## Hackathon resources page

- **What worked:** Clear per-track starting points and honest updates (like the credits notice).
- **What needs work:** Credits ran out partway through the hackathon, and the simulation-versus-real-Alexa+ question
  isn't answered in one place (friction log entries 5 and 6).

---

## Feature requests

**Critical**
- A documented way for hackathon participants to get Alexa+ MCP Toolkit access, or an official statement that a
  simulator satisfies the demo requirement.
- Windows support (or official WSL steps) for the Alexa AI CLI.

**Important**
- MCP Python SDK: warn at startup when DNS-rebinding protection only allows localhost but the server is reachable
  under another host name.
- Strands: track current MCP SDK releases in its dependency range.
- An official, minimal "MCP server inside FastAPI" recipe in the MCP Python SDK docs.
- Reserved AWS credits for registered participants, or a list of which AWS Builder services stay in the free tier.

**Nice to have**
- MCP Inspector: open on "Streamable HTTP" when given a URL, and explain the transport choice in the error.
- An Alexa+ web simulator that can be pointed at any public MCP server without an add-on, for prototyping.
- A small boto3 helper for verifying SNS message signatures.
