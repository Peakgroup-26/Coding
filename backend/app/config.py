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

# Longest side of the rendered sheet image in pixels.
RENDER_MAX_PX = int(os.environ.get("RENDER_MAX_PX", "5000"))

# Scale check tolerance (fraction). Brief: block measuring when out by more than 1%.
SCALE_TOLERANCE = 0.01

CORS_ORIGINS = [o for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o]
