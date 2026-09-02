"""时空聚类：按拍摄时间 + GPS 距离对媒体文件分组。

分组规则（核心逻辑）：
1. 有 GPS 的文件：按时间排序后顺序遍历，同一地点（距离 ≤ 阈值）且同一天 → 归入当前组；换地点或跨天 → 新建组
2. 无 GPS 的文件：在所有 GPS 组建好后处理——
   a. 若有同日期的 GPS 组 → 归入时间最近的那个组（同一天大概率在同一地点）
   b. 若没有同日期的组 → 按月份归入「YYYY-MM 未知地点」组（同月合并，避免一天一个文件夹）
   c. 若同月也没有未知地点组 → 新建月度组

这样保证：有位置信息的文件精细到天+地点，无位置信息的文件粗放到月，减少碎片文件夹。
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

    # 无 GPS 文件：先找同日期的GPS组归入，找不到则按月份归入未知地点组
    for f in without_gps:
        same_date = [g for g in groups if g.date == f.time.date()]
        if same_date:
            target = _nearest_group(same_date, f.time)
            target.add(f)
        else:
            file_month = (f.time.year, f.time.month)
            same_month = [g for g in groups
                          if g.ref_gps is None
                          and (g.date.year, g.date.month) == file_month]
            if same_month:
                same_month[0].add(f)
            else:
                g = Group()
                g.add(f)
                groups.append(g)

    return groups
