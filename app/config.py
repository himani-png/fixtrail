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


settings = Settings(
    base_url=os.getenv("BASE_URL", "http://localhost:8000").rstrip("/"),
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
)
