import pytest

from app.main import app


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    limiter = getattr(app.state, "rate_limiter", None)
    if limiter is not None:
        limiter.reset()
    yield
    if limiter is not None:
        limiter.reset()
