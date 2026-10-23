from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "bharat_bazaar.sqlite"
DOCS_DIR = DATA_DIR / "docs"
WHATSAPP_LOG = ROOT / "logs" / "whatsapp.log"

# The story is set on the Tuesday before Diwali 2026.
TODAY = date(2026, 11, 3)
THIS_WEEK = ("2026-10-27", "2026-11-02")
LAST_WEEK = ("2026-10-20", "2026-10-26")

TOOL_BUDGET = 8
FAULT_RATE = 0.15
