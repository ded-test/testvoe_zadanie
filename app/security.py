import hashlib
import hmac

from app.config import settings


def sign(raw_body: bytes, secret: str | None = None) -> str:
    key = (secret if secret is not None else settings.webhook_secret).encode()
    return hmac.new(key, raw_body, hashlib.sha256).hexdigest()


def verify(raw_body: bytes, header_value: str | None, secret: str | None = None) -> bool:
    if not header_value:
        return False
    provided = header_value.strip()
    if provided.lower().startswith("sha256="):
        provided = provided[len("sha256=") :]
    return hmac.compare_digest(provided, sign(raw_body, secret))
