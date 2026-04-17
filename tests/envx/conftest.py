import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Ensure GLM-OCR stubs are on for the whole test suite unless a test overrides.
os.environ.setdefault("ENVX_GLM_OCR_STUB", "1")
os.environ.setdefault("ENVX_SCHEMAS_ROOT", str(ROOT / "schemas"))
