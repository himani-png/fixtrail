# AWS in FixTrail

This document describes every AWS service FixTrail uses, for the **AWS Builder** mini challenge.
FixTrail runs fully without AWS (local email files, local photos, an offline simulator), and each AWS
service is switched on with one setting in `.env`.

| Service | What FixTrail uses it for | Code | Setting | Status |
|---|---|---|---|---|
| **Amazon Bedrock** | The AI model behind the Alexa+ simulator | [app/simulator.py](../app/simulator.py) | `SIMULATOR_MODE=bedrock` | Written; not yet run live |
| **Strands Agents SDK** | The agent loop: connects to FixTrail's MCP server and calls tools | [app/simulator.py](../app/simulator.py) | always | Running (offline model) |
| **Amazon SES** (sending) | All FixTrail emails, with the record fingerprint in every footer | [app/mailer.py](../app/mailer.py) `SESMailer` | `MAILER=ses` | Written and stub-tested |
| **Amazon SES** (receiving) | Tenant photo replies to `photos+<token>@your-domain` | [app/inbound_email.py](../app/inbound_email.py) | receipt rule | Written and stub-tested |
| **Amazon S3** | Photo storage (encrypted), and received emails | [app/photos.py](../app/photos.py) `S3PhotoStore` | `PHOTO_STORE=s3` | Written and stub-tested |
| **Amazon SNS** | Tells FixTrail when SES receives a photo reply | [app/web.py](../app/web.py) `/inbound/ses` | `INBOUND_*` | Written and tested |
| **Hosting** (EC2 or Lightsail) | Runs the Docker container with SQLite on a persistent disk | [Dockerfile](../Dockerfile) | — | Planned |

"Stub-tested" means each AWS call is tested with botocore's `Stubber`, which checks requests against AWS's real API
definitions without sending anything. AWS credit codes for the hackathon ran out on October 7, so live use waits on a
personal AWS account.

## How the pieces fit

```
Tenant (voice) -> Alexa+ simulator page -> Strands agent + Bedrock model + FixTrail Agent Skill
                                              |  MCP over Streamable HTTP
                                              v
                                      FixTrail server (Docker on EC2/Lightsail)
                                       |-- SQLite event log on a persistent disk
                                       |-- SES: sends emails with record fingerprints
                                       |-- S3: photos (encrypted)
                                       |
Tenant replies with photos -> SES receiving -> S3 (raw email) + SNS notification
                                              -> POST /inbound/ses -> same checks as local testing,
                                                 now with SES's real SPF/DKIM/DMARC/spam/virus verdicts
```

## Setup steps

Do these in **us-east-1**: it supports Bedrock, SES sending, and SES receiving
(SES receiving isn't available in every region).

1. **Billing first.** Create a billing alert (for example at $5) in Billing → Budgets.
2. **Bedrock:** in the Bedrock console, enable access to the model in `BEDROCK_MODEL_ID` (default
   `us.amazon.nova-lite-v1:0`, a small, low-cost model). Then set `SIMULATOR_MODE=bedrock`.
3. **SES sending:** verify a sender (ideally a domain you own, so emails can be DKIM-signed). In the SES sandbox,
   also verify every recipient (the demo tenant and landlord addresses). Set `MAILER=ses` and `SES_FROM_EMAIL`.
4. **S3 photos:** create a private bucket with "Block all public access" on. Set `PHOTO_STORE=s3` and `S3_BUCKET`.
5. **SES receiving** (needs a domain you control):
   - Verify the domain in SES and add an MX record pointing to `inbound-smtp.us-east-1.amazonaws.com`.
   - Create an SNS topic, and a second private S3 bucket for received emails (with a bucket policy allowing SES to
     write to it).
   - Create a receipt rule for `photos@your-domain` (which also catches `photos+token@your-domain`) with an S3 action
     that writes to the inbound bucket and publishes to the SNS topic.
   - Subscribe `https://your-domain/inbound/ses?secret=<INBOUND_SECRET>` to the topic (HTTPS). FixTrail confirms the
     subscription automatically.
   - Set `INBOUND_SECRET` (a long random string), `INBOUND_SNS_TOPIC_ARN`, and `INBOUND_S3_BUCKET`, and set
     `INBOUND_EMAIL_DOMAIN` to your domain.
6. **Hosting:** run the Docker image on a small EC2 or Lightsail instance with a persistent volume for `/data`, behind
   an HTTPS proxy (for example Caddy). Set `BASE_URL=https://your-domain`.

## Least-privilege permissions

Give the server an IAM role (or user) with only what it needs. Replace the names in angle brackets.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "Bedrock", "Effect": "Allow",
     "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse", "bedrock:ConverseStream"],
     "Resource": "*"},
    {"Sid": "SendEmail", "Effect": "Allow", "Action": ["ses:SendEmail", "ses:SendRawEmail"], "Resource": "*"},
    {"Sid": "Photos", "Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject"],
     "Resource": "arn:aws:s3:::<photo-bucket>/*"},
    {"Sid": "InboundEmails", "Effect": "Allow", "Action": ["s3:GetObject"],
     "Resource": "arn:aws:s3:::<inbound-bucket>/*"}
  ]
}
```

## Why these choices

- **SQLite on a persistent disk, not a serverless host.** FixTrail's record is one append-only file with database
  triggers. Hosts without a persistent disk (like App Runner) can lose it on redeploy. A small instance with a volume
  keeps the design simple. DynamoDB would be the next step for multiple properties.
- **Raw SES messages.** FixTrail builds the full email itself, so the photo-reply address and the fingerprint footer
  arrive exactly as written, and the sent text stored in the record matches what was delivered.
- **Only reading our own buckets.** The inbound endpoint rejects notifications that point anywhere except
  `INBOUND_S3_BUCKET`, and requires the secret and the topic ARN. Verifying SNS message signatures would be a further
  hardening step for a production service.

## Costs

At demo scale, SES and S3 cost very little, and the Bedrock model was chosen for low cost. Check current pricing on
the AWS pricing pages before enabling anything, keep the billing alert on, and turn off the instance when you're not
demoing.
