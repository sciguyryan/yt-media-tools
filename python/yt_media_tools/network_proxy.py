"""Validated cross-provider proxy configuration for Discover acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit, urlunsplit


SUPPORTED_PROXY_SCHEMES = frozenset({"http", "https", "socks4", "socks4a", "socks5", "socks5h"})


@dataclass(frozen=True)
class ProxyConfiguration:
    """One proxy endpoint with an explicit destination-name resolution policy."""

    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def remote_dns(self) -> bool:
        """Return whether the proxy, rather than the client, resolves destination names."""
        return self.scheme in {"socks4a", "socks5h"}

    @property
    def socks_version(self) -> int | None:
        """Return the configured SOCKS protocol version, if applicable."""
        if self.scheme in {"socks4", "socks4a"}:
            return 4
        if self.scheme in {"socks5", "socks5h"}:
            return 5
        return None

    @property
    def url(self) -> str:
        """Return a canonical URL accepted by yt-dlp and Requests proxy adapters."""
        hostname = f"[{self.host}]" if ":" in self.host else self.host
        authentication = ""
        if self.username is not None:
            authentication = quote(self.username, safe="")
            if self.password is not None:
                authentication += ":" + quote(self.password, safe="")
            authentication += "@"
        return urlunsplit((self.scheme, f"{authentication}{hostname}:{self.port}", "", "", ""))

    @property
    def redacted_url(self) -> str:
        """Return a diagnostic URL that cannot disclose proxy credentials."""
        hostname = f"[{self.host}]" if ":" in self.host else self.host
        authentication = "<redacted>@" if self.username is not None else ""
        return urlunsplit((self.scheme, f"{authentication}{hostname}:{self.port}", "", "", ""))


def parse_proxy_url(value: str) -> ProxyConfiguration:
    """Parse the common proxy URL surface into a provider-neutral configuration."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("proxy URL must not be empty")
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
        host = parsed.hostname
    except ValueError as exc:
        raise ValueError(f"invalid proxy URL: {exc}") from exc

    scheme = parsed.scheme.casefold()
    if scheme not in SUPPORTED_PROXY_SCHEMES:
        supported = ", ".join(sorted(SUPPORTED_PROXY_SCHEMES))
        raise ValueError(f"unsupported proxy scheme {parsed.scheme!r}; expected one of: {supported}")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("proxy URL must not contain a path, query, or fragment")
    if not host:
        raise ValueError("proxy URL must include a host")
    if port is None:
        raise ValueError("proxy URL must include an explicit port")
    if not 1 <= port <= 65535:
        raise ValueError("proxy port must be between 1 and 65535")
    if parsed.password is not None and parsed.username is None:
        raise ValueError("proxy password requires a username")

    return ProxyConfiguration(
        scheme=scheme,
        host=host,
        port=port,
        username=unquote(parsed.username) if parsed.username is not None else None,
        password=unquote(parsed.password) if parsed.password is not None else None,
    )


def requests_proxy_mapping(proxy: ProxyConfiguration | None) -> dict[str, str] | None:
    """Return the Requests-format mapping accepted by ytmusicapi."""
    if proxy is None:
        return None
    return {"http": proxy.url, "https": proxy.url}
