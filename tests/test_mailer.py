import asyncio
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from cryptography.fernet import Fernet

from taskview_be.config import Settings
from taskview_be.mailer import (
    DeliveryConfigurationError,
    DeliveryService,
    InMemoryMailer,
    TokenCipher,
)
from taskview_be.store import OutboxDeliveryRecord

DELIVERY_KEY = Fernet.generate_key().decode()


class FakeOutboxRepository:
    def __init__(self, delivery: OutboxDeliveryRecord | None) -> None:
        self.delivery = delivery
        self.delivered: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.claim_count = 0

    async def claim_outbox_deliveries(self, **_kwargs) -> list[OutboxDeliveryRecord]:
        self.claim_count += 1
        if self.delivery is None:
            return []
        delivery, self.delivery = self.delivery, None
        return [delivery]

    async def mark_outbox_delivered(self, delivery_id: str, *, worker_id: str) -> bool:
        self.delivered.append(delivery_id)
        return bool(worker_id)

    async def mark_outbox_failed(
        self,
        delivery_id: str,
        *,
        worker_id: str,
        error: str,
        max_attempts: int,
    ) -> bool:
        assert worker_id and max_attempts > 0
        self.failed.append((delivery_id, error))
        return True


class TransientRepository(FakeOutboxRepository):
    async def claim_outbox_deliveries(self, **kwargs) -> list[OutboxDeliveryRecord]:
        self.claim_count += 1
        if self.claim_count == 1:
            raise asyncpg.CannotConnectNowError("transient")
        return await super().claim_outbox_deliveries(**kwargs)


def delivery_settings(**overrides) -> Settings:
    values = {
        "taskview_delivery_encryption_key": DELIVERY_KEY,
        "taskview_expose_dev_tokens": False,
        "taskview_mail_worker_poll_seconds": 0.01,
    }
    values.update(overrides)
    return Settings(**values)


def test_fernet_cipher_never_persists_plaintext_and_rejects_invalid_key():
    cipher = TokenCipher(DELIVERY_KEY)
    token = "secret-one-time-token"
    ciphertext = cipher.encrypt(token)
    assert token.encode() not in ciphertext
    assert cipher.decrypt(ciphertext) == token
    assert Fernet(DELIVERY_KEY.encode()).decrypt(ciphertext).decode() == token

    with pytest.raises(DeliveryConfigurationError):
        TokenCipher("not-a-fernet-key")


def test_in_memory_mailer_drains_delivery_without_exposing_token_to_repository():
    token = "verification-token-value"
    ciphertext = TokenCipher(DELIVERY_KEY).encrypt(token)
    delivery = OutboxDeliveryRecord(
        id="7be9958b-0427-4352-99e7-a1a946e1a50b",
        purpose="email_verification",
        recipient_email="person@example.com",
        token_ciphertext=ciphertext,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        attempts=0,
    )
    repository = FakeOutboxRepository(delivery)
    mailer = InMemoryMailer()
    service = DeliveryService(delivery_settings(), mailer=mailer)

    assert asyncio.run(service.drain_once(repository)) == 1  # type: ignore[arg-type]
    assert repository.delivered == [delivery.id]
    assert repository.failed == []
    assert len(mailer.messages) == 1
    assert mailer.messages[0].recipient == "person@example.com"
    assert token in mailer.messages[0].text_body
    assert token not in repr(repository.delivered)


def test_worker_recovers_after_transient_postgres_error():
    repository = TransientRepository(None)
    service = DeliveryService(delivery_settings(), mailer=InMemoryMailer())

    async def exercise() -> None:
        await service.start_worker(repository)  # type: ignore[arg-type]
        for _ in range(20):
            if repository.claim_count >= 2:
                break
            await asyncio.sleep(0.01)
        await service.stop_worker()

    asyncio.run(exercise())
    assert repository.claim_count >= 2
