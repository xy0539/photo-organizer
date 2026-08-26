"""离线逆地理编码：GPS 坐标 → 汉字地名。

使用 PyGeoCN（纯 Python，自带数据，不联网），粒度到区/县级。
未安装 PyGeoCN 时回退为坐标字符串。
"""

try:
    from PyGeoCN.regeo import regeo as _pygeocn_regeo
    _AVAILABLE = True
except ImportError:
    _pygeocn_regeo = None
    _AVAILABLE = False

# 坐标缓存：同一地点多次查询只算一次
_CACHE = {}

# 直辖市 / 特别行政区：省名即市名，避免重复
_MUNICIPALITIES = {"北京市", "上海市", "重庆市", "天津市", "香港特别行政区"}


def _cache_key(lat, lon):
    """四舍五入到 3 位小数（约 100m）作为缓存键。"""
    return (round(lat, 3), round(lon, 3))


def _strip_admin_suffix(name):
    """去掉省/市/自治区等行政后缀，缩短显示，如 '北京市'→'北京'。"""
    for suffix in ("特别行政区", "壮族自治区", "回族自治区",
                   "维吾尔自治区", "自治区", "省", "市"):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)]
    return name


def _format_name(province, city, district):
    """把省/市/区拼成简短地名，如 '北京·东城区'、'苏州·张家港市'。"""
    province = province or ""
    city = city or ""
    district = district or ""

    if province in _MUNICIPALITIES:
        # 直辖市：市名(去"市") · 区名
        first = _strip_admin_suffix(city or province)
    else:
        first = _strip_admin_suffix(city) if city else _strip_admin_suffix(province)
    parts = [p for p in (first, district) if p]
    return "·".join(parts)


def get_location_name(lat, lon):
    """返回坐标对应的汉字地名。无 GPS 时不应调用本函数。"""
    key = _cache_key(lat, lon)
    if key in _CACHE:
        return _CACHE[key]

    if not _AVAILABLE:
        name = f"{lat:.4f},{lon:.4f}"
        _CACHE[key] = name
        return name

    try:
        result = _pygeocn_regeo(lat, lon)
        if result and result.get("status") == 1:
            addr = result.get("address", {})
            name = _format_name(
                addr.get("province"),
                addr.get("city"),
                addr.get("district"),
            )
        else:
            name = f"{lat:.4f},{lon:.4f}"
    except Exception:
        name = f"{lat:.4f},{lon:.4f}"

    _CACHE[key] = name
    return name


def is_available():
    """PyGeoCN 是否已安装。"""
    return _AVAILABLE
