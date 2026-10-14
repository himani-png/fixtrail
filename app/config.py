"""Loads settings from the .env file (or real environment variables).

Every other module imports `settings` from here instead of reading
os.environ directly, so all configuration lives in one place.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    base_url: str
    property_address: str
    tenant_name: str
    tenant_email: str
    landlord_name: str
    landlord_email: str
    tenant_passcode: str
    mailer: str
    photo_store: str
    database_path: str
    inbound_email_domain: str
    max_photo_mb: int
    simulator_mode: str
    simulator_mcp_url: str
    bedrock_model_id: str
    aws_region: str
    allowed_hosts: list[str]
    ses_from_email: str
    s3_bucket: str
    inbound_secret: str
    inbound_sns_topic_arn: str
    inbound_s3_bucket: str


def _list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


_base_url = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

settings = Settings(
    base_url=_base_url,
    property_address=os.getenv("PROPERTY_ADDRESS", "12 Example St, Apt 3"),
    tenant_name=os.getenv("TENANT_NAME", "Alex Tenant"),
    tenant_email=os.getenv("TENANT_EMAIL", "tenant@example.com"),
    landlord_name=os.getenv("LANDLORD_NAME", "Sam Landlord"),
    landlord_email=os.getenv("LANDLORD_EMAIL", "landlord@example.com"),
    tenant_passcode=os.getenv("TENANT_PASSCODE", "change-me"),
    mailer=os.getenv("MAILER", "console"),
    photo_store=os.getenv("PHOTO_STORE", "local"),
    database_path=os.getenv("DATABASE_PATH", "fixtrail.db"),
    inbound_email_domain=os.getenv("INBOUND_EMAIL_DOMAIN", "fixtrail.example.com"),
    max_photo_mb=int(os.getenv("MAX_PHOTO_MB", "10")),
    simulator_mode=os.getenv("SIMULATOR_MODE", "offline"),
    simulator_mcp_url=os.getenv("SIMULATOR_MCP_URL", f"{_base_url}/mcp"),
    bedrock_model_id=os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-lite-v1:0"),
    aws_region=os.getenv("AWS_REGION", "us-east-1"),
    allowed_hosts=_list(os.getenv("ALLOWED_HOSTS", "")),
    ses_from_email=os.getenv("SES_FROM_EMAIL", ""),
    s3_bucket=os.getenv("S3_BUCKET", ""),
    inbound_secret=os.getenv("INBOUND_SECRET", ""),
    inbound_sns_topic_arn=os.getenv("INBOUND_SNS_TOPIC_ARN", ""),
    inbound_s3_bucket=os.getenv("INBOUND_S3_BUCKET", ""),
)
