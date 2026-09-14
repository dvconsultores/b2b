"""Read-only Amazon SES API access: suppression list and send statistics (spec 003).

Uses a separate IAM key with read-only SES permissions (`AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_REGION` in .env). Never sends email; errors carry the AWS error
code only, never credentials or response text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from b2b import ConfigError


class SesApiError(Exception):
    """An SES API call failed; the message is the AWS error code or exception type."""


@dataclass(frozen=True)
class AwsSettings:
    access_key_id: str
    secret_access_key: str = field(repr=False)
    region: str = "us-east-2"


@dataclass(frozen=True)
class SesClients:
    sesv2: object
    ses: object


@dataclass(frozen=True)
class Suppressed:
    email: str
    reason: str          # "BOUNCE" | "COMPLAINT"
    updated_at: datetime


@dataclass(frozen=True)
class SendStats:
    attempts: int = 0
    bounces: int = 0
    complaints: int = 0
    rejects: int = 0


def _placeholder(value: str) -> bool:
    value = value.strip()
    return not value or value.startswith("<")


def load_aws_settings(env_path: Path) -> AwsSettings:
    env_path = Path(env_path)
    values = dotenv_values(env_path) if env_path.is_file() else {}
    key = values.get("AWS_ACCESS_KEY_ID") or ""
    secret = values.get("AWS_SECRET_ACCESS_KEY") or ""
    region = (values.get("AWS_REGION") or "").strip() or "us-east-2"
    if _placeholder(key):
        raise ConfigError(f"{env_path}: missing AWS_ACCESS_KEY_ID")
    if _placeholder(secret):
        raise ConfigError(f"{env_path}: missing AWS_SECRET_ACCESS_KEY")
    return AwsSettings(key.strip(), secret.strip(), region)


def make_clients(settings: AwsSettings) -> SesClients:
    import boto3

    session = boto3.Session(
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name=settings.region,
    )
    return SesClients(sesv2=session.client("sesv2"), ses=session.client("ses"))


def _call(function, **kwargs):
    try:
        return function(**kwargs)
    except Exception as exc:  # botocore ClientError / BotoCoreError / connection errors
        response = getattr(exc, "response", None)
        code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
        raise SesApiError(code or type(exc).__name__) from None


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def list_suppressed(clients: SesClients) -> list[Suppressed]:
    """The whole account-level suppression list (addresses SES will not deliver to)."""
    result: list[Suppressed] = []
    token = None
    while True:
        kwargs = {"PageSize": 1000}
        if token:
            kwargs["NextToken"] = token
        page = _call(clients.sesv2.list_suppressed_destinations, **kwargs)
        for item in page.get("SuppressedDestinationSummaries", []):
            result.append(Suppressed(
                email=item["EmailAddress"].strip().lower(),
                reason=item["Reason"],
                updated_at=_aware(item["LastUpdateTime"]),
            ))
        token = page.get("NextToken")
        if not token:
            return result


def send_statistics(clients: SesClients, since: datetime) -> SendStats:
    """Account sending totals from the 15-minute data points at or after `since` (last 14 days max)."""
    points = _call(clients.ses.get_send_statistics).get("SendDataPoints", [])
    totals = {"DeliveryAttempts": 0, "Bounces": 0, "Complaints": 0, "Rejects": 0}
    for point in points:
        if _aware(point["Timestamp"]) >= since:
            for key in totals:
                totals[key] += int(point.get(key, 0))
    return SendStats(totals["DeliveryAttempts"], totals["Bounces"], totals["Complaints"], totals["Rejects"])
