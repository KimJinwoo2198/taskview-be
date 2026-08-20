import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import urlencode
from uuid import uuid4

import asyncpg
from cryptography.fernet import Fernet, InvalidToken

from .config import Settings
from .store import OutboxDeliveryRecord, PostgresNeedexStore


class DeliveryConfigurationError(Exception):
    pass


class DeliveryEncryptionError(Exception):
    pass


class MailDeliveryError(Exception):
    pass


@dataclass(frozen=True)
class MailMessage:
    recipient: str
    subject: str
    text_body: str


class Mailer(Protocol):
    async def send(self, message: MailMessage) -> None: ...


class TokenCipher:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode())
        except (TypeError, ValueError) as exc:
            raise DeliveryConfigurationError(
                "TASKVIEW_DELIVERY_ENCRYPTION_KEY가 유효한 Fernet 키가 아닙니다."
            ) from exc

    def encrypt(self, token: str) -> bytes:
        return self._fernet.encrypt(token.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode()
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise DeliveryEncryptionError("전달 토큰을 복호화할 수 없습니다.") from exc


class SMTPMailer:
    def __init__(self, settings: Settings) -> None:
        if not settings.taskview_smtp_host:
            raise DeliveryConfigurationError("TASKVIEW_SMTP_HOST가 설정되지 않았습니다.")
        if settings.taskview_smtp_use_tls and settings.taskview_smtp_use_starttls:
            raise DeliveryConfigurationError("SMTP TLS와 STARTTLS는 동시에 사용할 수 없습니다.")
        if bool(settings.taskview_smtp_username) != bool(settings.taskview_smtp_password):
            raise DeliveryConfigurationError("SMTP 사용자 이름과 비밀번호는 함께 설정해야 합니다.")
        self._host = settings.taskview_smtp_host
        self._port = settings.taskview_smtp_port
        self._username = settings.taskview_smtp_username
        self._password = (
            settings.taskview_smtp_password.get_secret_value()
            if settings.taskview_smtp_password
            else None
        )
        self._from_email = settings.taskview_smtp_from_email
        self._use_tls = settings.taskview_smtp_use_tls
        self._use_starttls = settings.taskview_smtp_use_starttls
        self._timeout = settings.taskview_smtp_timeout_seconds

    async def send(self, message: MailMessage) -> None:
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: MailMessage) -> None:
        email = EmailMessage()
        email["From"] = self._from_email
        email["To"] = message.recipient
        email["Subject"] = message.subject
        email.set_content(message.text_body)
        try:
            if self._use_tls:
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    self._host,
                    self._port,
                    timeout=self._timeout,
                    context=ssl.create_default_context(),
                )
            else:
                client = smtplib.SMTP(self._host, self._port, timeout=self._timeout)
            with client:
                if self._use_starttls:
                    client.starttls(context=ssl.create_default_context())
                if self._username and self._password:
                    client.login(self._username, self._password)
                client.send_message(email)
        except (OSError, smtplib.SMTPException):
            raise MailDeliveryError("SMTP 메일 전송에 실패했습니다.") from None


class InMemoryMailer:
    def __init__(self) -> None:
        self.messages: list[MailMessage] = []

    async def send(self, message: MailMessage) -> None:
        self.messages.append(message)


class DeliveryService:
    def __init__(self, settings: Settings, *, mailer: Mailer | None = None) -> None:
        self._settings = settings
        self._mailer = mailer
        if self._mailer is None and settings.taskview_smtp_host:
            self._mailer = SMTPMailer(settings)
        self._stop_event = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._worker_failures = 0

    def ensure_api_ready(self) -> None:
        self._cipher()
        if not self._settings.taskview_expose_dev_tokens and self._mailer is None:
            raise DeliveryConfigurationError("SMTP 전달 설정이 없어 인증 메일을 보낼 수 없습니다.")

    def encrypt_token(self, token: str) -> bytes:
        self.ensure_api_ready()
        return self._cipher().encrypt(token)

    def development_token(self, token: str) -> str | None:
        return token if self._settings.taskview_expose_dev_tokens else None

    async def start_worker(self, repository: PostgresNeedexStore) -> None:
        if (
            not self._settings.taskview_mail_worker_enabled
            or self._mailer is None
            or self._settings.taskview_delivery_encryption_key is None
        ):
            return
        self._cipher()
        self._stop_event.clear()
        self._worker_task = asyncio.create_task(
            self._worker_loop(repository), name="taskview-mail-outbox"
        )

    async def stop_worker(self) -> None:
        if self._worker_task is None:
            return
        self._stop_event.set()
        await self._worker_task
        self._worker_task = None

    async def drain_once(self, repository: PostgresNeedexStore) -> int:
        if self._mailer is None:
            raise DeliveryConfigurationError("SMTP 전달 설정이 없습니다.")
        cipher = self._cipher()
        worker_id = str(uuid4())
        deliveries = await repository.claim_outbox_deliveries(
            worker_id=worker_id,
            limit=self._settings.taskview_mail_worker_batch_size,
            max_attempts=self._settings.taskview_mail_worker_max_attempts,
            claim_seconds=self._settings.taskview_mail_worker_claim_seconds,
        )
        delivered = 0
        for delivery in deliveries:
            try:
                token = cipher.decrypt(delivery.token_ciphertext)
                await self._mailer.send(self._message_for(delivery, token))
            except (DeliveryEncryptionError, MailDeliveryError):
                await repository.mark_outbox_failed(
                    delivery.id,
                    worker_id=worker_id,
                    error="메일 전달에 실패했습니다.",
                    max_attempts=self._settings.taskview_mail_worker_max_attempts,
                )
                continue
            await repository.mark_outbox_delivered(delivery.id, worker_id=worker_id)
            delivered += 1
        return delivered

    async def _worker_loop(self, repository: PostgresNeedexStore) -> None:
        while not self._stop_event.is_set():
            try:
                await self.drain_once(repository)
            except asyncio.CancelledError:
                raise
            except (asyncpg.PostgresError, DeliveryConfigurationError, RuntimeError):
                self._worker_failures += 1
            except Exception:  # noqa: BLE001
                # Keep the worker alive without serializing exception arguments that may be sensitive.
                self._worker_failures += 1
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._settings.taskview_mail_worker_poll_seconds,
                )
            except TimeoutError:
                continue

    def _cipher(self) -> TokenCipher:
        secret = self._settings.taskview_delivery_encryption_key
        if secret is None:
            raise DeliveryConfigurationError(
                "TASKVIEW_DELIVERY_ENCRYPTION_KEY가 설정되지 않았습니다."
            )
        return TokenCipher(secret.get_secret_value())

    def _message_for(self, delivery: OutboxDeliveryRecord, token: str) -> MailMessage:
        query = urlencode({"token": token})
        base_url = self._settings.taskview_public_web_url.rstrip("/")
        if delivery.purpose == "email_verification":
            subject = "[Needex] 이메일을 확인해주세요"
            action_url = f"{base_url}/verify-email?{query}"
            action = "이메일 인증"
        elif delivery.purpose == "password_reset":
            subject = "[Needex] 비밀번호 재설정"
            action_url = f"{base_url}/reset-password?{query}"
            action = "비밀번호 재설정"
        else:
            subject = "[Needex] 워크스페이스 초대"
            action_url = f"{base_url}/workspace-invitations/accept?{query}"
            action = "워크스페이스 참여"
        body = (
            f"Needex {action} 요청입니다.\n\n"
            f"다음 링크를 열어 계속하세요:\n{action_url}\n\n"
            f"이 링크는 {delivery.expires_at.isoformat()}까지 유효합니다."
        )
        return MailMessage(
            recipient=delivery.recipient_email,
            subject=subject,
            text_body=body,
        )
