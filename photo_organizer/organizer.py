"""整理流程：扫描 → 提取元数据 → 聚类 → 建文件夹 → 移动/复制文件。

文件夹结构：目标目录/年份/子文件夹/文件
- 第一层：年份（如 2018/）
- 第二层：有GPS用「YYYY-MM-DD 地名」，无GPS用「YYYY-MM 未知地点」

支持增量归集：对已有目标文件夹追加文件，已存在的同名文件自动跳过（不覆盖、不重命名）。
首次运行建文件夹并复制；再次运行只处理新文件，旧文件全部跳过。
"""

import hashlib
import os
import shutil
import sys
import time
from pathlib import Path

from .metadata import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS, get_media_meta
from .cluster import cluster_media, haversine_km
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
    """根据分组生成文件夹名：有GPS用「YYYY-MM-DD 地名」，无GPS用「YYYY-MM 未知地点」。"""
    if group.ref_gps:
        date_str = group.date.strftime("%Y-%m-%d")
        loc = geocode.get_location_name(*group.ref_gps)
    else:
        date_str = group.date.strftime("%Y-%m")
        loc = "未知地点"
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


def _md5(filepath, chunk_size=65536):
    """计算文件 MD5 哈希。"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _files_same(src, dst):
    """判断两个文件内容是否相同：先比大小，大小相同再比 MD5。"""
    try:
        if os.path.getsize(src) != os.path.getsize(dst):
            return False
        return _md5(src) == _md5(dst)
    except OSError:
        return False


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


def _read_folder_gps(folder_path, cache):
    """从已有文件夹中读取第一个有GPS的文件坐标，缓存结果。"""
    if folder_path in cache:
        return cache[folder_path]
    gps = None
    try:
        for entry in os.listdir(folder_path):
            filepath = os.path.join(folder_path, entry)
            if not os.path.isfile(filepath):
                continue
            ext = Path(entry).suffix.lower()
            if ext not in PHOTO_EXTENSIONS and ext not in VIDEO_EXTENSIONS:
                continue
            meta = get_media_meta(filepath)
            if meta and meta.gps:
                gps = meta.gps
                break
    except OSError:
        pass
    cache[folder_path] = gps
    return gps


def _find_matching_folder(year_dir, name, group_gps, distance_km, cache):
    """同年目录下有多个同名文件夹时，按GPS找最近的。

    返回最匹配的文件夹名（如 "2018-09-01 青岛·城阳区_2"）。
    无匹配则返回 None（调用方新建文件夹）。
    """
    candidates = []
    try:
        for entry in os.listdir(year_dir):
            full_path = os.path.join(year_dir, entry)
            if not os.path.isdir(full_path):
                continue
            if entry == name or entry.startswith(name + "_"):
                candidates.append((entry, full_path))
    except OSError:
        return None

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    # 多个同名文件夹，按GPS比距离
    if group_gps is None:
        return candidates[0][0]

    best_folder = None
    best_dist = float("inf")
    for folder_name, folder_path in candidates:
        gps = _read_folder_gps(folder_path, cache)
        if gps:
            dist = haversine_km(group_gps, gps)
            if dist < best_dist:
                best_dist = dist
                best_folder = folder_name

    if best_folder and best_dist <= distance_km:
        return best_folder
    return None


def organize(source_dir, target_dir, *, distance_km=5.0, move=False,
             dry_run=False, verbose=False):
    """主整理流程，返回退出码。"""
    source_dir = os.path.abspath(source_dir)
    target_dir = os.path.abspath(target_dir)

    if source_dir == target_dir:
        print("错误: 源目录和目标目录不能相同，会导致重复扫描和文件夹混乱。",
              file=sys.stderr)
        return 1

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
    failed_meta = 0
    for i, p in enumerate(paths, 1):
        if i % 50 == 0:
            print(f"  解析元数据... {i}/{len(paths)}")
        try:
            meta = get_media_meta(p)
            if meta:
                metas.append(meta)
            else:
                failed_meta += 1
        except Exception:
            print(f"  警告: 读取元数据失败，跳过: {os.path.basename(p)}",
                  file=sys.stderr)
            failed_meta += 1
    if failed_meta:
        print(f"  {failed_meta} 个文件无法读取元数据，已跳过")

    # 时空聚类
    groups = cluster_media(metas, distance_km=distance_km)
    print(f"分为 {len(groups)} 组")

    if not geocode.is_available():
        geocode.ensure_available()

    # 磁盘空间检查（复制模式或跨盘移动）
    if not dry_run:
        src_drive = os.path.splitdrive(source_dir)[0].lower()
        dst_drive = os.path.splitdrive(target_dir)[0].lower()
        need_check = (not move) or (src_drive != dst_drive)
        if need_check:
            total_size = 0
            for p in paths:
                try:
                    total_size += os.path.getsize(p)
                except OSError:
                    pass
            try:
                check_dir = target_dir if os.path.isdir(target_dir) \
                    else (os.path.dirname(target_dir) or ".")
                disk_info = shutil.disk_usage(check_dir)
                if total_size > disk_info.free:
                    print(f"警告: 目标磁盘空间可能不足", file=sys.stderr)
                    print(f"  需要约: {total_size / (1024**3):.1f} GB",
                          file=sys.stderr)
                    print(f"  剩余:   {disk_info.free / (1024**3):.1f} GB",
                          file=sys.stderr)
                    try:
                        answer = input("空间不足，是否继续？(y/n): ").strip().lower()
                    except EOFError:
                        answer = "n"
                    if answer != "y":
                        print("已取消。", file=sys.stderr)
                        return 1
            except OSError:
                pass

    op = "移动" if move else "复制"
    used_folders_by_year = {}  # {年份: 已用文件夹名集合}，用于同一年内避免重名
    gps_cache = {}  # {文件夹路径: GPS坐标}，缓存已有文件夹的GPS，避免重复读取
    moved = copied = skipped = errors = 0
    start_time = time.time()

    for g in groups:
        name = _folder_name(g)
        year = str(g.date.year)
        year_dir = os.path.join(target_dir, year)
        used = used_folders_by_year.setdefault(year, set())

        # 先检查本次运行是否已用过该名称（同一天同区县但不同地点的组）
        if name in used:
            folder_name = _unique_folder(year_dir, name, used)
            folder = os.path.join(year_dir, folder_name)
            print(f"\n[{year}/{folder_name}]  ({len(g.files)} 个文件)")
        elif os.path.isdir(os.path.join(year_dir, name)):
            # 文件夹已存在，检查是否有多个同名文件夹（含_2、_3后缀）
            match = _find_matching_folder(year_dir, name, g.ref_gps,
                                          distance_km, gps_cache)
            if match:
                used.add(match)
                folder = os.path.join(year_dir, match)
                print(f"\n[{year}/{match}]  (追加到已有文件夹)")
            else:
                folder_name = _unique_folder(year_dir, name, used)
                folder = os.path.join(year_dir, folder_name)
                print(f"\n[{year}/{folder_name}]  ({len(g.files)} 个文件)")
        else:
            folder_name = _unique_folder(year_dir, name, used)
            folder = os.path.join(year_dir, folder_name)
            print(f"\n[{year}/{folder_name}]  ({len(g.files)} 个文件)")

        # 处理该组内所有文件
        group_total = len(g.files)
        group_done = 0
        group_moved = group_copied = group_skipped = 0
        for f in g.files:
            filename = os.path.basename(f.path)
            dest = os.path.join(folder, filename)

            # 同名文件已存在：内容相同则跳过，不同则加后缀
            if os.path.exists(dest):
                if _files_same(f.path, dest):
                    print(f"  跳过(内容相同): {filename}")
                    skipped += 1
                    group_skipped += 1
                    group_done += 1
                    continue
                # 内容不同，加后缀避免覆盖
                dest = _unique_filepath(folder, filename)
                new_name = os.path.basename(dest)
                if verbose or dry_run:
                    tag = "移动" if move else "复制"
                    action = f"将{tag}" if dry_run else tag
                    print(f"  {action}: {filename} → {new_name} (同名不同内容)")

            if verbose or dry_run:
                tag = "移动" if move else "复制"
                action = f"将{tag}" if dry_run else tag
                print(f"  {action}: {filename} → {filename}")
            try:
                if not dry_run:
                    os.makedirs(folder, exist_ok=True)
                    if move:
                        shutil.move(f.path, dest)
                        moved += 1
                        group_moved += 1
                    else:
                        shutil.copy2(f.path, dest)
                        copied += 1
                        group_copied += 1
            except OSError as e:
                print(f"  错误: {op}失败 {f.path}: {e}", file=sys.stderr)
                errors += 1
            group_done += 1
            if group_total > 10 and group_done % 10 == 0:
                print(f"  处理中... {group_done}/{group_total}")

        # 每组完成后的进度摘要
        if group_total > 0:
            parts = []
            if group_moved or group_copied:
                n = group_moved if move else group_copied
                parts.append(f"{op}{n}")
            if group_skipped:
                parts.append(f"跳过{group_skipped}")
            if parts:
                print(f"  完成: {', '.join(parts)}")

    # 汇总
    elapsed = time.time() - start_time
    print()
    print("=" * 50)
    print("整理完成")
    print(f"  总文件数:    {len(paths)}")
    print(f"  分组数:      {len(groups)}")
    print(f"  {op}成功:     {moved if move else copied}")
    print(f"  跳过:        {skipped}")
    if errors:
        print(f"  失败:        {errors}")
    print(f"  耗时:        {elapsed:.1f}秒")
    if dry_run:
        print("  (预览模式，未实际执行)")
    print("=" * 50)
    return 0 if errors == 0 else 1
