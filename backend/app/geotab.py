"""Geotab (MyGeotab) for the live vehicle map.

Uses the MyGeotab JSON-RPC API: Authenticate once (the session is reused until Geotab says it's expired), then Get Device
(the vehicles), DeviceStatusInfo (where each one is right now) and User (drivers). Positions are cached for 30 seconds
so a room full of people looking at the map doesn't hammer Geotab. Each vehicle is matched to a plant record by the
Geotab id set on the plant, else the rego, VIN or name.
"""
import threading
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import Plant, User

_transport: httpx.BaseTransport | None = None  # tests swap in a fake Geotab
_lock = threading.Lock()
_session: dict | None = None  # {"credentials": {...}, "server": "my123.geotab.com"}
_cache: dict = {"at": 0.0, "data": None}
CACHE_SECONDS = 30


class GeotabError(RuntimeError):
    pass


def ready() -> bool:
    return bool(config.GEOTAB_DATABASE and config.GEOTAB_USERNAME and config.GEOTAB_PASSWORD)


def _post(server: str, method: str, params: dict) -> dict:
    with httpx.Client(timeout=20, transport=_transport) as c:
        r = c.post(f"https://{server}/apiv1", json={"method": method, "params": params})
    if r.status_code >= 300:
        raise GeotabError(f"Geotab said {r.status_code}")
    body = r.json()
    if body.get("error"):
        err = body["error"]
        names = " ".join(e.get("name", "") for e in (err.get("errors") or [])) + " " + str(err.get("message", ""))
        raise GeotabError(names.strip() or "Geotab error")
    return body.get("result")


def _login() -> dict:
    global _session
    res = _post(config.GEOTAB_SERVER, "Authenticate",
                {"database": config.GEOTAB_DATABASE, "userName": config.GEOTAB_USERNAME, "password": config.GEOTAB_PASSWORD})
    path = res.get("path") or "ThisServer"
    _session = {"credentials": res["credentials"], "server": config.GEOTAB_SERVER if path == "ThisServer" else path}
    return _session


def call(method: str, **params) -> object:
    if not ready():
        raise GeotabError("Geotab isn't connected yet (GEOTAB_DATABASE, GEOTAB_USERNAME and GEOTAB_PASSWORD in .env)")
    with _lock:
        s = _session or _login()
    try:
        return _post(s["server"], method, {**params, "credentials": s["credentials"]})
    except GeotabError as e:
        if "InvalidUser" not in str(e) and "Credentials" not in str(e):
            raise
        with _lock:
            s = _login()  # the session ran out: sign in again once
        return _post(s["server"], method, {**params, "credentials": s["credentials"]})


def _match(db: Session, devices: list[dict]) -> dict[str, Plant]:
    plants = list(db.scalars(select(Plant).where(Plant.status != "sold")))
    out: dict[str, Plant] = {}
    for d in devices:
        did = d.get("id", "")
        norm = lambda x: "".join(ch for ch in (x or "").upper() if ch.isalnum())  # noqa: E731
        p = next((p for p in plants if p.geotab_id and p.geotab_id == did), None) or \
            next((p for p in plants if p.rego and norm(p.rego) == norm(d.get("licensePlate"))), None) or \
            next((p for p in plants if p.serial and norm(p.serial) == norm(d.get("vehicleIdentificationNumber"))), None) or \
            next((p for p in plants if norm(p.name) == norm(d.get("name")) or (p.fleet_no and norm(p.fleet_no) == norm(d.get("name")))), None)
        if p:
            out[did] = p
    return out


def live(db: Session, fresh: bool = False) -> dict:
    """Every vehicle with where it is now, who's driving, and its plant record."""
    if not fresh and _cache["data"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
        data = _cache["data"]
    else:
        devices = call("Get", typeName="Device") or []
        status = call("Get", typeName="DeviceStatusInfo") or []
        users = call("Get", typeName="User", search={"isDriver": True}) or []
        data = {"devices": devices, "status": status, "users": users, "at": time.time()}
        _cache.update(at=time.time(), data=data)
    by_dev = {s.get("device", {}).get("id"): s for s in data["status"]}
    drivers = {u.get("id"): f"{u.get('firstName', '')} {u.get('lastName', '')}".strip() or u.get("name", "") for u in data["users"]}
    plants = _match(db, data["devices"])
    staff = {u.id: u for u in db.scalars(select(User))}
    out = []
    for d in data["devices"]:
        s = by_dev.get(d.get("id"), {})
        p = plants.get(d.get("id"))
        drv = s.get("driver")
        driver = drivers.get(drv.get("id")) if isinstance(drv, dict) else ""
        assigned = staff.get(p.assigned_user_id) if p and p.assigned_user_id else None
        out.append({"id": d.get("id"), "name": d.get("name", ""), "rego": d.get("licensePlate", ""), "vin": d.get("vehicleIdentificationNumber", ""),
                    "lat": s.get("latitude"), "lng": s.get("longitude"), "speed": s.get("speed"), "bearing": s.get("bearing"),
                    "driving": bool(s.get("isDriving")), "communicating": bool(s.get("isDeviceCommunicating", True)),
                    "at": s.get("dateTime"), "driver": driver if driver and driver != "UnknownDriverId" else "",
                    "plant_id": p.id if p else None, "plant": p.name if p else "", "kind": p.kind if p else "vehicle",
                    "assigned_to": (assigned.name or assigned.email) if assigned else "", "assigned_phone": assigned.phone if assigned else "",
                    "plant_status": p.status if p else ""})
    return {"vehicles": sorted(out, key=lambda v: v["name"].lower()), "updated": data["at"], "connected": True}
