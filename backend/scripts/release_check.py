from pathlib import Path
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.main import app


def check_settings() -> None:
    settings = get_settings()
    print(f"settings: ok ({settings.app_env}, payment_provider={settings.payment_provider})")


def check_app_import() -> None:
    route_count = len(app.routes)
    if route_count == 0:
        raise RuntimeError("FastAPI app has no routes")
    print(f"app import: ok ({route_count} routes)")


def check_alembic_heads() -> None:
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(alembic_config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected exactly one Alembic head, found {heads}")
    print(f"alembic heads: ok ({heads[0]})")


def main() -> None:
    check_settings()
    check_app_import()
    check_alembic_heads()
    print("release check: ok")


if __name__ == "__main__":
    main()
