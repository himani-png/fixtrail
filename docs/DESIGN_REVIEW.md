# FixTrail Design Review: Strengths, Weaknesses, and Answers for Judges


This section is an honest critique of FixTrail, used to make the design stronger. Each weakness found has a concrete fix that's already part of the build plan. Use this section to prepare the written submission and to answer judge questions.

### 1 Verdict
FixTrail convincingly solves one specific, real problem: **"Who told whom, and when?"** It does not force landlords to make repairs. What it does is give tenants, and fair landlords, trustworthy evidence that neither side usually has today. Its main trust gap, the server operator being able to rewrite history, is closed by putting record fingerprints in every email.

### 2 Strengths, mapped to the judging criteria

| Judging criterion | Why FixTrail scores well |
|---|---|
| **Tech implementation** | A real MCP server (Streamable HTTP, spec 2025-11-25) with 10 tools, an Agent Skill, and an Alexa+ simulator built on the Strands Agents SDK and Amazon Bedrock. A hash-chained, append-only event log enforced by database triggers. Fingerprints anchored outside the system in emails. AWS services: Bedrock, SES for email, S3 for photos. |
| **Design** | Voice for the moment a problem happens ("Alexa, the heater stopped working"), web pages for what voice does badly (photos, landlord replies, reports), and email as a zero-install channel for both sides. Every interface is used where it fits best. |
| **Potential impact** | Proof of notice is central to repair disputes, and tenants often need to show the landlord was told before they can pursue remedies (rules vary by place). The record is useful to tenants, landlords, housing inspectors, mediators, and tenant advocates. |
| **Quality of the idea** | Existing tools each cover one piece: letter senders, landlord-run maintenance portals, or evidence apps that one person keeps privately. FixTrail combines voice capture, automatic notice to the landlord, a **neutral shared record** with honest "verified" vs. "tenant-reported" labels, and fingerprints held by both parties. It treats trust as a design problem instead of assuming every claim is true. |

### 3 What makes this design stand out
1. **Neutrality.** Tenant-only apps feel one-sided and are easy for the other side to dismiss. A record that also protects landlords who respond quickly is more believable to a mediator, and it removes the incentive to make false claims: every claim goes straight to the other party.
2. **Honest labels.** The system marks only what it can prove as **verified** (an email it actually sent, a photo it actually received). Everything else is clearly **tenant-reported**. Being upfront about the limits of proof is what makes the rest of the record credible.
3. **Witnesses outside the system.** Fingerprints in old emails mean FixTrail itself can't quietly rewrite history. Tenant and landlord each hold copies that would expose any change.
4. **It demos clearly.** Speak to Alexa, an email arrives, the landlord clicks a link, the timeline updates, and a tampering attempt is caught by an old email. Every step is visible and easy to follow.

### 4 Weaknesses found, and how they're addressed

| Weakness | Risk | How FixTrail addresses it |
|---|---|---|
| Server operator could rewrite the log and recompute all hashes | A skeptic or a lawyer says "your own verify page would still pass" | Fingerprint and event number in every email, plus a "Check a fingerprint" tool on `/verify` (see the README, "How FixTrail earns trust") |
| Tenants could invent complaints | Unfair to landlords, undermines trust | Every complaint is emailed to the landlord immediately. Calls and in-person claims are labeled tenant-reported. Landlords can respond in the same record |
| Photos could be old or staged | Misleading evidence | Verified time is the server's receipt time, not the photo's own date. Each file's sha256 is recorded. Email photos only accepted from the tenant's registered address with SES authentication checks |
| Landlord never clicks the link | App seems to depend on landlord cooperation | Proof of notice comes from the sent emails themselves. The demo explicitly shows an ignoring landlord |
| Email sent is not email seen | Notice disputed; spam folders | Stated openly in Limitations. Reminders create repeated notice. Future: certified-mail integration |
| Some laws or leases require specific notice methods | Users might rely on FixTrail when they shouldn't | Prominent "not legal advice" disclaimer; framed as record-keeping |
| Scope too big for a first-time builder | Half-finished demo | Must-have / nice-to-have / skip table (see [BUILD_PLAN.md](BUILD_PLAN.md)); core finished first (Phases 1–5b done), real Alexa+ access made optional by the simulator |

### 5 What FixTrail does not solve (say this openly)
- **It proves notice; it doesn't get things fixed.** A landlord who doesn't care can still ignore everything. FixTrail's value is the evidence a tenant brings to a housing inspector, mediator, or court. Pitch it as **"evidence for when things go wrong,"** not "repairs get done faster."
- **It's not a legal service.** It doesn't decide who is right, and whether records are accepted is up to the relevant court or agency.

Judges tend to trust a team more when it states its limits clearly.

### 6 Anticipated judge questions

**"Couldn't you, as the operator, just fake the whole log?"**
We could rewrite our database, but we can't rewrite emails already sitting in the tenant's and landlord's inboxes. Each email contains the record's fingerprint at that moment. Paste any old fingerprint into the verify page and a rewritten history fails. We show this live in the demo.

**"What stops a tenant from lying?"**
Every complaint is sent to the landlord the moment it's made, so a false claim gets answered immediately and the answer goes in the same record. Things we can't verify, like phone calls, are labeled tenant-reported rather than treated as fact.

**"Why would a landlord ever use this?"**
They don't have to; proof of notice works without them. But a landlord who responds quickly gets a dated record proving it, which protects them against false accusations and "I never got a response" claims.

**"Why voice? Isn't a form simpler?"**
Problems happen at inconvenient moments: water on the floor, no heat at night. Saying one sentence is easier than opening an app, which is why people often don't keep records at all. Voice is used for capturing; web pages handle what voice does badly.

**"Does this exist already?"**
Pieces of it do, and we looked (October 2026):
- **Letter tools** like JustFix (NYC) send formal repair letters by certified mail. They create one strong notice, not an ongoing record.
- **Landlord-run portals** like RentRedi and RENTCafé track maintenance requests. RENTCafé even has an Alexa skill for submitting requests. But the landlord's software holds the record, so it isn't neutral evidence.
- **Evidence apps** like Kept, ProofNest, and Sealed timestamp and hash a person's own photos and logs. They're mostly one-sided and private, and they don't notify the other party.
- **Shared records** like Cora (an early-stage app) and Fairhold (UK, mainly check-in/check-out reports) let both sides see one log with hashed files.

What we haven't found is the combination: reporting by voice at the moment a problem happens, **automatic** notice to the landlord on every report, one neutral record both sides can respond in, honest verified vs. tenant-reported labels, and fingerprints sitting in **both parties' inboxes**, so even the operator can't rewrite history. Our edge is that combination, not any single feature.

**"Is this legal advice?"**
No. FixTrail is a record-keeping tool. Notice requirements differ by state, city, and lease, and some require methods like certified mail.

**"What would you build next?"**
Certified-mail integration for places that require it, multi-property support for landlords, exports formatted for housing agencies and mediators, more languages, and optional Ring integration to record when a repair person actually arrived.

### 7 Bottom line for the written submission
> FixTrail is a neutral, tamper-evident repair record for renters and landlords. Tenants report problems by voice through Alexa+, every report is automatically sent to the landlord, and both sides can add to the same timeline. Each email carries a fingerprint of the record, so not even FixTrail can secretly rewrite history. It doesn't force repairs, but it gives tenants and fair landlords the trustworthy evidence they don't have today.
