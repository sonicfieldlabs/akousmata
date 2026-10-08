"""Owner admission independent of workspace binding and route handlers."""
from dataclasses import dataclass, field
import hmac
import ipaddress
import os
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
        return (address.ipv4_mapped or address).is_loopback if isinstance(address, ipaddress.IPv6Address) else address.is_loopback
    except ValueError:
        return False


def _authority(value: str, scheme: str) -> tuple[str, int]:
    if not value or any(char.isspace() or char in "/\\?#%" for char in value):
        raise ValueError("Invalid owner authority")
    parsed = urlsplit("//" + value)
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Invalid owner authority")
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid owner port")
    return parsed.hostname.lower(), port if port is not None else (443 if scheme == "https" else 80)


@dataclass(frozen=True)
class RequestBoundary:
    allowed_hosts: frozenset[str] = _LOCAL_HOSTS
    access_token: str = field(default="", repr=False)

    @classmethod
    def from_env(cls):
        token = os.getenv("AKOUSMATA_ACCESS_TOKEN", "")
        additional = frozenset(item.strip().lower() for item in os.getenv("AKOUSMATA_ALLOWED_HOSTS", "").split(",") if item.strip())
        if token and len(token) < 32:
            raise ValueError("AKOUSMATA_ACCESS_TOKEN must contain at least 32 characters")
        if additional and not token:
            raise ValueError("Additional owner hosts require AKOUSMATA_ACCESS_TOKEN")
        for host in additional:
            authority = f"[{host}]" if ":" in host else host
            if _authority(authority, "http")[0] != host:
                raise ValueError("AKOUSMATA_ALLOWED_HOSTS must contain hostnames without ports")
        return cls(_LOCAL_HOSTS | additional, token)

    def validate_bind(self, host: str):
        if not _loopback(host) and (not self.access_token or self.allowed_hosts == _LOCAL_HOSTS):
            raise ValueError("Non-loopback binding requires an access token and explicit allowed hosts")

    def reject(self, request: Request) -> JSONResponse | None:
        # No trusted-proxy mode is configured. Uvicorn also disables proxy
        # header interpretation, so neither scheme nor authority can be forged.
        if any(name.lower() == "forwarded" or name.lower().startswith("x-forwarded-") for name in request.headers):
            return JSONResponse(status_code=400, content={"detail": "Forwarded owner headers are not trusted"})
        try:
            hosts = request.headers.getlist("host")
            if len(hosts) != 1:
                raise ValueError("Invalid owner authority")
            authority = _authority(hosts[0], request.url.scheme)
            if authority[0] not in self.allowed_hosts:
                raise ValueError("Untrusted owner host")
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Untrusted owner host"})
        if self.access_token:
            authorization = request.headers.get("authorization", "")
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), self.access_token.encode()):
                return JSONResponse(status_code=401, content={"detail": "Owner authentication required"}, headers={"WWW-Authenticate": "Bearer"})
        elif request.client is None or not _loopback(request.client.host):
            return JSONResponse(status_code=403, content={"detail": "Owner access requires a local client"})
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            origins = request.headers.getlist("origin")
            try:
                if len(origins) > 1:
                    raise ValueError("Multiple origins")
                if origins:
                    origin = urlsplit(origins[0])
                    if origin.scheme != request.url.scheme or origin.path or origin.query or origin.fragment or _authority(origin.netloc, origin.scheme) != authority:
                        raise ValueError("Foreign origin")
                if request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}:
                    raise ValueError("Cross-origin browser mutation")
            except ValueError:
                return JSONResponse(status_code=403, content={"detail": "Owner mutations require the same origin"})
        return None
