from taskview_be.ai_client import _ai_headers
from taskview_be.config import Settings


def test_ai_shared_secret_is_forwarded_as_bearer_token():
    settings = Settings(taskview_ai_shared_secret="deployment-secret")

    assert _ai_headers(settings) == {"authorization": "Bearer deployment-secret"}


def test_ai_header_is_omitted_for_local_unprotected_mode():
    assert _ai_headers(Settings(taskview_ai_shared_secret=None)) == {}
