"""时空聚类：按拍摄时间 + GPS 距离对媒体文件分组。

分组规则：
- 同一地点（GPS 距离 ≤ 阈值）+ 同一天 → 同一组
- 换地点 / 跨天 → 新组
无 GPS 的文件按时间就近归入最近的组。
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

from .metadata import MediaMeta


@dataclass
class Group:
    """一个分组：同一地点同一时段的文件集合。"""

    files: list = field(default_factory=list)
    date: object = None          # datetime.date
    ref_gps: tuple = None        # (lat, lon) 当前位置（最近文件）
    min_time: datetime = None
    max_time: datetime = None

    def add(self, f):
        self.files.append(f)
        if self.min_time is None:
            self.min_time = f.time
            self.max_time = f.time
            self.date = f.time.date()
        else:
            self.min_time = min(self.min_time, f.time)
            self.max_time = max(self.max_time, f.time)


def haversine_km(p1, p2):
    """两点间大圆距离（公里）。"""
    lat1, lon1 = p1
    lat2, lon2 = p2
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return r * 2 * math.asin(math.sqrt(a))


def _nearest_group(groups, t):
    """找到时间上离 t 最近的组（边界距离最小）。"""
    best = None
    best_delta = None
    for g in groups:
        if g.min_time <= t <= g.max_time:
            delta = 0
        else:
            delta = min(
                abs((t - g.min_time).total_seconds()),
                abs((t - g.max_time).total_seconds()),
            )
        if best_delta is None or delta < best_delta:
            best = g
            best_delta = delta
    return best


def cluster_media(files, distance_km=5.0):
    """对 MediaMeta 列表做时空聚类，返回 Group 列表。"""
    with_gps = sorted([f for f in files if f.gps], key=lambda f: f.time)
    without_gps = sorted([f for f in files if not f.gps], key=lambda f: f.time)

    groups = []
    for f in with_gps:
        placed = False
        if groups:
            cur = groups[-1]
            if (f.time.date() == cur.date
                    and haversine_km(f.gps, cur.ref_gps) <= distance_km):
                cur.add(f)
                cur.ref_gps = f.gps
                placed = True
        if not placed:
            g = Group()
            g.add(f)
            g.ref_gps = f.gps
            groups.append(g)

    # 无 GPS 文件归入时间最近的组
    for f in without_gps:
        target = _nearest_group(groups, f.time)
        if target is not None:
            target.add(f)

    # 全部无 GPS：按天分组
    if not groups:
        by_date = {}
        for f in without_gps:
            d = f.time.date()
            if d not in by_date:
                g = Group()
                by_date[d] = g
                groups.append(g)
            by_date[d].add(f)

    return groups
