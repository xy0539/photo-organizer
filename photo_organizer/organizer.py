"""整理流程：扫描 → 提取元数据 → 聚类 → 建文件夹 → 移动/复制文件。"""

import os
import shutil
import sys
from pathlib import Path

from .metadata import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS, get_media_meta
from .cluster import cluster_media
from . import geocode

_INVALID_CHARS = set('\\/:*?"<>|')


def scan_media(source_dir):
    """递归扫描源目录，返回媒体文件路径列表。"""
    files = []
    for root, _dirs, names in os.walk(source_dir):
        for name in names:
            ext = Path(name).suffix.lower()
            if ext in PHOTO_EXTENSIONS or ext in VIDEO_EXTENSIONS:
                files.append(os.path.join(root, name))
    return files


def _sanitize(name):
    return "".join("_" if c in _INVALID_CHARS else c for c in name)


def _folder_name(group):
    date_str = group.date.strftime("%Y-%m-%d")
    if group.ref_gps:
        loc = geocode.get_location_name(*group.ref_gps)
    else:
        loc = "未定位"
    return _sanitize(f"{date_str} {loc}")


def _unique_folder(target_dir, name, used):
    """文件夹名冲突时追加 _2、_3 后缀。"""
    candidate = name
    suffix = 2
    while candidate in used or os.path.exists(os.path.join(target_dir, candidate)):
        candidate = f"{name}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _unique_filepath(folder, filename):
    """目标文件名冲突时追加 _1、_2 后缀，避免覆盖。"""
    dest = os.path.join(folder, filename)
    if not os.path.exists(dest):
        return dest
    stem = Path(filename).stem
    ext = Path(filename).suffix
    i = 1
    while True:
        dest = os.path.join(folder, f"{stem}_{i}{ext}")
        if not os.path.exists(dest):
            return dest
        i += 1


def organize(source_dir, target_dir, *, distance_km=5.0, move=False,
             dry_run=False, verbose=False):
    """主整理流程，返回退出码。"""
    source_dir = os.path.abspath(source_dir)
    target_dir = os.path.abspath(target_dir)

    if not os.path.isdir(source_dir):
        print(f"错误: 源目录不存在: {source_dir}", file=sys.stderr)
        return 1

    print(f"扫描源目录: {source_dir}")
    paths = scan_media(source_dir)
    print(f"找到 {len(paths)} 个媒体文件")
    if not paths:
        print("没有文件需要整理。")
        return 0

    # 提取元数据
    metas = []
    for i, p in enumerate(paths, 1):
        if verbose and i % 50 == 0:
            print(f"  解析元数据... {i}/{len(paths)}")
        metas.append(get_media_meta(p))

    # 时空聚类
    groups = cluster_media(metas, distance_km=distance_km)
    print(f"分为 {len(groups)} 组")

    if not geocode.is_available():
        print("提示: 未安装 PyGeoCN，地名将以坐标显示。"
              "安装: pip install pygeo-cn", file=sys.stderr)

    op = "移动" if move else "复制"
    used_folders = set()
    moved = copied = errors = 0

    for g in groups:
        folder_name = _unique_folder(target_dir, _folder_name(g), used_folders)
        folder = os.path.join(target_dir, folder_name)
        print(f"\n[{folder_name}]  ({len(g.files)} 个文件)")

        for f in g.files:
            dest = _unique_filepath(folder, os.path.basename(f.path))
            rel_dest = os.path.basename(dest)
            if verbose or dry_run:
                tag = "移动" if move else "复制"
                action = f"将{tag}" if dry_run else tag
                print(f"  {action}: {os.path.basename(f.path)} → {rel_dest}")
            try:
                if not dry_run:
                    os.makedirs(folder, exist_ok=True)
                    if move:
                        shutil.move(f.path, dest)
                        moved += 1
                    else:
                        shutil.copy2(f.path, dest)
                        copied += 1
            except OSError as e:
                print(f"  错误: {op}失败 {f.path}: {e}", file=sys.stderr)
                errors += 1

    # 汇总
    print()
    print("=" * 50)
    print("整理完成")
    print(f"  总文件数:    {len(paths)}")
    print(f"  分组数:      {len(groups)}")
    print(f"  {op}成功:     {moved if move else copied}")
    if errors:
        print(f"  失败:        {errors}")
    if dry_run:
        print("  (预览模式，未实际执行)")
    print("=" * 50)
    return 0 if errors == 0 else 1
