"""Hardened, metadata-only PostgreSQL data-source runtime.

The runtime deliberately accepts individual connection attributes instead of a
DSN.  This keeps credentials out of object representations and makes it harder
for a driver error to accidentally be returned to an API caller.  Every public
error raised by this module has a fixed, credential-free message.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import ssl
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

import asyncpg

_POSTGRESQL_ENGINES = frozenset({"postgres", "postgresql"})
_SENSITIVE_COLUMN_PATTERN = (
    r"(^|_)(full_?name|first_?name|last_?name|customer_?name|email|e_?mail|phone|"
    r"mobile|address|birth|dob|ssn|social_?security|passport|tax_?id|national_?id|"
    r"credit_?card|card_?number|password|secret|token|raw_?ticket|ticket_?text|"
    r"comment_?text|message_?text|ip_?address|device_?id|customer_?id|user_?id)($|_)"
)
_SENSITIVE_COLUMN_RE = re.compile(_SENSITIVE_COLUMN_PATTERN, re.IGNORECASE)

_CATALOG_STATS_SQL = """
SELECT
    COUNT(DISTINCT (c.table_schema, c.table_name))::bigint AS table_count,
    COUNT(*)::bigint AS field_count,
    COUNT(*) FILTER (WHERE c.column_name ~* $1)::bigint AS sensitive_field_count
FROM information_schema.columns AS c
JOIN information_schema.tables AS t
  ON t.table_schema = c.table_schema
 AND t.table_name = c.table_name
WHERE t.table_type = 'BASE TABLE'
  AND c.table_schema NOT IN ('information_schema', 'pg_catalog')
"""

_CATALOG_FIELDS_SQL = """
SELECT
    c.table_schema,
    c.table_name,
    c.column_name,
    c.data_type,
    c.is_nullable,
    c.ordinal_position
FROM information_schema.columns AS c
JOIN information_schema.tables AS t
  ON t.table_schema = c.table_schema
 AND t.table_name = c.table_name
WHERE t.table_type = 'BASE TABLE'
  AND c.table_schema NOT IN ('information_schema', 'pg_catalog')
ORDER BY c.table_schema, c.table_name, c.ordinal_position
LIMIT $1
"""


class DataSourceRuntimeError(RuntimeError):
    """Base class for public, safe-to-return runtime failures."""

    code = "data_source_runtime_error"


class UnsupportedEngineError(DataSourceRuntimeError):
    code = "unsupported_engine"


class HostNotAllowedError(DataSourceRuntimeError):
    code = "host_not_allowed"


class TlsRequiredError(DataSourceRuntimeError):
    code = "tls_required"


class TlsVerificationError(DataSourceRuntimeError):
    code = "tls_verification_failed"


class PeerVerificationError(DataSourceRuntimeError):
    code = "peer_verification_failed"


class ReadOnlyEnforcementError(DataSourceRuntimeError):
    code = "read_only_enforcement_failed"


class DataSourceConnectionError(DataSourceRuntimeError):
    code = "connection_failed"


class CatalogScanError(DataSourceRuntimeError):
    code = "catalog_scan_failed"


@dataclass(frozen=True, slots=True)
class PostgreSQLConnectionSpec:
    """Connection values whose representation intentionally omits the password."""

    engine: str
    host: str
    port: int
    database: str
    username: str
    password: str = field(repr=False)
    tls: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("PostgreSQL port must be between 1 and 65535")
        for value, label in (
            (self.host, "host"),
            (self.database, "database"),
            (self.username, "username"),
        ):
            if not value or any(ord(character) < 32 for character in value):
                raise ValueError(f"PostgreSQL {label} is invalid")


@dataclass(frozen=True, slots=True)
class DataSourceRuntimeConfig:
    """Network and resource limits for one data-source operation.

    DNS names are denied by default.  A DNS target must match an allowed
    hostname *and* every address returned by DNS must belong to an allowed
    CIDR.  Literal IP targets only need the CIDR check.  This permits private
    database networks when their exact ranges are intentionally configured,
    while keeping the default fail-closed.
    """

    allowed_hostnames: frozenset[str] = frozenset()
    allowed_cidrs: tuple[str, ...] = ()
    require_tls: bool = True
    verify_tls: bool = True
    tls_ca_file: str | None = None
    connect_timeout_seconds: float = 3.0
    command_timeout_seconds: float = 3.0
    close_timeout_seconds: float = 1.0
    max_catalog_fields: int = 5000
    _networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        normalized_names = frozenset(
            _normalize_allowlist_pattern(name) for name in self.allowed_hostnames
        )
        try:
            networks = tuple(
                ipaddress.ip_network(value, strict=True) for value in self.allowed_cidrs
            )
        except ValueError as error:
            raise ValueError("An allowed CIDR is invalid") from error
        if not 0.1 <= self.connect_timeout_seconds <= 30:
            raise ValueError("Connection timeout must be between 0.1 and 30 seconds")
        if not 0.1 <= self.command_timeout_seconds <= 30:
            raise ValueError("Command timeout must be between 0.1 and 30 seconds")
        if not 0.1 <= self.close_timeout_seconds <= 10:
            raise ValueError("Close timeout must be between 0.1 and 10 seconds")
        if not 1 <= self.max_catalog_fields <= 50_000:
            raise ValueError("Catalog field limit must be between 1 and 50000")
        object.__setattr__(self, "allowed_hostnames", normalized_names)
        object.__setattr__(self, "_networks", networks)


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    success: bool
    engine: str
    read_only: bool
    tls: bool
    latency_ms: int


@dataclass(frozen=True, slots=True)
class CatalogField:
    schema: str
    table: str
    name: str
    data_type: str
    nullable: bool
    ordinal_position: int
    sensitive_name: bool
    sensitivity_reason: str | None


@dataclass(frozen=True, slots=True)
class CatalogTable:
    schema: str
    name: str
    fields: tuple[CatalogField, ...]


@dataclass(frozen=True, slots=True)
class CatalogScanResult:
    table_count: int
    field_count: int
    sensitive_field_count: int
    catalog: tuple[CatalogTable, ...]
    metadata_fields_returned: int
    catalog_truncated: bool
    raw_rows_returned: int = 0


def _normalize_hostname(host: str) -> str:
    candidate = host.strip().rstrip(".")
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    if not candidate or "/" in candidate or "\\" in candidate or "\x00" in candidate:
        raise HostNotAllowedError("The database host is not allowed")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        pass
    try:
        normalized = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise HostNotAllowedError("The database host is not allowed") from None
    if len(normalized) > 253 or any(
        not label or len(label) > 63 for label in normalized.split(".")
    ):
        raise HostNotAllowedError("The database host is not allowed")
    return normalized


def _normalize_allowlist_pattern(pattern: str) -> str:
    candidate = pattern.strip().rstrip(".").lower()
    if candidate.startswith("*."):
        suffix = _normalize_hostname(candidate[2:])
        try:
            ipaddress.ip_address(suffix)
        except ValueError:
            return f"*.{suffix}"
        raise ValueError("Wildcard hostname rules cannot target an IP address") from None
    normalized = _normalize_hostname(candidate)
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        return normalized
    raise ValueError("IP addresses belong in allowed_cidrs, not allowed_hostnames") from None


def _hostname_matches(host: str, patterns: frozenset[str]) -> bool:
    for pattern in patterns:
        if pattern.startswith("*."):
            suffix = pattern[1:]
            if host.endswith(suffix) and host != suffix[1:]:
                return True
        elif host == pattern:
            return True
    return False


async def _resolve_host_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return (str(literal),)

    resolution_failed = False
    records: Sequence[tuple[Any, ...]] = ()
    try:
        loop = asyncio.get_running_loop()
        records = await loop.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except (OSError, UnicodeError):
        resolution_failed = True
    if resolution_failed:
        raise HostNotAllowedError("The database host could not be safely resolved")

    addresses: list[str] = []
    for record in records:
        try:
            address = str(ipaddress.ip_address(record[4][0]))
        except (IndexError, TypeError, ValueError):
            raise HostNotAllowedError("The database host could not be safely resolved") from None
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise HostNotAllowedError("The database host could not be safely resolved")
    return tuple(addresses)


def _address_is_allowed(
    address: str,
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    ip = ipaddress.ip_address(address)
    return any(ip.version == network.version and ip in network for network in networks)


async def _validated_target(
    spec: PostgreSQLConnectionSpec,
    config: DataSourceRuntimeConfig,
) -> tuple[str, tuple[str, ...]]:
    host = _normalize_hostname(spec.host)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not _hostname_matches(host, config.allowed_hostnames):
            raise HostNotAllowedError("The database host is not allowed") from None

    addresses = await _resolve_host_addresses(host, spec.port)
    if not config._networks or any(
        not _address_is_allowed(address, config._networks) for address in addresses
    ):
        raise HostNotAllowedError("The database host resolved outside the allowed network")
    return host, addresses


def _ssl_context(config: DataSourceRuntimeConfig) -> ssl.SSLContext:
    if config.verify_tls:
        context = ssl.create_default_context(cafile=config.tls_ca_file)
        # The driver connects to a pre-validated IP to avoid a second DNS
        # lookup.  Hostname verification is performed against the original
        # hostname immediately after the handshake.
        context.check_hostname = False
        return context
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def _connect(
    spec: PostgreSQLConnectionSpec,
    config: DataSourceRuntimeConfig,
    addresses: tuple[str, ...],
) -> asyncpg.Connection[Any]:
    connection: asyncpg.Connection[Any] | None = None
    failed = False
    try:
        connection = await asyncio.wait_for(
            asyncpg.connect(
                host=addresses,
                port=spec.port,
                user=spec.username,
                password=spec.password,
                database=spec.database,
                timeout=config.connect_timeout_seconds,
                command_timeout=config.command_timeout_seconds,
                statement_cache_size=0,
                ssl=_ssl_context(config) if spec.tls else False,
                server_settings={
                    "application_name": "taskview-catalog-scanner",
                    "default_transaction_read_only": "on",
                    "statement_timeout": str(int(config.command_timeout_seconds * 1000)),
                },
            ),
            timeout=config.connect_timeout_seconds,
        )
    except Exception:  # noqa: BLE001 - driver errors may contain credentials
        # Never propagate a driver message: it may echo connection arguments.
        failed = True
    if failed or connection is None:
        raise DataSourceConnectionError("The PostgreSQL connection could not be established")
    return connection


def _transport_value(connection: asyncpg.Connection[Any], key: str) -> Any:
    transport = getattr(connection, "_transport", None)
    if transport is None or not hasattr(transport, "get_extra_info"):
        return None
    value_failed = False
    value: Any = None
    try:
        value = transport.get_extra_info(key)
    except Exception:  # noqa: BLE001 - transport implementations are driver-owned
        value_failed = True
    return None if value_failed else value


def _verify_peer(
    connection: asyncpg.Connection[Any],
    addresses: tuple[str, ...],
    config: DataSourceRuntimeConfig,
) -> None:
    peer = _transport_value(connection, "peername")
    valid = False
    if isinstance(peer, (tuple, list)) and peer:
        try:
            peer_address = str(ipaddress.ip_address(peer[0]))
            valid = peer_address in addresses and _address_is_allowed(
                peer_address, config._networks
            )
        except (TypeError, ValueError):
            valid = False
    if not valid:
        raise PeerVerificationError("The connected PostgreSQL peer could not be verified")


def _dns_certificate_name_matches(pattern: str, host: str) -> bool:
    candidate = pattern.strip().rstrip(".").lower()
    if candidate.startswith("*."):
        suffix = candidate[2:]
        host_labels = host.split(".")
        return len(host_labels) == len(suffix.split(".")) + 1 and host.endswith(f".{suffix}")
    return candidate == host


def _certificate_matches_host(certificate: Mapping[str, Any], host: str) -> bool:
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None

    subject_alt_names = certificate.get("subjectAltName", ())
    relevant_alt_name_seen = False
    for name_type, value in subject_alt_names:
        if host_ip is not None and name_type == "IP Address":
            relevant_alt_name_seen = True
            try:
                if ipaddress.ip_address(value) == host_ip:
                    return True
            except ValueError:
                continue
        elif host_ip is None and name_type == "DNS":
            relevant_alt_name_seen = True
            if _dns_certificate_name_matches(str(value), host):
                return True
    if relevant_alt_name_seen:
        return False

    # Common Name fallback is retained only for legacy certificates that have
    # no relevant SAN.  SAN always takes precedence when present.
    if host_ip is None:
        for relative_distinguished_name in certificate.get("subject", ()):
            for attribute, value in relative_distinguished_name:
                if attribute == "commonName" and _dns_certificate_name_matches(str(value), host):
                    return True
    return False


def _verify_tls(
    connection: asyncpg.Connection[Any],
    host: str,
    config: DataSourceRuntimeConfig,
) -> None:
    tls_object = _transport_value(connection, "ssl_object")
    if tls_object is None:
        raise TlsVerificationError("The PostgreSQL connection is not protected by TLS")
    if not config.verify_tls:
        return

    verification_failed = False
    try:
        certificate = tls_object.getpeercert()
        if not isinstance(certificate, Mapping) or not _certificate_matches_host(certificate, host):
            verification_failed = True
    except (AttributeError, TypeError, ValueError):
        verification_failed = True
    if verification_failed:
        raise TlsVerificationError("The PostgreSQL TLS certificate could not be verified")


async def _enforce_read_only(connection: asyncpg.Connection[Any]) -> None:
    mode: Any = None
    enforcement_failed = False
    try:
        await connection.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        mode = await connection.fetchval("SHOW transaction_read_only")
    except Exception:  # noqa: BLE001 - replace every driver error with a fixed message
        enforcement_failed = True
    if enforcement_failed or str(mode).strip().lower() not in {"on", "true", "1"}:
        raise ReadOnlyEnforcementError("The PostgreSQL session could not be made read-only")


def _terminate(connection: asyncpg.Connection[Any]) -> bool:
    try:
        connection.terminate()
    except Exception:  # noqa: BLE001 - never log credential-bearing driver errors
        return False
    return True


async def _close(connection: asyncpg.Connection[Any], timeout: float) -> None:
    close_failed = False
    try:
        await asyncio.wait_for(asyncio.shield(connection.close()), timeout=timeout)
    except asyncio.CancelledError:
        _terminate(connection)
        raise
    except Exception:  # noqa: BLE001 - closing must never mask the operation result
        close_failed = True
    if close_failed:
        # There is deliberately no logging here because a custom driver or
        # proxy exception could contain connection credentials.
        _terminate(connection)


@asynccontextmanager
async def secured_postgresql_connection(
    spec: PostgreSQLConnectionSpec,
    config: DataSourceRuntimeConfig,
) -> AsyncIterator[asyncpg.Connection[Any]]:
    """Open a verified, read-only connection and always close it."""

    if spec.engine.strip().lower() not in _POSTGRESQL_ENGINES:
        raise UnsupportedEngineError("Only PostgreSQL data sources are supported")
    if config.require_tls and not spec.tls:
        raise TlsRequiredError("TLS is required for PostgreSQL data sources")

    host, addresses = await _validated_target(spec, config)
    connection = await _connect(spec, config, addresses)
    try:
        _verify_peer(connection, addresses, config)
        if spec.tls:
            _verify_tls(connection, host, config)
        await _enforce_read_only(connection)
        yield connection
    finally:
        await _close(connection, config.close_timeout_seconds)


async def test_connection(
    spec: PostgreSQLConnectionSpec,
    config: DataSourceRuntimeConfig,
) -> ConnectionTestResult:
    """Verify network policy, TLS and read-only enforcement without reading rows."""

    started = monotonic()
    async with secured_postgresql_connection(spec, config):
        pass
    return ConnectionTestResult(
        success=True,
        engine="PostgreSQL",
        read_only=True,
        tls=spec.tls,
        latency_ms=max(0, round((monotonic() - started) * 1000)),
    )


def _mapping_value(row: Mapping[str, Any], key: str) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError):
        raise CatalogScanError("The PostgreSQL catalog returned an invalid response") from None


def _field_from_row(row: Mapping[str, Any]) -> CatalogField:
    schema = str(_mapping_value(row, "table_schema"))
    table = str(_mapping_value(row, "table_name"))
    name = str(_mapping_value(row, "column_name"))
    match = _SENSITIVE_COLUMN_RE.search(name)
    return CatalogField(
        schema=schema,
        table=table,
        name=name,
        data_type=str(_mapping_value(row, "data_type")),
        nullable=str(_mapping_value(row, "is_nullable")).upper() == "YES",
        ordinal_position=int(_mapping_value(row, "ordinal_position")),
        sensitive_name=match is not None,
        sensitivity_reason=(f"name-pattern:{match.group(2).lower()}" if match else None),
    )


def _build_scan_result(
    stats: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    limit: int,
) -> CatalogScanResult:
    try:
        table_count = int(_mapping_value(stats, "table_count") or 0)
        field_count = int(_mapping_value(stats, "field_count") or 0)
        sensitive_field_count = int(_mapping_value(stats, "sensitive_field_count") or 0)
    except (TypeError, ValueError):
        raise CatalogScanError("The PostgreSQL catalog returned an invalid response") from None

    grouped: OrderedDict[tuple[str, str], list[CatalogField]] = OrderedDict()
    for row in rows:
        field_value = _field_from_row(row)
        grouped.setdefault((field_value.schema, field_value.table), []).append(field_value)
    catalog = tuple(
        CatalogTable(schema=schema, name=table, fields=tuple(fields))
        for (schema, table), fields in grouped.items()
    )
    return CatalogScanResult(
        table_count=table_count,
        field_count=field_count,
        sensitive_field_count=sensitive_field_count,
        catalog=catalog,
        metadata_fields_returned=len(rows),
        catalog_truncated=field_count > limit,
        raw_rows_returned=0,
    )


async def scan_catalog(
    spec: PostgreSQLConnectionSpec,
    config: DataSourceRuntimeConfig,
) -> CatalogScanResult:
    """Read only ``information_schema`` metadata and return a redacted catalog."""

    async with secured_postgresql_connection(spec, config) as connection:
        stats: Mapping[str, Any] | None = None
        rows: Sequence[Mapping[str, Any]] = ()
        scan_failed = False
        try:
            async with connection.transaction(readonly=True):
                stats = await connection.fetchrow(
                    _CATALOG_STATS_SQL,
                    _SENSITIVE_COLUMN_PATTERN,
                )
                rows = await connection.fetch(
                    _CATALOG_FIELDS_SQL,
                    config.max_catalog_fields,
                )
        except DataSourceRuntimeError:
            raise
        except Exception:  # noqa: BLE001 - replace every driver error with a fixed message
            # Database errors are never surfaced because they can contain a
            # proxy-generated DSN or credential fragment.
            scan_failed = True
        if scan_failed or stats is None:
            raise CatalogScanError("The PostgreSQL catalog scan could not be completed")
        return _build_scan_result(stats, rows, config.max_catalog_fields)


__all__ = [
    "CatalogField",
    "CatalogScanError",
    "CatalogScanResult",
    "CatalogTable",
    "ConnectionTestResult",
    "DataSourceConnectionError",
    "DataSourceRuntimeConfig",
    "DataSourceRuntimeError",
    "HostNotAllowedError",
    "PeerVerificationError",
    "PostgreSQLConnectionSpec",
    "ReadOnlyEnforcementError",
    "TlsRequiredError",
    "TlsVerificationError",
    "UnsupportedEngineError",
    "scan_catalog",
    "secured_postgresql_connection",
    "test_connection",
]
