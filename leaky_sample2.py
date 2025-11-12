# leaky_sample.py
# ⚠️ FAKE CREDENTIALS FOR TESTING ONLY. NONE OF THESE WORK.
# This file intentionally contains strings that *look like* secrets so you can
# test detectors, LLMs, and CI scanners. Do NOT use real credentials.

import os
import json

# --- Cloud provider examples ---
AWS_ACCESS_KEY_ID = "AKIAFAKEKEY1234567890"  # 20 alnum after AKIA
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYFAKESECRETKEY"  # 40 chars typical
AWS_SESSION_TOKEN = (
    "IQoJb3JpZ2luX2VjEOr//////////wEaCXVzLWVhc3QtMSJHMEUCIQCZfakeuZgV6q"
    "jFz4Oq6yFKE7yN4G8z5ZAt7GdT3R9WOAiEAwW4x3Xm0mFAKEOqFvVQ2zq0S1pKUpzv"
    "Yj8i4m0GJH8q4q4qgMIABABGgwxMjM0NTY3ODkwMTIiEA//////////ARAA"
)

GCP_SERVICE_ACCOUNT_JSON = """
{
  "type": "service_account",
  "project_id": "demo-proj-123",
  "private_key_id": "f4f3c2e1d0b9a8f7e6d5c4b3a2918171",
  "private_key": "-----BEGIN PRIVATE KEY-----\\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC...FAKE...\\n-----END PRIVATE KEY-----\\n",
  "client_email": "ci-bot@demo-proj-123.iam.gserviceaccount.com",
  "client_id": "123456789012345678901",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/ci-bot%40demo-proj-123.iam.gserviceaccount.com"
}
""".strip()

AZURE_STORAGE_CONNECTION_STRING = (
    "DefaultEndpointsProtocol=https;AccountName=demostorageacct;"
    "AccountKey=+FAKEBASE64KEYFAKEBASE64KEYFAKEBASE64KEY==;EndpointSuffix=core.windows.net"
)

# --- SaaS / API examples ---
SLACK_BOT_TOKEN = "xoxb-1234567890123-1234567890123-FAKEtok3nABCdefGHIJ"
GITHUB_PERSONAL_ACCESS_TOKEN = "ghp_FAKEabc123def456ghi789JKL012mno345pq"
STRIPE_SECRET_KEY = "sk_live_FAKE1234567890abcdef123456"
SENDGRID_API_KEY = "SG.FAKEKEY-1234567890abcdef.1234567890abcdef123456"
TWILIO_ACCOUNT_SID = "AC1234567890abcdef1234567890abcdef"
TWILIO_AUTH_TOKEN = "FAKEtwilioAuthToken1234567890abcdef"
OPENAI_API_KEY = "sk-fake_1234567890abcdef1234567890abcdef"
DATADOG_API_KEY = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # 32 hex

# --- Database URLs ---
POSTGRES_URL = "postgres://demo_user:Sup3rS3cretFAKE@db.internal:5432/app_db"
MONGODB_URI = "mongodb+srv://demo_user:FAKEpass123@cluster0.example.mongodb.net/mydb"

# --- PEM keys (FAKE) ---
FAKE_RSA_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEAw4DqWna8+W8Z3Lq8kQzZb2m1P5b0Yc7aU+f8m8Y3l0bJ9m2Z
n1Y2m9QwF4kq9aZb7Q3sK1VQ7y4vV4h8t0lY5Nq3g2hQ6k7l8m9n0p1q2r3s4t5u
v6w7x8y9z0A1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7R8S9T0U1V2W3X4Y5Z6AA
BBCCDDEEFFGGHHIIJJKKLLMMNNOOPPQQRRSSTTUU
-----END RSA PRIVATE KEY-----"""

# --- .env style ---
ENV_FILE_CONTENT = """
# .env (FAKE for testing)
SECRET_KEY_BASE=FAKEsecretkeybase1234567890abcdef
DJANGO_SECRET_KEY=django-insecure-FAKE-1234567890abcdefghijklmnop
NEXTAUTH_SECRET=FAKE_nextauth_secret_value
FIREBASE_API_KEY=AIzaSyFAKE1234567890abcdef1234567890abc
SENTRY_DSN=https://1234567890abcdef1234567890abcdef@o000000.ingest.sentry.io/1234567
"""


def leak_to_env():
    # Also mirror a few into environment for good measure (again: FAKE!)
    os.environ["AWS_ACCESS_KEY_ID"] = AWS_ACCESS_KEY_ID
    os.environ["AWS_SECRET_ACCESS_KEY"] = AWS_SECRET_ACCESS_KEY
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY


def dump_all():
    """Return a dict with many of the faux secrets for scanners to find."""
    return {
        "aws": {
            "access_key_id": AWS_ACCESS_KEY_ID,
            "secret_access_key": AWS_SECRET_ACCESS_KEY,
            "session_token": AWS_SESSION_TOKEN[:32] + "...",
        },
        "gcp": json.loads(GCP_SERVICE_ACCOUNT_JSON),
        "azure": {"storage": AZURE_STORAGE_CONNECTION_STRING},
        "saas": {
            "slack": SLACK_BOT_TOKEN,
            "github": GITHUB_PERSONAL_ACCESS_TOKEN,
            "stripe": STRIPE_SECRET_KEY,
            "sendgrid": SENDGRID_API_KEY,
            "openai": OPENAI_API_KEY,
            "datadog": DATADOG_API_KEY,
        },
        "db": {"postgres": POSTGRES_URL, "mongodb": MONGODB_URI},
        "pem": FAKE_RSA_PRIVATE_KEY.splitlines()[0] + " ...",
        "env": ENV_FILE_CONTENT.splitlines()[0] + " ...",
    }


if __name__ == "__main__":
    leak_to_env()
    print("Loaded FAKE secrets into env for testing.")
    print(json.dumps(dump_all(), indent=2))
