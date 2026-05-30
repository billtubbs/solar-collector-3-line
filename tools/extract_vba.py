#!/usr/bin/env python3
"""Extract VBA macros from an .xlsm into excel/macros/ as text files.

Usage:
    python tools/extract_vba.py "excel/Your Workbook.xlsm"

The script uses oletools. If oletools isn't installed, run:
    python -m pip install oletools
"""

import os
import sys


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def extract(xlsm_path: str, out_dir: str = "excel/macros") -> int:
    try:
        from oletools.olevba import VBA_Parser
    except Exception as e:
        print(
            "oletools is required but not installed. Install with: python -m pip install oletools",
            file=sys.stderr,
        )
        return 2

    if not os.path.isfile(xlsm_path):
        print(f"File not found: {xlsm_path}", file=sys.stderr)
        return 3

    ensure_dir(out_dir)

    vb = VBA_Parser(xlsm_path)
    modules = []
    for filename, stream_path, vba_filename, vba_code in vb.extract_macros():
        if not vba_code:
            continue
        # sanitize filename
        if vba_filename:
            base = os.path.splitext(os.path.basename(vba_filename))[0]
        else:
            # fallback to stream_path or filename
            base = os.path.splitext(os.path.basename(filename or stream_path))[
                0
            ]
        out_name = f"{base}.vba"
        out_path = os.path.join(out_dir, out_name)
        with open(out_path, "w", encoding="utf-8", errors="replace") as f:
            f.write(vba_code)
        modules.append(out_name)

    # write index
    idx_path = os.path.join(out_dir, "index.txt")
    with open(idx_path, "w", encoding="utf-8") as idx:
        idx.write("\n".join(modules))

    print(f"Extracted {len(modules)} module(s) to {out_dir}")
    vb.close()
    return 0


def main(argv):
    if len(argv) < 2:
        print("Usage: python tools/extract_vba.py <path-to-xlsm>")
        return 1
    path = argv[1]
    return extract(path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
