from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from .config import Settings
from .schemas import ViewPlan

FCC_URL = "https://opendata.fcc.gov/resource/3xyp-aqkj.json"
NYC_311_URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
NHTSA_URL = "https://api.nhtsa.gov/complaints/complaintsByVehicle"

NHTSA_VEHICLES = (
    ("TESLA", "MODEL 3", 2024),
    ("FORD", "F-150", 2024),
    ("TOYOTA", "RAV4", 2024),
    ("HONDA", "CR-V", 2024),
    ("HYUNDAI", "IONIQ 5", 2024),
    ("KIA", "EV6", 2024),
    ("CHEVROLET", "SILVERADO 1500", 2024),
    ("NISSAN", "ROGUE", 2024),
)

SENSITIVE_SOURCE_FIELDS = frozenset(
    {
        "caller_id_number",
        "advertiser_business_phone_number",
        "incident_address",
        "street_name",
        "cross_street_1",
        "cross_street_2",
        "intersection_street_1",
        "intersection_street_2",
        "address_type",
        "latitude",
        "longitude",
        "location",
        "park_borough",
        "vin",
        "summary",
        "products",
    }
)


@dataclass(frozen=True)
class PublicRecord:
    source_key: str
    external_id_hash: str
    observed_at: datetime
    payload: dict[str, str | int | float | bool | None]


@dataclass(frozen=True)
class PublicSnapshot:
    source_key: str
    provider: str
    official_url: str
    license_url: str
    fetched_at: datetime
    records: list[PublicRecord]

    @property
    def content_sha256(self) -> str:
        safe_rows = [record.payload for record in self.records]
        encoded = json.dumps(safe_rows, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def _hash_id(source_key: str, value: object) -> str:
    return hashlib.sha256(f"{source_key}:{value}".encode()).hexdigest()


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for pattern in ("%m/%d/%Y", "%Y%m%d"):
            try:
                parsed = datetime.strptime(value, pattern).replace(tzinfo=UTC)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _week(value: datetime) -> str:
    year, week, _ = value.isocalendar()
    return f"{year}-W{week:02d}"


def _clean(value: object, *, fallback: str = "Unknown", maximum: int = 100) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = " ".join(value.split())[:maximum]
    return cleaned or fallback


def normalize_fcc(row: dict[str, Any]) -> PublicRecord | None:
    observed = _parse_datetime(row.get("ticket_created"))
    external_id = row.get("ticket_id") or row.get("id")
    if observed is None or external_id is None:
        return None
    payload: dict[str, str | int | float | bool | None] = {
        "week": _week(observed),
        "region": _clean(row.get("state"), fallback="US"),
        "issue_type": _clean(row.get("issue_type")),
        "issue": _clean(row.get("issue")),
        "channel": _clean(row.get("method")),
        "case_count": 1,
    }
    return PublicRecord("product", _hash_id("product", external_id), observed, payload)


def normalize_nyc_311(row: dict[str, Any]) -> PublicRecord | None:
    observed = _parse_datetime(row.get("created_date"))
    external_id = row.get("unique_key")
    if observed is None or external_id is None:
        return None
    closed = _parse_datetime(row.get("closed_date"))
    resolution_hours = (
        max(0.0, round((closed - observed).total_seconds() / 3600, 2)) if closed else None
    )
    payload: dict[str, str | int | float | bool | None] = {
        "week": _week(observed),
        "region": _clean(row.get("borough"), fallback="Unspecified"),
        "agency": _clean(row.get("agency")),
        "complaint_type": _clean(row.get("complaint_type")),
        "descriptor": _clean(row.get("descriptor")),
        "channel": _clean(row.get("open_data_channel_type")),
        "status": _clean(row.get("status")),
        "resolution_hours": resolution_hours,
        "case_count": 1,
    }
    return PublicRecord("operations", _hash_id("operations", external_id), observed, payload)


def normalize_nhtsa(row: dict[str, Any]) -> PublicRecord | None:
    observed = _parse_datetime(row.get("dateComplaintFiled") or row.get("dateOfIncident"))
    external_id = row.get("odiNumber")
    if observed is None or external_id is None:
        return None
    products = row.get("products")
    vehicle = products[0] if isinstance(products, list) and products else {}
    if not isinstance(vehicle, dict):
        vehicle = {}
    components = _clean(row.get("components"), maximum=160).split(",")[0]
    payload: dict[str, str | int | float | bool | None] = {
        "week": _week(observed),
        "manufacturer": _clean(row.get("manufacturer")),
        "make": _clean(vehicle.get("productMake")),
        "model": _clean(vehicle.get("productModel")),
        "model_year": int(vehicle.get("productYear") or 0),
        "component": components or "Unknown",
        "crash_count": int(bool(row.get("crash"))),
        "fire_count": int(bool(row.get("fire"))),
        "injury_count": int(row.get("numberOfInjuries") or 0),
        "death_count": int(row.get("numberOfDeaths") or 0),
        "case_count": 1,
    }
    return PublicRecord("voc", _hash_id("voc", external_id), observed, payload)


def assert_safe_records(records: Iterable[PublicRecord]) -> None:
    for record in records:
        overlap = SENSITIVE_SOURCE_FIELDS.intersection(record.payload)
        if overlap:
            raise ValueError(f"sensitive source fields survived normalization: {sorted(overlap)}")


async def fetch_public_snapshots(settings: Settings) -> list[PublicSnapshot]:
    headers = {"User-Agent": settings.taskview_public_demo_user_agent, "Accept": "application/json"}
    timeout = httpx.Timeout(settings.taskview_public_demo_timeout_seconds)
    fetched_at = datetime.now(UTC)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        fcc_response = await client.get(
            FCC_URL,
            params={"$limit": 3000, "$order": "ticket_created DESC"},
        )
        fcc_response.raise_for_status()
        nyc_response = await client.get(
            NYC_311_URL,
            params={"$limit": 6000, "$order": "created_date DESC"},
        )
        nyc_response.raise_for_status()
        nhtsa_rows: list[dict[str, Any]] = []
        for make, model, model_year in NHTSA_VEHICLES:
            response = await client.get(
                NHTSA_URL,
                params={"make": make, "model": model, "modelYear": model_year},
            )
            if response.status_code in {400, 404}:
                continue
            response.raise_for_status()
            nhtsa_rows.extend(response.json().get("results", []))

    source_rows = (
        (
            "product",
            "Federal Communications Commission",
            "https://catalog.data.gov/dataset/cgb-consumer-complaints-data",
            "https://www.usa.gov/government-copyright",
            (normalize_fcc(row) for row in fcc_response.json()),
        ),
        (
            "operations",
            "NYC Open Data",
            "https://data.cityofnewyork.us/resource/erm2-nwe9",
            "https://opendata.cityofnewyork.us/overview/#termsofuse",
            (normalize_nyc_311(row) for row in nyc_response.json()),
        ),
        (
            "voc",
            "National Highway Traffic Safety Administration",
            "https://www.nhtsa.gov/nhtsa-datasets-and-apis",
            "https://www.usa.gov/government-copyright",
            (normalize_nhtsa(row) for row in nhtsa_rows),
        ),
    )
    snapshots: list[PublicSnapshot] = []
    for key, provider, official_url, license_url, normalized in source_rows:
        records = [record for record in normalized if record is not None]
        if not records:
            raise ValueError(f"{key} public source returned no usable records")
        assert_safe_records(records)
        snapshots.append(
            PublicSnapshot(key, provider, official_url, license_url, fetched_at, records)
        )
    return snapshots


def aggregate_records(
    plan: ViewPlan,
    records_by_source: dict[str, list[dict[str, Any]]],
    *,
    minimum_group_size: int = 20,
    limit: int | None = 24,
) -> list[dict[str, str | int]]:
    dimensions = [
        column
        for column in plan.preview_columns
        if column
        not in {
            "case_count",
            "avg_resolution_hours",
            "crash_count",
            "fire_count",
            "injury_count",
            "death_count",
        }
    ]
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for source_key in plan.selected_sources:
        for payload in records_by_source.get(source_key, []):
            if all(column in payload for column in dimensions):
                groups[tuple(str(payload[column]) for column in dimensions)].append(payload)

    output: list[dict[str, str | int]] = []
    for key, group in groups.items():
        if len(group) < minimum_group_size:
            continue
        row: dict[str, str | int] = dict(zip(dimensions, key, strict=True))
        row["case_count"] = len(group)
        if "avg_resolution_hours" in plan.preview_columns:
            values = [
                float(item["resolution_hours"])
                for item in group
                if item.get("resolution_hours") is not None
            ]
            row["avg_resolution_hours"] = round(sum(values) / len(values)) if values else 0
        for metric in ("crash_count", "fire_count", "injury_count", "death_count"):
            if metric in plan.preview_columns:
                row[metric] = sum(int(item.get(metric) or 0) for item in group)
        output.append(row)
    output.sort(key=lambda row: int(row.get("case_count", 0)), reverse=True)
    return output if limit is None else output[:limit]


def project_public_records(
    plan: ViewPlan,
    records_by_source: dict[str, list[dict[str, Any]]],
) -> list[dict[str, str | int | float]]:
    """Project normalized public records to the approved View schema.

    This is only for official public datasets that have already passed
    ``assert_safe_records``. It never exposes source IDs or fields outside the
    approved preview columns.
    """
    source_field_by_output = {"avg_resolution_hours": "resolution_hours"}
    output: list[dict[str, str | int | float]] = []
    for source_key in plan.selected_sources:
        for payload in records_by_source.get(source_key, []):
            row: dict[str, str | int | float] = {}
            valid = True
            for column in plan.preview_columns:
                if column == "case_count":
                    row[column] = 1
                    continue
                source_field = source_field_by_output.get(column, column)
                if source_field not in payload:
                    valid = False
                    break
                value = payload[source_field]
                if value is None:
                    row[column] = ""
                elif isinstance(value, (str, int, float)):
                    row[column] = value
                else:
                    valid = False
                    break
            if valid:
                output.append(row)
    return output
