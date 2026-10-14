"""Tests for production pieces that can be checked without an AWS account:
host checks, security headers, login limits, SES, S3, and inbound email via SNS.

AWS calls are tested with botocore's Stubber, which checks each request
against AWS's real API definitions without sending anything.
"""

import io
import json
from dataclasses import replace

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber
from fastapi.testclient import TestClient

from mcp.server.transport_security import TransportSecurityMiddleware

from app import config, db, inbound_email, mailer, photos, services, web
from app import main as main_module
from app.main import app, transport_security

def use_settings(monkeypatch, **changes):
    """Swap in settings with some values changed, everywhere they're imported."""
    new = replace(config.settings, **changes)
    for module in (config, mailer, photos, inbound_email, services, web, main_module):
        monkeypatch.setattr(module, "settings", new)
    return new


# ------------------------------------------------------------ host checks

def test_mcp_accepts_localhost_and_the_public_base_url(monkeypatch):
    use_settings(monkeypatch, base_url="https://fixtrail-demo.example.com", allowed_hosts=["abc.trycloudflare.com"])
    security = transport_security()
    assert "fixtrail-demo.example.com" in security.allowed_hosts
    assert "abc.trycloudflare.com" in security.allowed_hosts
    assert "localhost:*" in security.allowed_hosts
    assert security.enable_dns_rebinding_protection  # protection stays on


def test_mcp_rejects_unknown_hosts(monkeypatch):
    # Checked through the SDK's own middleware. (Starting the full app here would
    # use up the MCP session manager, which can only start once per process.)
    use_settings(monkeypatch, base_url="https://fixtrail-demo.example.com", allowed_hosts=[])
    check = TransportSecurityMiddleware(transport_security())
    assert check._validate_host("fixtrail-demo.example.com")
    assert check._validate_host("localhost:8000")
    assert not check._validate_host("evil.example.com")
    assert check._validate_origin("https://fixtrail-demo.example.com")
    assert not check._validate_origin("https://evil.example.com")


# ------------------------------------------------------- headers & login

def test_security_headers():
    response = TestClient(app).get("/health")
    assert response.headers["Referrer-Policy"] == "no-referrer"  # keeps landlord links private
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_repeated_wrong_passcodes_are_slowed_down(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DEFAULT_PATH", str(tmp_path / "x.db"))
    web._failures.clear()
    client = TestClient(app)
    for _ in range(web.MAX_FAILURES):
        assert client.post("/login", data={"passcode": "wrong"}).status_code == 401
    blocked = client.post("/login", data={"passcode": config.settings.tenant_passcode})
    assert blocked.status_code == 429  # even the right passcode waits
    web._failures.clear()


def test_privacy_and_terms_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DEFAULT_PATH", str(tmp_path / "x.db"))
    client = TestClient(app)
    assert "What FixTrail stores" in client.get("/privacy").text
    assert "Not legal advice" in client.get("/terms").text


# ------------------------------------------------------------------- SES

def test_ses_mailer_sends_raw_email_with_reply_to(monkeypatch):
    use_settings(monkeypatch, ses_from_email="fixtrail@example.com")
    client = boto3.client("sesv2", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(client) as stub:
        stub.add_response("send_email", {"MessageId": "ses-123"}, {
            "FromEmailAddress": "fixtrail@example.com",
            "Destination": {"ToAddresses": ["tenant@example.com"]},
            "Content": {"Raw": {"Data": ANY}},
        })
        message_id = mailer.SESMailer(client).send("tenant@example.com", "Hello", "Body\n", reply_to="photos+t@x.com")
        stub.assert_no_pending_responses()
    assert message_id == "ses-123"


def test_ses_mailer_needs_a_verified_sender(monkeypatch):
    use_settings(monkeypatch, ses_from_email="")
    client = boto3.client("sesv2", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    with pytest.raises(RuntimeError, match="SES_FROM_EMAIL"):
        mailer.SESMailer(client).send("t@example.com", "s", "b")


# -------------------------------------------------------------------- S3

def test_s3_photo_store_saves_encrypted_and_loads():
    client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    data = b"\x89PNG\r\n\x1a\nimage"
    with Stubber(client) as stub:
        stub.add_response("put_object", {}, {"Bucket": "photos-bucket", "Key": "issue/abc.png", "Body": data,
                                             "ContentType": "image/png", "ServerSideEncryption": "AES256"})
        stub.add_response("get_object", {"Body": StreamingBody(io.BytesIO(data), len(data))},
                          {"Bucket": "photos-bucket", "Key": "issue/abc.png"})
        store = photos.S3PhotoStore("photos-bucket", client)
        store.save("issue/abc.png", data)
        assert store.load("issue/abc.png") == data
        stub.assert_no_pending_responses()


def test_backends_are_chosen_from_settings(monkeypatch):
    use_settings(monkeypatch, mailer="nope")
    with pytest.raises(ValueError):
        mailer.get_mailer()


# ------------------------------------------------- inbound email via SNS

def ses_notification(bucket="inbound-bucket", verdicts=None):
    verdicts = verdicts or {}
    receipt = {f"{name}Verdict": {"status": verdicts.get(name, "PASS")}
               for name in ("spf", "dkim", "spam", "virus", "dmarc")}
    receipt["action"] = {"type": "S3", "bucketName": bucket, "objectKey": "emails/abc"}
    return {"notificationType": "Received", "receipt": receipt, "mail": {}}


def test_ses_verdicts_are_read_from_the_receipt():
    assert inbound_email.ses_verdicts(ses_notification(verdicts={"spam": "FAIL"})["receipt"]) == {
        "spf": "PASS", "dkim": "PASS", "spam": "FAIL", "virus": "PASS", "dmarc": "PASS"}


def test_inbound_only_reads_from_our_bucket(monkeypatch, conn):
    use_settings(monkeypatch, inbound_s3_bucket="inbound-bucket")
    fetched = []
    result = inbound_email.handle_ses_notification(conn, ses_notification(bucket="someone-elses"),
                                                   fetch=lambda b, k: fetched.append(b) or b"")
    assert not result.accepted and fetched == []


def test_inbound_ses_end_to_end(monkeypatch, conn, tmp_path):
    from tests.test_inbound_email import FakeMailer, reply
    use_settings(monkeypatch, inbound_s3_bucket="inbound-bucket")
    monkeypatch.setattr(services, "mailer", FakeMailer())
    monkeypatch.setattr(services, "RUN_IN_BACKGROUND", False)
    monkeypatch.setattr(photos, "store", photos.LocalPhotoStore(str(tmp_path / "uploads")))
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    token = db.get_token_for_issue(conn, db.list_issues(conn)[0]["id"], "photo_reply")

    result = inbound_email.handle_ses_notification(conn, ses_notification(), fetch=lambda b, k: reply(token))
    assert result.accepted and result.photos_added == 1
    photo = [e for e in db.list_events(conn) if e["type"] == "photo_added"][0]
    assert photo["payload"]["verdicts"]["dkim"] == "PASS"  # real verdicts, not "local test"

    spam = inbound_email.handle_ses_notification(conn, ses_notification(verdicts={"spam": "FAIL"}),
                                                 fetch=lambda b, k: reply(token, message_id="<other@x>"))
    assert not spam.accepted and "spam" in spam.reason


def test_inbound_endpoint_checks_secret_and_topic(monkeypatch, tmp_path):
    use_settings(monkeypatch, inbound_secret="s3cret", inbound_sns_topic_arn="arn:aws:sns:us-east-1:1:fixtrail")
    monkeypatch.setattr(db, "DEFAULT_PATH", str(tmp_path / "x.db"))
    client = TestClient(app)
    envelope = {"Type": "Notification", "TopicArn": "arn:aws:sns:us-east-1:1:fixtrail",
                "Message": json.dumps({"notificationType": "Bounce"})}

    assert client.post("/inbound/ses?secret=wrong", content=json.dumps(envelope)).status_code == 403
    other_topic = {**envelope, "TopicArn": "arn:aws:sns:us-east-1:1:other"}
    assert client.post("/inbound/ses?secret=s3cret", content=json.dumps(other_topic)).status_code == 403
    ok = client.post("/inbound/ses?secret=s3cret", content=json.dumps(envelope))
    assert ok.status_code == 200 and ok.json()["accepted"] is False

    fake_confirm = {"Type": "SubscriptionConfirmation", "TopicArn": envelope["TopicArn"],
                    "SubscribeURL": "https://evil.example.com/confirm"}
    assert client.post("/inbound/ses?secret=s3cret", content=json.dumps(fake_confirm)).status_code == 400


def test_inbound_endpoint_is_off_without_a_secret(monkeypatch):
    use_settings(monkeypatch, inbound_secret="")
    assert TestClient(app).post("/inbound/ses?secret=", content="{}").status_code == 403
