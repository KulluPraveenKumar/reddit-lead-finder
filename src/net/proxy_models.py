"""Proxy value objects.

The credential handling rule, stated once and enforced everywhere below:
**a proxy's username and password never leave this module in printable form.**
``__repr__``, ``__str__``, logging, the database, and the HTTP health page all
see ``ip:port`` only.

That is deliberate belt-and-braces. The proxy file is gitignored and the
credentials are not in the database, but a credential leaks through whichever
path nobody thought about -- usually an exception message or a debug log -- so
the safe form is the *default* form and the usable form has to be asked for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class ProxyState(StrEnum):
    HEALTHY = "healthy"
    #: Failing but inside its cooldown; may recover.
    DEGRADED = "degraded"
    #: Removed from rotation for this run.
    BLACKLISTED = "blacklisted"
    UNTESTED = "untested"


@dataclass(frozen=True)
class ProxyEndpoint:
    """One proxy. Credentials are private by construction."""

    host: str
    port: int
    _username: str = field(repr=False, default="")
    _password: str = field(repr=False, default="")

    @property
    def label(self) -> str:
        """The ONLY safe identifier. Use this in logs, the UI and the database."""
        return f"{self.host}:{self.port}"

    def url(self, scheme: str = "http") -> str:
        """Credentialled URL for `requests`. Never log the return value."""
        if self._username:
            return f"{scheme}://{self._username}:{self._password}@{self.host}:{self.port}"
        return f"{scheme}://{self.host}:{self.port}"

    def as_requests_proxies(self) -> dict[str, str]:
        # Both schemes use an http:// proxy URL: for HTTPS the client issues
        # CONNECT to the proxy over HTTP. A https:// proxy URL here would mean
        # TLS *to the proxy*, which Webshare does not offer.
        return {"http": self.url("http"), "https": self.url("http")}

    def __repr__(self) -> str:
        return f"<ProxyEndpoint {self.label}>"

    def __str__(self) -> str:
        return self.label


class ProxyParseError(ValueError):
    pass


_LINE = re.compile(
    r"^\s*(?P<host>[\w.\-]+):(?P<port>\d{1,5})"
    r"(?::(?P<user>[^:\s]+):(?P<password>[^:\s]+))?\s*$"
)


def parse_proxy_line(line: str) -> ProxyEndpoint | None:
    """Parse ``ip:port`` or ``ip:port:user:pass``. Blank/comment lines -> None."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    match = _LINE.match(stripped)
    if not match:
        # The message deliberately does NOT echo the line: a malformed line is
        # still a line that probably contains a password.
        raise ProxyParseError(
            "Malformed proxy line. Expected 'host:port' or 'host:port:user:pass'."
        )

    port = int(match.group("port"))
    if not 1 <= port <= 65535:
        raise ProxyParseError(f"Port {port} is out of range.")

    return ProxyEndpoint(
        host=match.group("host"),
        port=port,
        _username=match.group("user") or "",
        _password=match.group("password") or "",
    )


def parse_proxy_file(path) -> list[ProxyEndpoint]:
    from pathlib import Path

    file = Path(path)
    if not file.exists():
        raise FileNotFoundError(f"Proxy file not found: {file}")

    endpoints: list[ProxyEndpoint] = []
    for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
        try:
            endpoint = parse_proxy_line(line)
        except ProxyParseError as exc:
            raise ProxyParseError(f"{file.name} line {number}: {exc}") from None
        if endpoint is not None:
            endpoints.append(endpoint)

    if not endpoints:
        raise ProxyParseError(f"{file} contained no usable proxy lines.")
    return endpoints
