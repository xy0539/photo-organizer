# photo-organizer

按拍摄时间与地理位置整理照片和视频的轻量命令行工具。

读取照片（JPEG EXIF）和视频（MP4/MOV）的拍摄时间与 GPS 坐标，按「时间 + 地点」
自动聚类分组，创建形如 `2026-08-25 北京·东城区` 的文件夹，把文件移动进去。
没有 GPS 的文件按时间就近归入最近的文件夹。

## 特性

- **按时间 + 地点智能分组**：同一地点（GPS 距离 ≤ 5 公里）且同一天的照片/视频归为一组；换地点或跨天则新建一组
- **汉字地名**：离线通过 [PyGeoCN](https://github.com/CZD-MO/PyGeoCN) 将 GPS 坐标转为省/市/区县地名，无需联网、无需 API key
- **照片 + 视频**：内置 JPEG EXIF 解析（时间 + GPS），纯 Python 解析 MP4/MOV 元数据
- **无 GPS 兜底**：没有地理位置的文件按拍摄时间归入最近的分组
- **零外部服务**：不联网、不调第三方 API，全部本地完成
- **安全选项**：支持 `--dry-run` 预览、`--copy` 复制（默认移动）、`--distance` 调整聚类阈值

## 安装

```bash
git clone https://github.com/xy0539/photo-organizer.git
cd photo-organizer
pip install .
```

> 仅需一个依赖：`pygeo-cn`（PyGeoCN，纯 Python，自带数据，离线运行）。

## 用法

```bash
# 整理：把 ./photos 里的照片视频移动到 ./organized
photo-organizer ./photos ./organized

# 先预览（不实际移动），确认无误后再执行
photo-organizer ./photos ./organized --dry-run

# 改为复制（保留原件）
photo-organizer ./photos ./organized --copy

# 调整同一地点距离阈值（默认 5 公里），并显示详细过程
photo-organizer ./photos ./organized --distance 3 -v
```

也可以直接用模块方式运行（无需安装）：

```bash
python -m photo_organizer ./photos ./organized --dry-run
```

### 参数说明

| 参数 | 默认 | 说明 |
|------|------|------|
| `source` | — | 源照片/视频目录 |
| `target` | — | 目标输出目录 |
| `--distance` | `5.0` | 同一地点的距离阈值（公里） |
| `--copy` | 关 | 复制文件而非移动（默认移动） |
| `--dry-run` | 关 | 预览模式，只显示将执行的操作 |
| `-v, --verbose` | 关 | 显示详细处理信息 |
| `--version` | — | 显示版本号 |

## 工作原理

1. **扫描**：递归扫描源目录，识别照片（jpg/png/heic 等）和视频（mp4/mov/m4v/3gp）
2. **提取元数据**：
   - 照片：解析 JPEG EXIF 的 `DateTimeOriginal` 与 GPS IFD
   - 视频：解析 MP4/MOV 的 `mvhd`（拍摄时间）与 `©xyz`（iPhone 位置）
   - 解析失败时回退到文件修改时间
3. **时空聚类**：按时间排序后顺序遍历——GPS 距离 ≤ 阈值且同一天归为一组，否则新建一组
4. **命名文件夹**：用 PyGeoCN 查询每组坐标对应的省/市/区县，命名如 `2026-08-25 北京·东城区`
5. **归位**：将文件移动（或复制）到对应文件夹；无 GPS 文件按时间归入最近的组

## 输出示例

```
扫描源目录: ./photos
找到 1280 个媒体文件
分为 37 组

[2026-08-24 北京·东城区]  (52 个文件)
[2026-08-24 北京·海淀区]  (38 个文件)
[2026-08-25 杭州·西湖区]  (96 个文件)
...

==================================================
整理完成
  总文件数:    1280
  分组数:      37
  移动成功:     1280
==================================================
```

## 局限

- 视频元数据解析覆盖 MP4/MOV（手机主流）；AVI/MKV 等格式取不到 GPS 时回退到文件修改时间
- 离线地名粒度到区/县级（省/市/区县），不到街道/景点级
- 聚类采用顺序贪心策略：同一地点连续跨天会按天拆分

## 许可证

MIT，详见 [LICENSE](LICENSE)。
