# heic-to-ultrahdr

Convert **Apple HDR HEIC** photos (iPhone) into **UltraHDR JPEGs** that show real HDR
in the browser — on **Chrome, Edge, and Safari** — and degrade gracefully to SDR
everywhere else.

iPhone HDR photos store an SDR base image plus a proprietary **gain map** (the
auxiliary image `urn:com:apple:photo:2020:aux:hdrgainmap`). Browsers can't use
Apple's gain map directly, and Google's `ultrahdr_app` **can't read it either**
(`xml parse error, could not find attribute hdrgm:Version`). The working trick:
pull the Apple gain map out with **libheif** (via `pillow-heif`), pair it with the
SDR base, and have **libultrahdr** assemble a standard UltraHDR JPEG.

**UltraHDR** (ISO 21496-1 / Google "JPEG_R" gain-map JPEG) is the one HDR image
format that renders across today's browsers *and* is backward compatible: HDR
displays show boosted highlights; SDR displays / older browsers just see the
embedded SDR base. So you can serve a single `.jpg` to everyone.

## How it works

For each HEIC:

1. **Extract the Apple gain map** — `pillow-heif` reads the `hdrgainmap` aux image
   (a half-resolution grayscale map). *Note:* the gain map lives in the HEIC, **not**
   in any paired `.MOV` — the MOV's auxiliary HDR streams decode flat/useless.
2. **Make the SDR base** — decode the HEIC primary to an 8-bit JPEG (optionally
   downscaled for the web).
3. **Assemble UltraHDR** — `ultrahdr_app -m 0 -i sdr.jpg -g gain.jpg -f metadata.cfg
   -z out.jpg` (libultrahdr "encode scenario 4") muxes the SDR base + gain map +
   metadata into one UltraHDR JPEG.

## Requirements

### 1. Python deps

```bash
pip install -r requirements.txt   # pillow, pillow-heif
```

### 2. `ultrahdr_app` (from libultrahdr)

There is **no official prebuilt binary** — you build it from
[google/libultrahdr](https://github.com/google/libultrahdr). You need CMake, Ninja,
a C/C++ toolchain, and **nasm**.

```bash
git clone --depth 1 https://github.com/google/libultrahdr.git
cd libultrahdr
cmake -G Ninja -S . -B build -DCMAKE_BUILD_TYPE=Debug -DUHDR_BUILD_DEPS=1
ninja -C build ultrahdr_app
```

#### Windows gotchas (hard-won)

- **Build at an ASCII-only path** (e.g. `C:\uhdrbuild`). libjpeg-turbo's SIMD is
  assembled with **nasm**, and nasm fails to open source files whose path contains
  non-ASCII characters (`nasm: fatal: unable to open input file ...`). The C/C++
  compiler tolerates such paths; nasm does not.
- **Use the Debug build** (`-DCMAKE_BUILD_TYPE=Debug`). Under MinGW GCC the **Release**
  build *compiles fine but segfaults* on its encode paths (an optimizer miscompile;
  disabling SIMD/intrinsics does **not** fix it). The Debug binary runs correctly —
  speed is irrelevant for a one-off batch. On MSVC or real Linux, Release is fine.
- No MSVC? MinGW-w64 GCC works (that's what these notes were validated on). Real
  Linux / WSL builds cleanly too.

Then point this tool at the binary:

```bash
export ULTRAHDR_APP=/path/to/libultrahdr/build/ultrahdr_app   # or --ultrahdr-app
```

## Usage

```bash
# single file -> ./ultrahdr_out/IMG_1234.jpg
python heic_to_ultrahdr.py IMG_1234.HEIC

# a folder, downscaled for the web, custom output dir + brightness
python heic_to_ultrahdr.py photos/ -o out/ --max-size 1920 --boost 3.0

# point at the binary explicitly
python heic_to_ultrahdr.py *.HEIC --ultrahdr-app C:/uhdrbuild/build/ultrahdr_app.exe
```

Options: `--boost` (HDR brightness ceiling, default 3.0), `--max-size` (downscale SDR
long edge), `--quality` (SDR JPEG quality), `-o/--out`, `--ultrahdr-app`.

Verify an output is valid UltraHDR:

```bash
ultrahdr_app -m 1 -j out/IMG_1234.jpg -P     # prints "Ultra HDR Image: Yes" + metadata
```

## Calibration

`metadata.cfg` controls the HDR look:

- **`maxContentBoost`** — the HDR brightness ceiling (linear gain). Higher = brighter
  highlights. ~3.0 (≈ +1.6 stops) is a tasteful default for landscapes; tune on a real
  HDR display.
- **`hdrCapacityMax`** — pinned to `maxContentBoost` so any display whose headroom
  reaches that value renders the *full* boost (e.g. recent iPhone OLEDs, HDR monitors);
  weaker HDR displays scale down automatically and never clip.

You can't really judge HDR on an SDR screen — but because UltraHDR is SDR-backward
compatible, a mis-tuned boost never breaks the SDR view. Iterate `--boost` against an
HDR display.

## Serving on the web

An UltraHDR JPEG is just a JPEG — serve it via a plain `<img src="...">` and supporting
browsers apply the gain map automatically on HDR displays. **Do not re-encode it** in
your image pipeline or the gain map is stripped. (With Next.js `<Image>`, set
`images.unoptimized: true`, or use a raw `<img>`, so the gain map reaches the browser
intact.)

## Limitations

- Only HEICs that actually contain an Apple gain map convert; plain/SDR HEICs are
  skipped (reported as `no Apple gain map`).
- Apple's gain map is fed to libultrahdr as the ISO gain map. The mapping is close but
  not a perfectly calibrated color-managed transform; for reference-grade fidelity
  Apple's own `toGainMapHDR` (macOS, uses Apple ImageIO) is the gold standard. For web
  delivery this pipeline is more than good enough and runs anywhere.

## Credits

- [google/libultrahdr](https://github.com/google/libultrahdr) — UltraHDR reference codec
- [pillow-heif](https://github.com/bigcat88/pillow_heif) / libheif — HEIF + aux image access
