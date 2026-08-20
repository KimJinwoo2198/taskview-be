import asyncio
import re
from dataclasses import asdict
from typing import Any, Self

import pytest

from taskview_be import data_source_runtime as runtime


class FakeTlsObject:
    def __init__(self, hostname: str = "db.example.com") -> None:
        self.hostname = hostname

    def getpeercert(self) -> dict[str, Any]:
        return {
            "subject": ((("commonName", self.hostname),),),
            "subjectAltName": (("DNS", self.hostname),),
        }


class FakeTransport:
    def __init__(
        self,
        *,
        peer: tuple[str, int] = ("203.0.113.10", 5432),
        tls_object: FakeTlsObject | None = None,
    ) -> None:
        self.peer = peer
        self.tls_object = tls_object

    def get_extra_info(self, key: str) -> Any:
        if key == "peername":
            return self.peer
        if key == "ssl_object":
            return self.tls_object
        return None


class FakeTransaction:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> Self:
        self.entered = True
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.exited = True


class FakeConnection:
    def __init__(
        self,
        *,
        read_only: str = "on",
        tls: bool = True,
        stats: dict[str, int] | None = None,
        fields: list[dict[str, Any]] | None = None,
    ) -> None:
        self._transport = FakeTransport(
            tls_object=FakeTlsObject() if tls else None,
        )
        self.read_only = read_only
        self.stats = stats or {
            "table_count": 0,
            "field_count": 0,
            "sensitive_field_count": 0,
        }
        self.fields = fields or []
        self.closed = False
        self.terminated = False
        self.execute_calls: list[str] = []
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []
        self.transaction_value: FakeTransaction | None = None

    async def execute(self, query: str) -> str:
        self.execute_calls.append(query)
        return "SET"

    async def fetchval(self, query: str) -> str:
        assert query == "SHOW transaction_read_only"
        return self.read_only

    async def fetchrow(self, query: str, *args: object) -> dict[str, int]:
        self.fetch_calls.append((query, args))
        return self.stats

    async def fetch(self, query: str, *args: object) -> list[dict[str, Any]]:
        self.fetch_calls.append((query, args))
        return self.fields

    def transaction(self, *, readonly: bool = False) -> FakeTransaction:
        assert readonly is True
        self.transaction_value = FakeTransaction()
        return self.transaction_value

    async def close(self) -> None:
        self.closed = True

    def terminate(self) -> None:
        self.terminated = True


def spec(*, password: str = "super-secret", tls: bool = True) -> runtime.PostgreSQLConnectionSpec:
    return runtime.PostgreSQLConnectionSpec(
        engine="PostgreSQL",
        host="db.example.com",
        port=5432,
        database="analytics",
        username="catalog_reader",
        password=password,
        tls=tls,
    )


def config(**overrides: object) -> runtime.DataSourceRuntimeConfig:
    values: dict[str, object] = {
        "allowed_hostnames": frozenset({"db.example.com"}),
        "allowed_cidrs": ("203.0.113.0/24",),
        "connect_timeout_seconds": 1.0,
        "command_timeout_seconds": 1.0,
        "close_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return runtime.DataSourceRuntimeConfig(**values)  # type: ignore[arg-type]


def install_resolver(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    async def resolve(_host: str, _port: int) -> tuple[str, ...]:
        return tuple(addresses)

    monkeypatch.setattr(runtime, "_resolve_host_addresses", resolve)


def test_connection_uses_resolved_ip_tls_read_only_and_always_closes(monkeypatch):
    connection = FakeConnection()
    captured: dict[str, object] = {}
    install_resolver(monkeypatch, "203.0.113.10")

    async def connect(**kwargs: object) -> FakeConnection:
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(runtime.asyncpg, "connect", connect)

    result = asyncio.run(runtime.test_connection(spec(), config()))

    assert result.success is True
    assert result.read_only is True
    assert result.tls is True
    assert connection.closed is True
    assert connection.terminated is False
    assert connection.execute_calls == ["SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"]
    assert captured["host"] == ("203.0.113.10",)
    assert "dsn" not in captured
    assert captured["statement_cache_size"] == 0
    assert captured["server_settings"] == {
        "application_name": "taskview-catalog-scanner",
        "default_transaction_read_only": "on",
        "statement_timeout": "1000",
    }


def test_read_write_session_is_rejected_and_closed(monkeypatch):
    connection = FakeConnection(read_only="off")
    install_resolver(monkeypatch, "203.0.113.10")

    async def connect(**_kwargs: object) -> FakeConnection:
        return connection

    monkeypatch.setattr(runtime.asyncpg, "connect", connect)

    with pytest.raises(runtime.ReadOnlyEnforcementError, match="read-only"):
        asyncio.run(runtime.test_connection(spec(), config()))

    assert connection.closed is True


@pytest.mark.parametrize("tls", [False, True])
def test_tls_is_rejected_when_disabled_or_not_negotiated(monkeypatch, tls):
    install_resolver(monkeypatch, "203.0.113.10")
    connection = FakeConnection(tls=False)

    async def connect(**_kwargs: object) -> FakeConnection:
        return connection

    monkeypatch.setattr(runtime.asyncpg, "connect", connect)

    if not tls:
        expected_error = runtime.TlsRequiredError
    else:
        expected_error = runtime.TlsVerificationError
    with pytest.raises(expected_error):
        asyncio.run(runtime.test_connection(spec(tls=tls), config()))

    assert connection.closed is tls


def test_dns_rebind_or_disallowed_host_is_rejected_before_connect(monkeypatch):
    install_resolver(monkeypatch, "203.0.113.10", "169.254.169.254")
    connect_called = False

    async def connect(**_kwargs: object) -> FakeConnection:
        nonlocal connect_called
        connect_called = True
        return FakeConnection()

    monkeypatch.setattr(runtime.asyncpg, "connect", connect)

    with pytest.raises(runtime.HostNotAllowedError, match="allowed network"):
        asyncio.run(runtime.test_connection(spec(), config()))

    assert connect_called is False


def test_runtime_defaults_are_fail_closed(monkeypatch):
    install_resolver(monkeypatch, "203.0.113.10")
    connect_called = False

    async def connect(**_kwargs: object) -> FakeConnection:
        nonlocal connect_called
        connect_called = True
        return FakeConnection()

    monkeypatch.setattr(runtime.asyncpg, "connect", connect)

    with pytest.raises(runtime.HostNotAllowedError):
        asyncio.run(runtime.test_connection(spec(), runtime.DataSourceRuntimeConfig()))

    assert connect_called is False


def test_connection_exception_and_representations_never_expose_credentials(monkeypatch):
    password = "DONT-LEAK-postgres://user:password@host/db"
    install_resolver(monkeypatch, "203.0.113.10")

    async def connect(**_kwargs: object) -> FakeConnection:
        raise RuntimeError(f"postgresql://catalog_reader:{password}@db.example.com/analytics")

    monkeypatch.setattr(runtime.asyncpg, "connect", connect)
    connection_spec = spec(password=password)

    with pytest.raises(runtime.DataSourceConnectionError) as raised:
        asyncio.run(runtime.test_connection(connection_spec, config()))

    assert password not in repr(connection_spec)
    assert password not in str(raised.value)
    assert password not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None

    # dataclasses.asdict is intentionally not a supported serialization path;
    # public result objects contain no connection attributes at all.
    assert "password" not in asdict(
        runtime.ConnectionTestResult(
            success=True,
            engine="PostgreSQL",
            read_only=True,
            tls=True,
            latency_ms=1,
        )
    )


def test_catalog_scan_reads_information_schema_only_and_returns_no_raw_rows(monkeypatch):
    fields = [
        {
            "table_schema": "public",
            "table_name": "customers",
            "column_name": "customer_id",
            "data_type": "uuid",
            "is_nullable": "NO",
            "ordinal_position": 1,
        },
        {
            "table_schema": "public",
            "table_name": "customers",
            "column_name": "email",
            "data_type": "text",
            "is_nullable": "YES",
            "ordinal_position": 2,
        },
        {
            "table_schema": "analytics",
            "table_name": "weekly_metrics",
            "column_name": "week",
            "data_type": "date",
            "is_nullable": "NO",
            "ordinal_position": 1,
        },
    ]
    connection = FakeConnection(
        stats={
            "table_count": 2,
            "field_count": 3,
            "sensitive_field_count": 2,
        },
        fields=fields,
    )
    install_resolver(monkeypatch, "203.0.113.10")

    async def connect(**_kwargs: object) -> FakeConnection:
        return connection

    monkeypatch.setattr(runtime.asyncpg, "connect", connect)

    result = asyncio.run(runtime.scan_catalog(spec(), config(max_catalog_fields=10)))

    assert result.table_count == 2
    assert result.field_count == 3
    assert result.sensitive_field_count == 2
    assert result.raw_rows_returned == 0
    assert result.metadata_fields_returned == 3
    assert result.catalog_truncated is False
    assert [(table.schema, table.name) for table in result.catalog] == [
        ("public", "customers"),
        ("analytics", "weekly_metrics"),
    ]
    assert [field.sensitive_name for field in result.catalog[0].fields] == [True, True]
    assert result.catalog[1].fields[0].sensitive_name is False
    assert connection.transaction_value is not None
    assert connection.transaction_value.entered is True
    assert connection.transaction_value.exited is True
    assert connection.closed is True

    assert len(connection.fetch_calls) == 2
    for query, _args in connection.fetch_calls:
        lowered = query.lower()
        assert "information_schema" in lowered
        assert not re.search(r"\bselect\s+\*", lowered)
        assert re.search(r"\blimit\b", lowered) or "count(" in lowered


def test_catalog_failure_is_redacted_and_connection_is_closed(monkeypatch):
    secret = "postgresql://user:secret@db.example.com/private"
    connection = FakeConnection()
    install_resolver(monkeypatch, "203.0.113.10")

    async def connect(**_kwargs: object) -> FakeConnection:
        return connection

    async def broken_fetchrow(*_args: object, **_kwargs: object) -> dict[str, int]:
        raise RuntimeError(secret)

    connection.fetchrow = broken_fetchrow  # type: ignore[method-assign]
    monkeypatch.setattr(runtime.asyncpg, "connect", connect)

    with pytest.raises(runtime.CatalogScanError) as raised:
        asyncio.run(runtime.scan_catalog(spec(), config()))

    assert secret not in str(raised.value)
    assert secret not in repr(raised.value)
    assert raised.value.__context__ is None
    assert connection.closed is True
