"""Runtime settings, read from environment variables."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TAKEOFF_DATA_DIR", BASE_DIR / "data"))

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'takeoff.db'}")
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", DATA_DIR / "files"))

# Tokens are signed with this key. Set it in production or every restart logs everyone out.
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
TOKEN_TTL_HOURS = int(os.environ.get("TOKEN_TTL_HOURS", "12"))

# First admin account, created on startup if no users exist.
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@peak.local")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "200")) * 1024 * 1024

# File storage backend: "local" (STORAGE_DIR) or "s3" (private bucket, STORAGE_DIR as cache)
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local").lower()
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_PREFIX = os.environ.get("S3_PREFIX", "takeoff")
AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-2")  # Sydney, for data residency
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL") or None  # for S3-compatible services
if STORAGE_BACKEND == "s3" and not S3_BUCKET:
    raise RuntimeError("STORAGE_BACKEND=s3 needs S3_BUCKET")

# Longest side of the rendered sheet image in pixels.
RENDER_MAX_PX = int(os.environ.get("RENDER_MAX_PX", "5000"))

# Scale check tolerance (fraction). Brief: block measuring when out by more than 1%.
SCALE_TOLERANCE = 0.01

# Autopilot (the "drop the plans in" read). Jobs run in the background, this many at a time.
AUTOPILOT_WORKERS = int(os.environ.get("AUTOPILOT_WORKERS", "2"))
AUTOPILOT_SYNC = os.environ.get("AUTOPILOT_SYNC", "") == "1"  # run inline (tests)

CORS_ORIGINS = [o for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o]

# The web address people reach the app on, for links in emails and texts (feedback forms, Xero sign-in).
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/")

# Phones stay signed in this long (people on the tools shouldn't log in every morning).
FIELD_TOKEN_TTL_DAYS = int(os.environ.get("FIELD_TOKEN_TTL_DAYS", "60"))

# Outgoing email (CRM follow-ups, feedback requests, POs). Any SMTP service: Microsoft 365, Google Workspace, SendGrid...
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)

# Text messages through ClickSend (Australian SMS gateway). Leave blank to send email only.
CLICKSEND_USERNAME = os.environ.get("CLICKSEND_USERNAME", "")
CLICKSEND_API_KEY = os.environ.get("CLICKSEND_API_KEY", "")
SMS_FROM = os.environ.get("SMS_FROM", "Peak")

# Xero: make an app at developer.xero.com (Web app), redirect URI = PUBLIC_URL + /api/public/xero-callback
XERO_CLIENT_ID = os.environ.get("XERO_CLIENT_ID", "")
XERO_CLIENT_SECRET = os.environ.get("XERO_CLIENT_SECRET", "")
# Apps made after 2 March 2026 must ask for Xero's granular scopes; check the list on Xero's Scopes page for your app.
XERO_SCOPES = os.environ.get("XERO_SCOPES", "openid profile email offline_access accounting.contacts accounting.invoices "
                             "accounting.payments accounting.banktransactions.read accounting.settings.read accounting.reports.read")
XERO_SYNC_MINUTES = int(os.environ.get("XERO_SYNC_MINUTES", "15"))
# Geotab (vehicle tracking): a MyGeotab user with read access (a "View only" security clearance is enough)
GEOTAB_SERVER = os.environ.get("GEOTAB_SERVER", "my.geotab.com")
GEOTAB_DATABASE = os.environ.get("GEOTAB_DATABASE", "")
GEOTAB_USERNAME = os.environ.get("GEOTAB_USERNAME", "")
GEOTAB_PASSWORD = os.environ.get("GEOTAB_PASSWORD", "")

# Background jobs (sending messages, reminders, Xero sync). Off in tests; tests call the tick themselves.
BACKGROUND_TASKS = os.environ.get("BACKGROUND_TASKS", "1") == "1"
