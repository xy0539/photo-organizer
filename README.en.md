# photo-organizer

English | [简体中文](README.md)

A lightweight CLI tool that organizes photos and videos by shooting time and geographic location.

Reads shooting time and GPS coordinates from photos (JPEG EXIF) and videos (MP4/MOV),
clusters them by "time + location", creates year-level folders with date+location or
month+unknown sub-folders inside, and moves files in. Files without GPS are grouped by
month into folders like `2026-08 Unknown`.

## Features

- **Smart grouping by time + location**: photos/videos taken at the same place (GPS distance ≤ 5 km) on the same day are grouped together; different place or different day creates a new group
- **Chinese place names**: offline GPS-to-location conversion via [PyGeoCN](https://github.com/CZD-MO/PyGeoCN) (province/city/district), no internet or API key required
- **Photos + videos**: built-in JPEG EXIF parsing (time + GPS), pure Python MP4/MOV metadata parsing
- **No-GPS fallback**: files without GPS are grouped by month into `YYYY-MM Unknown` folders, avoiding fragmentation
- **Incremental updates**: re-running appends new files to existing folders; same-name files are compared by size + MD5 — identical content is skipped, different content gets a suffix
- **Zero external services**: no internet, no third-party APIs, fully local
- **Safety options**: `--dry-run` preview, `--copy` (copy instead of move), `--distance` to adjust clustering threshold

## Installation

```bash
git clone https://github.com/xy0539/photo-organizer.git
cd photo-organizer
pip install .
```

> Only one dependency: `pygeo-cn` (PyGeoCN, pure Python, bundled data, offline).

## Usage

```bash
# Organize: move photos/videos from ./photos to ./organized
photo-organizer ./photos ./organized

# Preview first (no actual moves), then run for real
photo-organizer ./photos ./organized --dry-run

# Copy instead of move (keep originals)
photo-organizer ./photos ./organized --copy

# Adjust distance threshold (default 5 km) and show verbose output
photo-organizer ./photos ./organized --distance 3 -v
```

Or run as a module without installing:

```bash
python -m photo_organizer ./photos ./organized --dry-run
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `source` | — | Source directory with photos/videos |
| `target` | — | Output directory |
| `--distance` | `5.0` | Distance threshold in km for same-location grouping |
| `--copy` | off | Copy files instead of moving (default: move) |
| `--dry-run` | off | Preview mode, show what would be done |
| `-v, --verbose` | off | Show detailed processing info |
| `--version` | — | Show version |

## How It Works

1. **Scan**: recursively scans the source directory (including all subdirectories) for the following file types:

   | Type | Formats | Notes |
   |------|---------|-------|
   | Photo | .jpg .jpeg | JPEG, full EXIF parsing (time + GPS) |
   |       | .png .gif .bmp .webp | Common image formats, no EXIF, uses file modification time |
   |       | .heic .heif | iPhone Live Photo format |
   |       | .cr2 .nef .arw .dng .rw2 | DSLR/mirrorless RAW formats |
   |       | .tif .tiff | TIFF format |
   | Video | .mp4 .mov | Full parsing (mvhd time + ©xyz GPS) |
   |       | .m4v .3gp | Uses file modification time, usually no GPS |

2. **Extract metadata**:
   - Photos: parse JPEG EXIF `DateTimeOriginal` and GPS IFD
   - Videos: parse MP4/MOV `mvhd` (shooting time) and `©xyz` (iPhone location)
   - Falls back to file modification time if parsing fails
3. **Spatiotemporal clustering**:
   - Files with GPS: sorted by time, then grouped — same location (distance ≤ threshold) and same day → one group, otherwise new group
   - Files without GPS: first try to join a same-date GPS group, otherwise grouped by month into "Unknown" groups
4. **Folder naming**:
   - First level: year (e.g., `2018/`)
   - Second level: GPS groups use `YYYY-MM-DD Place` (e.g., `2018-06-24 Beijing·Dongcheng`); non-GPS groups use `YYYY-MM Unknown`
5. **Place files**: move (or copy) files into corresponding folders; existing folders are appended to, same-name files compared by size + MD5 — identical content skipped, different content suffixed (e.g., `_1`)

## Example Output

```
Scanning source: ./photos
Found 1280 media files
Clustered into 37 groups

[2018/2018-06-24 Beijing·Dongcheng]  (52 files)
[2018/2018-06-24 Beijing·Haidian]   (38 files)
[2018/2018-08 Unknown]              (18 files)
[2019/2019-01-05 Hangzhou·Xihu]     (96 files)
[2019/2019-02 Unknown]              (12 files)
...

==================================================
Done
  Total files:   1280
  Groups:        37
  Moved:         1262
  Skipped:       18
==================================================
```

## Limitations

- Video metadata parsing covers MP4/MOV (mainstream phone formats); AVI/MKV etc. fall back to file modification time when GPS is unavailable
- Offline place name granularity is at district/county level (province/city/district), not street/landmark level
- Clustering uses a sequential greedy strategy: the same location across consecutive days is split by day

## License

MIT, see [LICENSE](LICENSE).

## Acknowledgments

Developed by [xy0539](https://github.com/xy0539) with assistance from [TRAE](https://trae.cn) AI.
