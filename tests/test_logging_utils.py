import logging


def test_secret_redaction_filter_sanitizes_formatted_log_arguments():
    import logging_utils

    secret = "123456:secret-token"
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="HTTP Request: %s",
        args=(f"https://api.telegram.org/bot{secret}/getUpdates",),
        exc_info=None,
    )

    logging_utils.SecretRedactionFilter([secret]).filter(record)

    assert secret not in record.getMessage()
    assert "<redacted>" in record.getMessage()
