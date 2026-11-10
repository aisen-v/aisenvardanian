import pytest


@pytest.fixture(autouse=True)
def _default_backend(monkeypatch):
    """Tests choose their backend explicitly; ignore the developer's environment."""
    for var in ("GARMIN_BACKEND", "GARMIN_CLIENT_ID", "GARMIN_CLIENT_SECRET", "GARMINTOKENS",
                "GARMIN_REDIRECT_URI", "GARMIN_DATA_DB", "GARMIN_CONNECTOR_TOKEN"):
        monkeypatch.delenv(var, raising=False)
