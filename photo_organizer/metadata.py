"""提取照片和视频的拍摄时间与 GPS 坐标。

照片: 纯 Python 解析 JPEG EXIF（DateTimeOriginal + GPS IFD）。
视频: 纯 Python 解析 MP4/MOV（mvhd creation_time + ©xyz 位置）。
其他格式或解析失败时回退到文件修改时间，GPS 置空。
"""

import os
import re
import struct
from datetime import datetime
from pathlib import Path

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif",
                    ".cr2", ".nef", ".arw", ".dng", ".rw2",
                    ".tif", ".tiff", ".bmp", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".3gp"}

_JPEG_MAGIC = b"\xff\xd8"

# ISO 6709 坐标，如 "+35.6601+139.7296+021.000"
_ISO6709_RE = re.compile(r"([+-]\d{1,3}(?:\.\d+)?)([+-]\d{1,3}(?:\.\d+)?)")

# EXIF 类型 → 字节数
_EXIF_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}


class MediaMeta:
    """单个媒体文件的元数据。"""

    __slots__ = ("path", "time", "gps", "is_video")

    def __init__(self, path, time, gps, is_video):
        self.path = path
        self.time = time          # datetime
        self.gps = gps            # (lat, lon) 或 None
        self.is_video = is_video

    def __repr__(self):
        return (f"MediaMeta({os.path.basename(self.path)}, "
                f"{self.time}, {self.gps}, video={self.is_video})")


# ──────────────────────────── EXIF (JPEG) ────────────────────────────

def _exif_read_ifd_entry(data, entry_off, endian):
    """读取一条 IFD 记录，返回 (tag, type_code, count, value_bytes)。"""
    tag, type_code, count = struct.unpack(endian + "HHI", data[entry_off:entry_off + 8])
    type_size = _EXIF_TYPE_SIZE.get(type_code, 1)
    total = count * type_size
    field = data[entry_off + 8:entry_off + 12]
    if total <= 4:
        value = field[:total]
    else:
        offset = struct.unpack(endian + "I", field)[0]
        value = data[offset:offset + total]
    return tag, type_code, count, value


def _exif_find_tag(data, ifd_off, target_tag, endian):
    """在指定 IFD 中查找标签，返回 (type_code, count, value_bytes) 或 None。"""
    if ifd_off + 2 > len(data):
        return None
    n = struct.unpack(endian + "H", data[ifd_off:ifd_off + 2])[0]
    for i in range(n):
        off = ifd_off + 2 + i * 12
        if off + 12 > len(data):
            break
        tag, type_code, count, value = _exif_read_ifd_entry(data, off, endian)
        if tag == target_tag:
            return type_code, count, value
    return None


def _exif_ascii(value):
    try:
        return value.decode("ascii", errors="replace").rstrip("\x00 ").strip()
    except Exception:
        return None


def _exif_rationals(value, count, endian):
    """解析 count 个有理数，返回 float 列表。"""
    out = []
    for i in range(count):
        chunk = value[i * 8:i * 8 + 8]
        if len(chunk) < 8:
            break
        num, den = struct.unpack(endian + "II", chunk)
        out.append(num / den if den else 0.0)
    return out


def _parse_exif_datestring(s):
    try:
        return datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _parse_gps(data, gps_off, endian):
    """从 GPS IFD 解析经纬度，返回 (lat, lon) 或 None。"""
    lat_tag = _exif_find_tag(data, gps_off, 0x0002, endian)   # GPSLatitude
    lat_ref = _exif_find_tag(data, gps_off, 0x0001, endian)   # N/S
    lon_tag = _exif_find_tag(data, gps_off, 0x0004, endian)   # GPSLongitude
    lon_ref = _exif_find_tag(data, gps_off, 0x0003, endian)    # E/W
    if not lat_tag or not lon_tag:
        return None
    lat_vals = _exif_rationals(lat_tag[2], 3, endian)
    lon_vals = _exif_rationals(lon_tag[2], 3, endian)
    if len(lat_vals) < 3 or len(lon_vals) < 3:
        return None
    lat = lat_vals[0] + lat_vals[1] / 60 + lat_vals[2] / 3600
    lon = lon_vals[0] + lon_vals[1] / 60 + lon_vals[2] / 3600
    if lat_ref and _exif_ascii(lat_ref[2]) == "S":
        lat = -lat
    if lon_ref and _exif_ascii(lon_ref[2]) == "W":
        lon = -lon
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return (lat, lon)
    return None


def _parse_tiff(data):
    """解析 TIFF 头 + IFD0，返回 (datetime, gps) 或 (None, None)。"""
    if len(data) < 8:
        return None, None
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        return None, None
    if struct.unpack(endian + "H", data[2:4])[0] != 42:
        return None, None
    ifd0 = struct.unpack(endian + "I", data[4:8])[0]

    # 时间：优先 ExifIFD 的 DateTimeOriginal (0x9003)
    dt = None
    exif_ifd = _exif_find_tag(data, ifd0, 0x8769, endian)
    if exif_ifd:
        exif_off = struct.unpack(endian + "I", exif_ifd[2][:4])[0]
        orig = _exif_find_tag(data, exif_off, 0x9003, endian)
        if orig:
            dt = _parse_exif_datestring(_exif_ascii(orig[2]))
    if not dt:
        mod = _exif_find_tag(data, ifd0, 0x0132, endian)  # DateTime
        if mod:
            dt = _parse_exif_datestring(_exif_ascii(mod[2]))

    # GPS
    gps = None
    gps_ifd = _exif_find_tag(data, ifd0, 0x8825, endian)
    if gps_ifd:
        gps_off = struct.unpack(endian + "I", gps_ifd[2][:4])[0]
        gps = _parse_gps(data, gps_off, endian)
    return dt, gps


def _read_jpeg_exif(filepath):
    """从 JPEG 文件解析 EXIF，返回 (datetime, gps) 或 (None, None)。"""
    try:
        with open(filepath, "rb") as f:
            if f.read(2) != _JPEG_MAGIC:
                return None, None
            while True:
                marker = f.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None, None
                seg_id = marker[1]
                if seg_id == 0xDA:  # SOS
                    return None, None
                seg_len = struct.unpack(">H", f.read(2))[0]
                seg_data = f.read(seg_len - 2)
                if seg_id == 0xE1 and seg_data[:4] == b"Exif":
                    return _parse_tiff(seg_data[6:])
    except (OSError, struct.error):
        return None, None
    return None, None


# ──────────────────────────── MP4 / MOV ────────────────────────────

_MP4_EPOCH_DELTA = 2082844800  # 1904-01-01 → 1970-01-01 秒数


def _iter_boxes(f, limit):
    """按字节偏移遍历顶层 box，yield (type, data_start, data_size)。"""
    pos = f.tell()
    while pos + 8 <= limit:
        f.seek(pos)
        header = f.read(8)
        if len(header) < 8:
            return
        size = struct.unpack(">I", header[:4])[0]
        btype = header[4:8]
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return
            size = struct.unpack(">Q", ext)[0]
            data_start = pos + 16
            data_size = size - 16
        elif size == 0:
            return  # 延伸到 EOF，无法定位边界
        else:
            data_start = pos + 8
            data_size = size - 8
        if data_size <= 0:
            return
        yield btype, data_start, data_size
        pos += size


def _parse_mvhd(data):
    """解析 mvhd box，返回 creation_time 的 datetime。"""
    if len(data) < 8:
        return None
    version = data[0]
    try:
        if version == 0:
            ct = struct.unpack(">I", data[4:8])[0]
        else:
            ct = struct.unpack(">Q", data[4:12])[0]
    except struct.error:
        return None
    try:
        return datetime.fromtimestamp(ct - _MP4_EPOCH_DELTA)
    except (OSError, ValueError, OverflowError):
        return None


def _parse_iso6709(raw):
    """解析 ISO 6709 坐标串，返回 (lat, lon) 或 None。"""
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="ignore")
    m = _ISO6709_RE.search(raw)
    if not m:
        return None
    lat = float(m.group(1))
    lon = float(m.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return (lat, lon)
    return None


def _find_video_gps(moov_data):
    """从 moov 数据中提取 GPS（iPhone ©xyz 原子）。"""
    idx = moov_data.find(b"\xa9xyz")
    if idx >= 0:
        content = moov_data[idx + 4:]
        data_idx = content.find(b"data")
        if data_idx >= 0:
            value = content[data_idx + 12:]  # data(4)+type_flags(4)+locale(4)
            coord = _parse_iso6709(value.split(b"\x00")[0])
            if coord:
                return coord
    # 回退：在 moov 中搜索 ISO6709 模式
    try:
        text = moov_data.decode("ascii", errors="ignore")
    except Exception:
        return None
    return _parse_iso6709(text)


def _read_mp4_metadata(filepath):
    """解析 MP4/MOV，返回 (datetime, gps) 或 (None, None)。"""
    try:
        fsize = os.path.getsize(filepath)
    except OSError:
        return None, None
    dt, gps = None, None
    try:
        with open(filepath, "rb") as f:
            for btype, dstart, dsize in _iter_boxes(f, fsize):
                if btype == b"moov":
                    # moov 通常不大，读入内存
                    if dsize > 64 * 1024 * 1024:
                        break
                    f.seek(dstart)
                    moov = f.read(dsize)
                    mvhd = _find_subbox(moov, 0, len(moov), b"mvhd")
                    if mvhd:
                        dt = _parse_mvhd(moov[mvhd[0]:mvhd[0] + mvhd[1]])
                    gps = _find_video_gps(moov)
                    break
    except (OSError, struct.error):
        pass
    return dt, gps


def _find_subbox(data, parent_start, parent_size, target):
    """在已读入内存的 data 中查找子 box，返回 (offset, size) 或 None。"""
    pos = parent_start
    end = parent_start + parent_size
    while pos + 8 <= end:
        size = struct.unpack(">I", data[pos:pos + 4])[0]
        btype = data[pos + 4:pos + 8]
        if size == 1:
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            return None
        else:
            header = 8
        if size < header:
            return None
        if btype == target:
            return pos + header, size - header
        pos += size
    return None


# ──────────────────────────── 统一入口 ────────────────────────────

def _mtime_fallback(filepath):
    try:
        return datetime.fromtimestamp(os.path.getmtime(filepath))
    except OSError:
        return datetime.now()


def get_media_meta(filepath):
    """提取单个文件的元数据，返回 MediaMeta。"""
    ext = Path(filepath).suffix.lower()
    is_video = ext in VIDEO_EXTENSIONS
    dt, gps = None, None

    if not is_video and ext in (".jpg", ".jpeg"):
        dt, gps = _read_jpeg_exif(filepath)
    elif is_video and ext in (".mp4", ".mov", ".m4v"):
        dt, gps = _read_mp4_metadata(filepath)

    if dt is None:
        dt = _mtime_fallback(filepath)
    return MediaMeta(filepath, dt, gps, is_video)
