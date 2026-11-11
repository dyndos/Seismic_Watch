#!/usr/bin/env python3
"""Create compiler-compatible working copies; never modify archived source files."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text(encoding="latin-1").replace("\r\n", "\n").replace("\r", "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gear1_source", type=Path)
    parser.add_argument("sphere_source", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--stop-after-step2", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    gear = read_text(args.gear1_source)
    replacements = [
        (', DISP = "KEEP"', ""),
        ("='p,ES12.4", "=',ES12.4"),
        (r"\)", ")"),
    ]
    for old, new in replacements:
        if old not in gear:
            raise SystemExit(f"Expected GEAR1 compatibility token not found: {old!r}")
        gear = gear.replace(old, new)

    sphere = read_text(args.sphere_source)
    sphere, removed = re.subn(
        r"(?ms)^\s*SUBROUTINE\s+MATHERRQQ\b.*?^\s*END SUBROUTINE\s+MATHERRQQ\s*\n?",
        "",
        sphere,
    )
    if removed != 1:
        raise SystemExit(f"Expected to remove one Intel-specific MATHERRQQ routine; removed {removed}")
    if r"\)" not in sphere:
        raise SystemExit("Expected one remaining backslash-parenthesis format token in Sphere")
    sphere = sphere.replace(r"\)", ")")

    if args.stop_after_step2:
        marker = '''    WRITE (*, "(' ===  STEP #3: Merge to create hybrid forecast H*       ================')")'''
        if marker not in gear:
            raise SystemExit("Could not locate STEP #3 diagnostic insertion point")
        diagnostic = '''    WRITE (*, "(' Diagnostic stop: STEP #1 and STEP #2 completed; STEP #3 not executed.')")
    WRITE (21, "('Diagnostic stop: STEP #1 and STEP #2 completed; STEP #3 not executed.')")
    FLUSH (21)
    STOP

'''
        gear = gear.replace(marker, diagnostic + marker, 1)

    (args.output_dir / "GEAR1_for_CSEP_gfortran.f90").write_text(gear, encoding="utf-8", newline="\n")
    (args.output_dir / "Sphere_gfortran.f90").write_text(sphere, encoding="utf-8", newline="\n")
    print("Created patched working copies. Original archive files were not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
