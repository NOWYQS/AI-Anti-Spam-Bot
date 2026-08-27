import logging
from collections.abc import Iterable


class SecretRedactionFilter(logging.Filter):
    """Render a record once and replace configured secrets before handlers write it."""

    def __init__(self, secrets: Iterable[str]):
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        for secret in self._secrets:
            rendered = rendered.replace(secret, "<redacted>")
        record.msg = rendered
        record.args = ()
        return True
