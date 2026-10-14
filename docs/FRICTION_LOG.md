# Friction Log

### Entry 1: MCP Python SDK 2.x renamed FastMCP
- Tool/API/SDK: MCP Python SDK (`mcp` 2.3.0)
- Task attempted: Create a "hello world" MCP server with one tool.
- Steps taken: Installed latest `mcp` from PyPI; most tutorials and examples online use `from mcp.server.fastmcp import FastMCP`.
- Expected: Tutorial code works with the latest release.
- Actually happened: In 2.x, `FastMCP` is now `mcp.server.mcpserver.MCPServer`; the old import raises an error (with a helpful message pointing to the migration guide).
- Severity: low
- Workaround: Use `MCPServer`. The API (`@server.tool()`, `streamable_http_app()`, `session_manager`) is otherwise similar.
- Suggestion for Amazon: Alexa+ MCP docs/samples should state which MCP SDK major version they target.

### Entry 2: MCP Inspector v2 requires a newer Node.js
- Tool/API/SDK: MCP Inspector (`@modelcontextprotocol/inspector`)
- Task attempted: Test the server with MCP Inspector.
- Steps taken: `npx @modelcontextprotocol/inspector` prints "v1 is deprecated, upgrade to @latest"; `@latest` (2.11.0) requires Node >= 22.19.0.
- Expected: The recommended upgrade works on a recent Node 22.
- Actually happened: Engine warnings on Node 22.15.0.
- Severity: low
- Workaround: Use v1 (still works and gets security fixes), or upgrade Node.
- Suggestion for Amazon: List required tool versions (Node, Python, Inspector) in hackathon setup docs.

### Entry 3: Alexa AI CLI does not officially support Windows; needs Node 24+
- Tool/API/SDK: Alexa AI CLI (`@alexa-ai/cli`), Alexa+ MCP Toolkit
- Task attempted: Plan the Alexa+ smoke test (Phase 1.5) on a Windows 11 laptop.
- Steps taken: Read "Set Up Your Development Environment" in the Alexa+ add-on docs.
- Expected: Setup that works on common developer machines, including Windows.
- Actually happened: Prerequisites list only macOS Sierra+ or Ubuntu, and Node.js 24+. Hackathon participants on Windows with Node 22 must install WSL and upgrade Node first.
- Severity: high
- Workaround: Use WSL (Ubuntu) on Windows, with Node 24 installed inside it.
- Suggestion for Amazon: Support Windows (or document WSL steps) and say so on the hackathon resources page.

### Entry 4: Alexa+ access and auth requirements are spread across several pages
- Tool/API/SDK: Alexa+ MCP Toolkit docs
- Task attempted: Find out what a minimal MCP add-on needs to connect.
- Steps taken: Read the docs home, QuickStart, Authentication, and Account Linking pages.
- Expected: One checklist for a minimal add-on with no user accounts.
- Actually happened: The docs home says the toolkit is "available to select partners only," but the QuickStart doesn't explain how to get access. The QuickStart lists an OAuth checklist as requirements, while Account Linking says linking is optional. The Authentication page says a `WWW-Authenticate` header in 401 responses is not supported, which differs from common MCP auth examples. One documentation URL (under /en-US/docs/alexa/add-ons/) returned 404.
- Severity: medium
- Workaround: Read all four pages and check details at office hours.
- Suggestion for Amazon: A single "minimal add-on" checklist that separates required from optional steps, plus a clear access path for hackathon participants.

### Entry 5: Unclear whether an Alexa+ simulation satisfies the demo requirement
- Tool/API/SDK: Hackathon Resources page, Alexa+ track
- Task attempted: Decide how to show FixTrail working with Alexa+ in the demo video.
- Steps taken: Read the Resources page and the submission requirements.
- Expected: One clear statement of what counts as "working with Alexa+".
- Actually happened: The Resources page says "You can simulate an Alexa+ experience using your preferred agentic tools via a web app", while the submission requirements ask for a video "showing the MCP server working with Alexa+". Meanwhile the Alexa+ MCP Toolkit docs say it is "available to select partners only", with no access path described for participants.
- Severity: high
- Workaround: Build a web-app simulator that acts as the MCP client (Strands Agents SDK + Bedrock), and ask at office hours to confirm it's acceptable.
- Suggestion for Amazon: State plainly on the Resources and submission pages whether a simulation is acceptable, and if real Alexa+ is preferred, explain how participants get toolkit access.

### Entry 6: AWS credits ran out partway through the hackathon
- Tool/API/SDK: Hackathon AWS credit codes
- Task attempted: Plan AWS usage (Bedrock, SES, S3) for the AWS Builder mini challenge.
- Steps taken: Checked the Resources page for credits.
- Expected: Credits available for the whole hackathon window, or a clear cap announced up front.
- Actually happened: "October 7th Update: Unfortunately, we are out of credit codes and are no longer accepting credit requests." Later participants must pay for AWS usage themselves, which is a barrier for students.
- Severity: medium
- Workaround: Use free-tier options, small Bedrock models, and a billing alert; design so everything runs locally without AWS.
- Suggestion for Amazon: Reserve credits for registered participants, or list which AWS Builder services stay within the free tier.
