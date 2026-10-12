"""Microsoft 365 (Entra ID) single sign-on: OpenID Connect authorisation code flow with PKCE.

Off unless SSO_TENANT_ID, SSO_CLIENT_ID and SSO_CLIENT_SECRET are set. Users sign in with their
work account; by default they must already exist (an admin adds them by email) so roles stay
controlled. SSO_AUTO_CREATE=true creates unknown users as estimators instead.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse

import httpx
import jwt

from . import config


def settings() -> dict:
    tenant = os.environ.get("SSO_TENANT_ID", "")
    return {
        "tenant": tenant,
        "client_id": os.environ.get("SSO_CLIENT_ID", ""),
        "client_secret": os.environ.get("SSO_CLIENT_SECRET", ""),
        "redirect_uri": os.environ.get("SSO_REDIRECT_URI", "http://localhost:8000/api/auth/sso/callback"),
        "allowed_domains": [d.strip().lower() for d in os.environ.get("SSO_ALLOWED_DOMAINS", "").split(",") if d.strip()],
        "auto_create": os.environ.get("SSO_AUTO_CREATE", "").lower() in ("1", "true", "yes"),
        "authority": f"https://login.microsoftonline.com/{tenant}",
    }


def enabled() -> bool:
    s = settings()
    return bool(s["tenant"] and s["client_id"] and s["client_secret"])


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _sign(payload: dict) -> str:
    body = _b64(json.dumps(payload).encode())
    sig = _b64(hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _unsign(value: str) -> dict | None:
    try:
        body, sig = value.split(".")
    except (ValueError, AttributeError):
        return None
    expected = _b64(hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    return data if data.get("exp", 0) > time.time() else None


def start() -> tuple[str, str]:
    """(authorisation URL, signed state cookie value)."""
    s = settings()
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    params = {
        "client_id": s["client_id"], "response_type": "code", "redirect_uri": s["redirect_uri"], "response_mode": "query",
        "scope": "openid profile email", "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    cookie = _sign({"state": state, "nonce": nonce, "verifier": verifier, "exp": int(time.time()) + 600})
    return f"{s['authority']}/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}", cookie


class SSOError(Exception):
    pass


def exchange_code(code: str, verifier: str) -> str:
    """Swap the authorisation code for an ID token."""
    s = settings()
    r = httpx.post(f"{s['authority']}/oauth2/v2.0/token", data={
        "client_id": s["client_id"], "client_secret": s["client_secret"], "grant_type": "authorization_code",
        "code": code, "redirect_uri": s["redirect_uri"], "code_verifier": verifier, "scope": "openid profile email",
    }, timeout=20)
    if r.status_code != 200:
        raise SSOError(f"Microsoft sign-in failed ({r.status_code})")
    token = r.json().get("id_token")
    if not token:
        raise SSOError("Microsoft didn't return an ID token")
    return token


_jwks_client: jwt.PyJWKClient | None = None


def signing_key(id_token: str):
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(f"{settings()['authority']}/discovery/v2.0/keys", cache_keys=True)
    return _jwks_client.get_signing_key_from_jwt(id_token).key


def verify_id_token(id_token: str, nonce: str) -> str:
    """Check the token's signature, audience, issuer, expiry and nonce. Returns the user's email."""
    s = settings()
    try:
        claims = jwt.decode(id_token, signing_key(id_token), algorithms=["RS256"], audience=s["client_id"],
                            issuer=f"{s['authority']}/v2.0", options={"require": ["exp", "iat", "aud", "iss"]})
    except jwt.PyJWTError as e:
        raise SSOError(f"The sign-in token isn't valid: {e}")
    if claims.get("nonce") != nonce:
        raise SSOError("The sign-in response doesn't match this request")
    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if "@" not in email:
        raise SSOError("Your Microsoft account didn't share an email address")
    if s["allowed_domains"] and email.split("@")[1] not in s["allowed_domains"]:
        raise SSOError("That account's email domain isn't allowed to sign in here")
    return email
