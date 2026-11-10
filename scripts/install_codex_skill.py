#!/usr/bin/env python3
"""Install a self-contained AAE skill from this checkout without overwriting skills."""

import argparse
import os
from pathlib import Path
import shutil
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest", type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills",
        help="Parent skills directory (default: $CODEX_HOME/skills or ~/.codex/skills)",
    )
    args = parser.parse_args()
    parent = args.dest.expanduser().resolve()
    target = parent / "aae"
    if target.exists() or target.is_symlink():
        parser.error(f"destination already exists: {target}; move it aside before reinstalling")
    root = Path(__file__).resolve().parents[1]
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".aae-install-", dir=parent) as staging:
        bundle = Path(staging) / "aae"
        bundle.mkdir()
        shutil.copy2(root / "AAE.md", bundle / "SKILL.md")
        shutil.copy2(root / "LICENSE", bundle / "LICENSE")
        report = bundle / "templates" / "report"
        report.mkdir(parents=True)
        for name in ("report.tex", "build_report.py"):
            shutil.copy2(root / "templates" / "report" / name, report / name)
        shutil.copytree(root / "knowledge-base", bundle / "knowledge-base")
        bundle.rename(target)
    print(f"Installed AAE to {target}. Available on your next Codex turn; invoke with $aae.")


if __name__ == "__main__":
    main()
