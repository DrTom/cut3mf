"""Command-line interface for cut3mf."""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from . import __version__
from .core import CutError, cut_file

EPILOG = """\
examples:
  cut3mf part.3mf                    remove the top 1 mm -> part_cut.3mf
  cut3mf part.3mf -d 1.2 -o out.3mf  remove the top 1.2 mm
  cut3mf part.3mf --axis bottom      plate on the bottom (same as --axis -z)
  cut3mf part.3mf --at 14.5          keep everything below Z = 14.5 mm
"""

_NEG_AXIS = re.compile(r"^-[xyz]$", re.IGNORECASE)


def _fix_negative_axis(argv: list[str]) -> list[str]:
    """Let '--axis -z' work: argparse would read '-z' as an option."""
    out, i = [], 0
    while i < len(argv):
        if argv[i] == "--axis" and i + 1 < len(argv) and _NEG_AXIS.match(argv[i + 1]):
            out.append(f"--axis={argv[i + 1]}")
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cut3mf",
        description="Cut a slab off one face of a 3MF/STL model before slicing, "
                    "e.g. a 1 mm helper plate that holds embedded text together.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", type=Path, help="input mesh (.3mf, .stl, .obj, ...)")
    p.add_argument("-o", "--output", type=Path,
                   help="output file (default: <input>_cut.<ext>)")
    p.add_argument("-d", "--depth", type=float, default=1.0,
                   help="thickness to remove from the outermost face, mm (default 1.0)")
    p.add_argument("--at", "--z", dest="at", type=float,
                   help="cut at this absolute coordinate (mm) instead of using --depth")
    p.add_argument("-a", "--axis", default="z",
                   help="face carrying the plate: top, bottom, front, back, left, right, "
                        "or x, -x, y, -y, z, -z (default: top)")
    p.add_argument("--eps", type=float, default=0.001,
                   help="extra cut depth against coplanar slivers, mm (default 0.001)")
    p.add_argument("-q", "--quiet", action="store_true", help="only print errors")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = _fix_negative_axis(list(sys.argv[1:] if argv is None else argv))
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.ERROR if args.quiet else logging.INFO,
                        format="%(message)s")
    try:
        r = cut_file(args.input, args.output, axis=args.axis, depth=args.depth,
                     at=args.at, eps=args.eps)
    except (CutError, OSError, ValueError) as e:
        print(f"cut3mf: error: {e}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"cut at {r.axis}={r.cut:.3f} mm (outermost {r.extreme:.3f} mm), "
              f"{len(r.kept)} object(s) -> {r.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
