#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2026 saucecat114514
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# See the LICENSE file in the project root for the full license text.
"""
heic_to_ultrahdr.py — convert Apple HDR HEIC photos to web-friendly UltraHDR JPEGs.

iPhone HDR photos store an SDR base image plus a proprietary *gain map*
(auxiliary image `urn:com:apple:photo:2020:aux:hdrgainmap`). Browsers can't use
Apple's gain map directly, and Google's `ultrahdr_app` can't read it either
("xml parse error, could not find attribute hdrgm:Version"). The trick: pull the
Apple gain map out with libheif (via pillow-heif), pair it with the SDR base, and
let libultrahdr assemble a standard **UltraHDR** JPEG.

UltraHDR (a.k.a. ISO 21496-1 / JPEG_R gain-map JPEG) is the one HDR image format
that renders on Chrome / Edge / Safari today AND degrades gracefully: HDR displays
show the boosted highlights, everything else just sees the embedded SDR base.

Pipeline (per HEIC):
  1. pillow-heif extracts the Apple gain map (grayscale aux image).
  2. The HEIC primary is decoded to an 8-bit SDR base JPEG (optionally downscaled).
  3. `ultrahdr_app -m 0 -i sdr.jpg -g gain.jpg -f metadata.cfg -z out.jpg`
     (libultrahdr "encode scenario 4") muxes them into an UltraHDR JPEG.

Requirements:
  - Python 3.9+  with  pillow  and  pillow-heif   (pip install -r requirements.txt)
  - ultrahdr_app  from  https://github.com/google/libultrahdr  (see README for a
    Windows build that actually works — TL;DR: build at an ASCII path and use the
    Debug build, the MinGW Release build segfaults).
    Point at it with  --ultrahdr-app  or the  ULTRAHDR_APP  env var.

Usage:
  python heic_to_ultrahdr.py IMG_1234.HEIC
  python heic_to_ultrahdr.py photos/ -o out/ --boost 3.0 --max-size 1920
  ULTRAHDR_APP=/path/to/ultrahdr_app python heic_to_ultrahdr.py *.HEIC
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import pillow_heif
    from PIL import Image
except ImportError:
    sys.exit("Missing deps. Run:  pip install -r requirements.txt")

# Let PIL's Image.open() handle .heic/.heif directly.
pillow_heif.register_heif_opener()

APPLE_GAINMAP = "urn:com:apple:photo:2020:aux:hdrgainmap"


def find_ultrahdr_app(explicit: str | None) -> str:
    """Locate the ultrahdr_app executable (arg > env > PATH)."""
    import shutil
    cand = explicit or os.environ.get("ULTRAHDR_APP")
    if cand:
        if os.path.isfile(cand):
            return cand
        sys.exit(f"ultrahdr_app not found at: {cand}")
    found = shutil.which("ultrahdr_app") or shutil.which("ultrahdr_app.exe")
    if found:
        return found
    sys.exit(
        "ultrahdr_app not found. Build it from https://github.com/google/libultrahdr "
        "and pass --ultrahdr-app PATH or set ULTRAHDR_APP. See README.md."
    )


def extract_gain_map(heic_path: str, out_jpg: str) -> bool:
    """Save the Apple HDR gain map (aux image) as a grayscale JPEG. False if absent."""
    heif = pillow_heif.open_heif(heic_path, convert_hdr_to_8bit=False)
    ids = (heif.info.get("aux") or {}).get(APPLE_GAINMAP)
    if not ids:
        return False
    heif.get_aux_image(ids[0]).to_pillow().convert("L").save(out_jpg, quality=97)
    return True


def make_sdr_base(heic_path: str, out_jpg: str, max_size: int | None, quality: int) -> None:
    """Decode the HEIC primary image to an 8-bit SDR JPEG (optionally downscaled)."""
    im = Image.open(heic_path).convert("RGB")
    if max_size and max(im.size) > max_size:
        im.thumbnail((max_size, max_size), Image.LANCZOS)
    im.save(out_jpg, quality=quality)


def write_metadata(path: str, boost: float) -> None:
    """libultrahdr gain-map metadata. maxContentBoost = HDR brightness ceiling (linear).
    hdrCapacityMax is pinned to it so any display with that headroom shows the full
    boost (weaker HDR displays scale down). Tune `boost` on a real HDR display."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"--maxContentBoost {boost} {boost} {boost}\n")
        f.write("--minContentBoost 1.0 1.0 1.0\n")
        f.write("--gamma 1.0 1.0 1.0\n")
        f.write("--offsetSdr 0.0 0.0 0.0\n")
        f.write("--offsetHdr 0.0 0.0 0.0\n")
        f.write("--hdrCapacityMin 1.0\n")
        f.write(f"--hdrCapacityMax {boost}\n")
        f.write("--useBaseColorSpace 1\n")


def convert_one(app: str, heic: str, dst: str, boost: float,
                max_size: int | None, quality: int) -> str:
    """Returns 'ok' | 'no-gainmap' | 'error: ...'."""
    with tempfile.TemporaryDirectory() as tmp:
        sdr = os.path.join(tmp, "sdr.jpg")
        gain = os.path.join(tmp, "gain.jpg")
        meta = os.path.join(tmp, "metadata.cfg")
        if not extract_gain_map(heic, gain):
            return "no-gainmap"
        make_sdr_base(heic, sdr, max_size, quality)
        write_metadata(meta, boost)
        r = subprocess.run(
            [app, "-m", "0", "-i", sdr, "-g", gain, "-f", meta, "-z", dst],
            capture_output=True, text=True,
        )
        if r.returncode != 0 or not os.path.exists(dst):
            return f"error: rc={r.returncode} {r.stdout.strip()[-200:]}"
    return "ok"


def collect_heics(inputs: list[str]) -> list[str]:
    out: list[str] = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            out += [str(x) for x in sorted(p.iterdir())
                    if x.suffix.lower() in (".heic", ".heif")]
        elif p.is_file():
            out.append(str(p))
        else:
            print(f"  skip (not found): {inp}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Apple HDR HEIC -> UltraHDR JPEG")
    ap.add_argument("inputs", nargs="+", help="HEIC file(s) or a directory of them")
    ap.add_argument("-o", "--out", default="ultrahdr_out", help="output directory")
    ap.add_argument("--boost", type=float, default=3.0,
                    help="maxContentBoost / HDR brightness ceiling (linear, default 3.0)")
    ap.add_argument("--max-size", type=int, default=None,
                    help="downscale the SDR base so its long edge <= this many px")
    ap.add_argument("--quality", type=int, default=95, help="SDR base JPEG quality")
    ap.add_argument("--ultrahdr-app", default=None,
                    help="path to ultrahdr_app (or set ULTRAHDR_APP)")
    args = ap.parse_args()

    app = find_ultrahdr_app(args.ultrahdr_app)
    os.makedirs(args.out, exist_ok=True)
    heics = collect_heics(args.inputs)
    if not heics:
        sys.exit("No HEIC inputs found.")

    ok = skipped = errs = 0
    for heic in heics:
        slug = Path(heic).stem
        dst = os.path.join(args.out, slug + ".jpg")
        status = convert_one(app, heic, dst, args.boost, args.max_size, args.quality)
        if status == "ok":
            kb = os.path.getsize(dst) // 1024
            print(f"  ok        {slug}.jpg  ({kb} KB)")
            ok += 1
        elif status == "no-gainmap":
            print(f"  skip      {slug}: no Apple gain map (not an HDR HEIC)")
            skipped += 1
        else:
            print(f"  ERROR     {slug}: {status}")
            errs += 1

    print(f"\nDone. ok={ok} skipped={skipped} errors={errs}  "
          f"(boost={args.boost}, out={args.out})")
    print("Verify any output with:  ultrahdr_app -m 1 -j <file>.jpg -P  "
          "(prints 'Ultra HDR Image: Yes')")


if __name__ == "__main__":
    main()
