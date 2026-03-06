from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backend.apps.web_server import *  # noqa: F401,F403
from src.backend.apps.web_server import main


if __name__ == "__main__":
    raise SystemExit(main())
