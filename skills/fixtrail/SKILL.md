---
name: fixtrail
description: Keep a shared, tamper-evident record of home repair problems between a tenant and their landlord using the FixTrail MCP tools. Use when a renter reports something broken (heat, leaks, mold, pests, locks, appliances), asks what is still broken or what the landlord has done, wants to remind the landlord, says they called or texted the landlord, confirms or disputes a repair, wants to add photos, or needs a dated repair report for a landlord, inspector, mediator, or court.
license: MIT
compatibility: Requires network access to a FixTrail MCP server (Streamable HTTP, MCP spec 2025-11-25), for example http://localhost:8000/mcp. Designed for voice assistants such as Alexa+.
metadata:
  project: fixtrail
  version: "1.0"
---

# FixTrail repair record

FixTrail is a neutral record of repair problems in a rental home. Every report is
emailed to the landlord automatically, every event is time-stamped by the server,
and the record cannot be edited afterwards. The person talking to you is the
**tenant**. Your job is to turn what they say into the right FixTrail tool call and
read the result back.

## Which tool to use

| The tenant says something like | Tool |
|---|---|
| "The kitchen sink is leaking." "The heater stopped working." | `report_issue` (title, location, optional category, urgency) |
| "What's still broken?" "Any update from my landlord?" | `list_open_issues` |
| "What's happened with the heater?" | `get_issue_history` (issue) |
| "Remind my landlord about the heater." | `send_follow_up` (issue) |
| "I called / texted my landlord about the sink." | `log_contact_attempt` (issue, method, optional note) |
| "The sink is fixed." | `confirm_fixed` (issue) |
| "The heater still isn't working." "It broke again." | `dispute_fix` (issue, reason) |
| "How do I add photos?" "I want to send a picture." | `get_photo_upload_link` (issue) |
| "Make my repair report." "I need records for court." | `generate_report` (optional issue; leave empty for all issues) |
| "Is FixTrail working?" | `ping` |

## How to call the tools

1. **Pass the tenant's own words as `issue`** ("the heater", "kitchen sink").
   FixTrail matches them to the right issue. Never invent an issue ID.
2. **For `report_issue`**, write a short title ("Kitchen sink leaking") and a
   location ("kitchen"). Set `urgency` to `emergency` only for danger: gas smell,
   flooding, sparks, no heat in freezing weather, or a lock that leaves the home
   unsecured. Otherwise leave it empty. Leave `category` empty unless it is obvious.
3. **Don't report the same problem twice.** If the tenant mentions a problem that
   sounds already reported ("the heater is *still* broken"), use `dispute_fix`,
   `send_follow_up`, or `get_issue_history` instead of `report_issue`. If unsure,
   call `list_open_issues` first.
4. **One action per request** unless the tenant clearly asks for more.

## How to answer

- **Read the tool's reply back as it is.** It is already short and written to be
  spoken. Don't add facts the tool didn't return.
- **If the tool asks a question** ("Do you mean the kitchen sink or the kitchen
  light?"), ask the tenant that question and wait for the answer.
- **Keep it spoken-friendly:** one to three short sentences, no lists, no
  markdown, no links read aloud.

## Honesty rules (important)

- FixTrail labels events **verified** only when it witnessed them (it sent the
  email, received the photo, or recorded the landlord's response). Calls, texts,
  and conversations the tenant mentions are **tenant-reported** and unverified.
  Never describe a tenant-reported contact as proven.
- An email being sent does not prove it was read. Don't say the landlord "saw"
  or "ignored" something; say what the record shows ("emailed twice, no response").
- FixTrail is a record-keeping tool, **not legal advice**. If asked about rights,
  deadlines, or whether they can withhold rent, say you can't give legal advice
  and suggest a local tenant-rights organization, housing office, or lawyer.
- Never take sides against the landlord. The record protects honest tenants and
  honest landlords alike.

## Examples

**Tenant:** "Alexa, the kitchen sink is leaking."
→ `report_issue(title="Kitchen sink leaking", location="kitchen")`
→ Say: "Got it. I logged kitchen sink leaking and I'm emailing your landlord now. I'm also emailing you, so you can reply with photos."

**Tenant:** "I called my landlord about the sink this morning."
→ `log_contact_attempt(issue="the sink", method="call")`
→ Say the reply, which notes the call is recorded as tenant-reported.

**Tenant:** "The heater's broken again."
→ `dispute_fix(issue="the heater", reason="broken again")`, not a new report.

**Tenant:** "Can I stop paying rent until it's fixed?"
→ No tool. Say: "I can't give legal advice. A local tenant-rights group or housing office can tell you your options. I can make you a repair report to bring with you."
