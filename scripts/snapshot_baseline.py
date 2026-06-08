"""Snapshot the live bot configuration to a frozen baseline directory.

Captures:
  - git rev/branch (best effort)
  - SHA-256 hashes of the bot source files we'd ever consider tuning
  - Copies of those source files
  - A small JSON manifest with timestamps + key thresholds extracted from
    polyou_bot.py via regex (RR_MIN, rr_min, MAJOR_ASSETS threshold)

Output: logs/derived/baseline_<YYYYMMDD-HHMMSS>/

This freezes "what the bot looked like before the validation week" so the
eventual A/B comparison has an unambiguous reference. Pure read-only;
does not touch the live bot.

Usage:
    .venv/Scripts/python.exe scripts/snapshot_baseline.py
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC_FILES = [
    "src/polyou/bots/polyou_bot.py",
    "src/polyou/core/data.py",
    "src/polyou/core/risk.py",
    "src/polyou/execution/execution_client.py",
    "src/polyou/markets/polymarket_crypto_resolver.py",
    "scripts/run_bot_forever.ps1",
]
THRESHOLD_PATTERNS = [
    (r"^\s*RR_MIN\s*=\s*([0-9.]+)", "RR_MIN"),
    (r"^\s*rr_min\s*=\s*([0-9.]+)", "rr_min_inline"),
    (r"base_threshold\s*=\s*([0-9.]+)\s*if\s*symbol\s*in\s*MAJOR_ASSETS\s*else\s*([0-9.]+)", "major_vs_other"),
]


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()
    except Exception as exc:  # noqa: BLE001
        return f"<git error: {exc}>"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_thresholds(text: str) -> dict:
    out: dict = {}
    for pat, label in THRESHOLD_PATTERNS:
        matches = re.findall(pat, text, flags=re.MULTILINE)
        if matches:
            out[label] = matches
    return out


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = REPO / "logs" / "derived" / f"baseline_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict = {
        "snapshot_ts": datetime.now().isoformat(timespec="seconds"),
        "git_rev": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "files": {},
    }

    for rel in SRC_FILES:
        src = REPO / rel
        if not src.exists():
            manifest["files"][rel] = {"present": False}
            continue
        digest = _sha256(src)
        dst = out_dir / Path(rel).name
        shutil.copy2(src, dst)
        entry: dict = {
            "present": True,
            "sha256": digest,
            "bytes": src.stat().st_size,
            "copied_to": str(dst.relative_to(REPO)),
        }
        if src.suffix == ".py":
            try:
                entry["thresholds"] = _extract_thresholds(src.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                entry["thresholds"] = {"_error": "decode"}
        manifest["files"][rel] = entry

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"baseline written to {out_dir}")
    print(f"  git_rev   = {manifest['git_rev']}")
    print(f"  files     = {len(manifest['files'])}")
    print(f"  manifest  = {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
