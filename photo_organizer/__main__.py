"""photo-organizer 命令行入口。

用法: python -m photo_organizer <源目录> <目标目录> [选项]
"""

import argparse
import sys

from . import __version__
from .organizer import organize


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="photo-organizer",
        description="按拍摄时间与地理位置整理照片和视频",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  python -m photo_organizer ./photos ./organized
  python -m photo_organizer ./photos ./organized --dry-run
  python -m photo_organizer ./photos ./organized --copy
  python -m photo_organizer ./photos ./organized --distance 3 -v
""",
    )
    parser.add_argument("source", help="源照片/视频目录")
    parser.add_argument("target", help="目标输出目录")
    parser.add_argument("--distance", type=float, default=5.0,
                        help="同一地点距离阈值(公里)，默认 5")
    parser.add_argument("--copy", action="store_true",
                        help="复制文件而非移动(默认移动)")
    parser.add_argument("--dry-run", action="store_true",
                        help="预览模式，只显示将执行的操作")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="显示详细处理信息")
    parser.add_argument("--version", action="version",
                        version=f"photo-organizer {__version__}")
    args = parser.parse_args(argv)

    return organize(
        args.source,
        args.target,
        distance_km=args.distance,
        move=not args.copy,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    sys.exit(main())
