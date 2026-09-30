"""Bundle the metakit package for the browser app (docs/app/metakit.zip).

Run after changing anything in metakit/:  python scripts/build_web.py
CI fails if the bundle is out of date (tests/test_web.py::test_web_bundle_is_current).
"""
import hashlib
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "app" / "metakit.zip"


def build_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / "metakit").glob("*.py")):
            info = zipfile.ZipInfo(f"metakit/{f.name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes())
    return buf.getvalue()


if __name__ == "__main__":
    data = build_bytes()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(data):,} bytes, sha256 {hashlib.sha256(data).hexdigest()[:12]})")
