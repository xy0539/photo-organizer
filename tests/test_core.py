"""photo-organizer 核心逻辑测试。

运行: python tests/test_core.py
"""

import os
import struct
import sys
import tempfile
from datetime import datetime

# 让 tests/ 能导入上级的 photo_organizer 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from photo_organizer.metadata import _read_jpeg_exif, MediaMeta  # noqa: E402
from photo_organizer.cluster import cluster_media, haversine_km  # noqa: E402


# ─────────────── 构造一个带 EXIF(时间+GPS) 的最小 JPEG ───────────────

def _build_exif_entry(tag, type_code, count, value_field):
    return struct.pack("<HHI", tag, type_code, count) + value_field


def build_test_jpeg(path):
    """构造一个含 DateTimeOriginal + GPS 的 JPEG，写入 path。"""
    # 预设偏移量（见上方布局注释）
    exif_ifd_off = 38
    gps_ifd_off = 76
    datestr_off = 56
    lat_off = 130
    lon_off = 154

    # TIFF 头
    tiff = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)

    # IFD0：2 条记录
    tiff += struct.pack("<H", 2)
    tiff += _build_exif_entry(0x8769, 4, 1, struct.pack("<I", exif_ifd_off))  # ExifIFD
    tiff += _build_exif_entry(0x8825, 4, 1, struct.pack("<I", gps_ifd_off))  # GPSIFD
    tiff += struct.pack("<I", 0)  # next IFD

    # ExifIFD：1 条记录 (DateTimeOriginal)
    tiff += struct.pack("<H", 1)
    tiff += _build_exif_entry(0x9003, 2, 20, struct.pack("<I", datestr_off))
    tiff += struct.pack("<I", 0)
    datestr = b"2026:08:25 10:30:00\x00"
    assert len(datestr) == 20
    tiff += datestr

    # GPSIFD：4 条记录
    tiff += struct.pack("<H", 4)
    tiff += _build_exif_entry(0x0001, 2, 2, b"N\x00\x00\x00")            # LatitudeRef
    tiff += _build_exif_entry(0x0002, 5, 3, struct.pack("<I", lat_off))  # Latitude
    tiff += _build_exif_entry(0x0003, 2, 2, b"E\x00\x00\x00")            # LongitudeRef
    tiff += _build_exif_entry(0x0004, 5, 3, struct.pack("<I", lon_off))  # Longitude
    tiff += struct.pack("<I", 0)

    # 纬度: 39°54'30"  →  39.908333
    tiff += struct.pack("<II", 39, 1) + struct.pack("<II", 54, 1) + struct.pack("<II", 30, 1)
    # 经度: 116°23'15" → 116.3875
    tiff += struct.pack("<II", 116, 1) + struct.pack("<II", 23, 1) + struct.pack("<II", 15, 1)

    # 组装 JPEG
    seg = b"Exif\x00\x00" + tiff
    jpeg = b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(seg) + 2) + seg + b"\xff\xd9"
    with open(path, "wb") as f:
        f.write(jpeg)


def test_exif_parsing():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "test.jpg")
        build_test_jpeg(p)
        dt, gps = _read_jpeg_exif(p)
        assert dt == datetime(2026, 8, 25, 10, 30, 0), f"时间解析错误: {dt}"
        assert gps is not None, "GPS 解析为 None"
        lat, lon = gps
        assert round(lat, 4) == 39.9083, f"纬度错误: {lat}"
        assert round(lon, 4) == 116.3875, f"经度错误: {lon}"
    print("[PASS] EXIF 时间 + GPS 解析")


# ─────────────── 聚类测试 ───────────────

BEIJING = (39.9042, 116.4074)
SHANGHAI = (31.2304, 121.4737)  # 距北京 > 1000km


def _meta(path, time, gps, is_video=False):
    return MediaMeta(path, time, gps, is_video)


def test_same_location_same_day_one_group():
    files = [
        _meta("a.jpg", datetime(2026, 8, 25, 10, 0), BEIJING),
        _meta("b.jpg", datetime(2026, 8, 25, 14, 0), BEIJING),
        _meta("c.jpg", datetime(2026, 8, 25, 18, 0), BEIJING),
    ]
    groups = cluster_media(files, distance_km=5.0)
    assert len(groups) == 1, f"应为 1 组，实际 {len(groups)}"
    assert len(groups[0].files) == 3
    print("[PASS] 同地点同天 → 一组")


def test_same_location_diff_day_split():
    files = [
        _meta("a.jpg", datetime(2026, 8, 25, 10, 0), BEIJING),
        _meta("b.jpg", datetime(2026, 8, 26, 10, 0), BEIJING),
    ]
    groups = cluster_media(files, distance_km=5.0)
    assert len(groups) == 2, f"跨天应拆 2 组，实际 {len(groups)}"
    print("[PASS] 同地点跨天 → 拆分")


def test_diff_location_same_day_split():
    files = [
        _meta("a.jpg", datetime(2026, 8, 25, 10, 0), BEIJING),
        _meta("b.jpg", datetime(2026, 8, 25, 18, 0), SHANGHAI),
    ]
    groups = cluster_media(files, distance_km=5.0)
    assert len(groups) == 2, f"不同地点应拆 2 组，实际 {len(groups)}"
    print("[PASS] 不同地点同天 → 拆分")


def test_no_gps_assigned_to_nearest():
    files = [
        _meta("a.jpg", datetime(2026, 8, 25, 10, 0), BEIJING),
        _meta("b.jpg", datetime(2026, 8, 25, 12, 0), None),       # 无 GPS
        _meta("c.jpg", datetime(2026, 8, 25, 18, 0), SHANGHAI),
    ]
    groups = cluster_media(files, distance_km=5.0)
    # b 的 12:00 离 10:00(北京) 2 小时，离 18:00(上海) 6 小时 → 归北京组
    beijing_group = [g for g in groups if any(f.path == "a.jpg" for f in g.files)][0]
    assert any(f.path == "b.jpg" for f in beijing_group.files), "无 GPS 文件应归入最近的北京组"
    print("[PASS] 无 GPS → 归入时间最近的组")


def test_all_no_gps_grouped_by_date():
    files = [
        _meta("a.jpg", datetime(2026, 8, 25, 10, 0), None),
        _meta("b.jpg", datetime(2026, 8, 25, 18, 0), None),
        _meta("c.jpg", datetime(2026, 8, 26, 10, 0), None),
    ]
    groups = cluster_media(files, distance_km=5.0)
    assert len(groups) == 2, f"全部无 GPS 应按天分 2 组，实际 {len(groups)}"
    print("[PASS] 全部无 GPS → 按天分组")


def test_haversine():
    d = haversine_km(BEIJING, SHANGHAI)
    assert 1000 < d < 1200, f"北京-上海距离异常: {d}"
    d0 = haversine_km(BEIJING, BEIJING)
    assert d0 == 0
    print("[PASS] haversine 距离计算")


def test_geocode():
    try:
        from photo_organizer import geocode
    except Exception:
        print("[SKIP] geocode 模块不可用")
        return
    if not geocode.is_available():
        print("[SKIP] PyGeoCN 未安装，跳过地名测试")
        return
    name = geocode.get_location_name(39.9042, 116.4074)
    assert "北京" in name, f"北京坐标应含'北京'，实际: {name}"
    print(f"[PASS] geocode: 北京 → {name}")


def main():
    test_haversine()
    test_exif_parsing()
    test_same_location_same_day_one_group()
    test_same_location_diff_day_split()
    test_diff_location_same_day_split()
    test_no_gps_assigned_to_nearest()
    test_all_no_gps_grouped_by_date()
    test_geocode()
    print("\n全部测试通过 ✓")


if __name__ == "__main__":
    main()
