# LEGACY Survey FITS Re-Export SOP (Standard Operating Procedure)

> **版本**: v1.0 | **日期**: 2026-07-24
> **适用**: 修复 LEGACY 巡天全零数据缺陷
> **状态**: 48 个 LEGACY FITS 文件全部受影响，需逐一重新导出

---

## 1. 问题描述

### 1.1 现象

LEGACY 巡天目录下所有 48 个 FITS 文件 (`sample_data/fitsfile/LEGACY/`) 的像素数据**全部为零**。

### 1.2 根因

从 [legacysurvey.org](https://legacysurvey.org) 导出时发生错误 — 可能原因：
- API 请求参数不正确（未指定正确的 band/层）
- 坐标解析失败但未报错，返回了空数据
- 网络超时导致下载不完整
- JPEG/PNG 预览被误存为 FITS 格式

### 1.3 影响范围

- LEGACY 缩略图：全黑（已被 Pipeline 的 stretch 逻辑兜底 — 使用 0.5 百分位拉伸）
- LEGACY FITS 查看：Firefly 显示全黑图像
- LEGACY 源检测：零源（无数据可检测）
- LEGACY RGB 合成：g/r/i 三个通道均为零，合成图为黑色
- 多波段统计：LEGACY 数据被计为 1 个巡天，但实际不可用
- **实际可用巡天数：5 个（DSS2、2MASS、allWISE、NVSS、FIRST），非 6 个**

### 1.4 检测方法

Pipeline 提供两种检测方式：

```bash
# 方式 1：批量扫描（返回所有文件的 defective 标志）
curl "http://localhost:8200/pipeline/files?survey=LEGACY&check_integrity=true"

# 方式 2：单文件检查
curl "http://localhost:8200/pipeline/file/integrity?filename=LEGACY/xxx.fits"
```

响应示例：
```json
{
    "filename": "LEGACY/some_file.fits",
    "defective": true,
    "action": "Re-download from legacysurvey.org/viewer"
}
```

---

## 2. 重新导出操作流程

### 2.1 前提条件

- 能访问 https://legacysurvey.org/viewer
- 已知目标坐标（从现有文件名中提取 RA/Dec）
- 本地 Python 环境（用于批量下载脚本）

### 2.2 从文件名提取坐标

LEGACY 文件命名格式：
```
Dataset_LEGACY_RA_<ra>_Dec_<dec>_FOV_<fov>_Width_<w>_Height_<h>_<band>.fits
```

示例：
```
Dataset_LEGACY_RA_159.647_Dec_44.796_FOV_3.435_Width_15_Height_15_g.fits
→ RA=159.647°, Dec=44.796°, FOV=3.435 arcmin, band=g
```

### 2.3 单文件手动下载

1. 打开 https://legacysurvey.org/viewer
2. 在搜索框输入 `RA Dec`（如 `159.647 44.796`）
3. 选择对应波段（g/r/i/z）
4. 调整 FOV 与现有文件一致
5. 点击 "Download FITS" 按钮
6. 保存为原始文件名，覆盖 `sample_data/fitsfile/LEGACY/` 中的旧文件

### 2.4 批量下载脚本（推荐）

```python
#!/usr/bin/env python3
"""LEGACY Survey FITS re-downloader via legacysurvey.org cutout API.

Usage: python re-download-legacy.py [--dry-run] [--band g,r,i,z]
"""
import os, re, sys, time, argparse
from pathlib import Path
from urllib.request import urlretrieve
from urllib.parse import urlencode

LEGACY_CUTOUT_URL = "https://www.legacysurvey.org/viewer/cutout.fits"

# File naming pattern
PATTERN = re.compile(
    r'Dataset_LEGACY_RA_([\d.]+)_Dec_([\d.]+)_FOV_([\d.]+)_'
    r'Width_(\d+)_Height_(\d+)_(g|r|i|z)\.fits'
)

FITS_DIR = Path("D:/AliCPT/sample_data/fitsfile/LEGACY")

def parse_filename(name: str):
    m = PATTERN.match(name)
    if not m:
        return None
    return {
        "ra": float(m.group(1)),
        "dec": float(m.group(2)),
        "fov": float(m.group(3)),
        "width": int(m.group(4)),
        "height": int(m.group(5)),
        "band": m.group(6),
    }

def download_one(info: dict, output_path: Path, dry_run=False):
    """Download one FITS cutout from legacysurvey.org."""
    # Legacy Survey cutout API parameters
    # ra, dec in degrees; size in arcseconds; layer (band)
    size_arcsec = info["fov"] * 60  # arcmin → arcsec
    params = {
        "ra": info["ra"],
        "dec": info["dec"],
        "width": size_arcsec,
        "height": size_arcsec,
        "layer": info["band"],
        "pixscale": info["fov"] * 60 / info["width"],  # ~13.7 arcsec/pix
    }
    url = f"{LEGACY_CUTOUT_URL}?{urlencode(params)}"
    print(f"  → {url}")
    if not dry_run:
        try:
            urlretrieve(url, str(output_path))
            print(f"  ✓ Saved: {output_path.name}")
        except Exception as e:
            print(f"  ✗ Failed: {e}")

def main():
    parser = argparse.ArgumentParser(description="Re-download LEGACY FITS files")
    parser.add_argument("--dry-run", action="store_true", help="Print URLs without downloading")
    parser.add_argument("--band", default="g,r,i,z", help="Bands to download (comma-separated)")
    args = parser.parse_args()

    bands = [b.strip() for b in args.band.split(",")]

    files = sorted(FITS_DIR.glob("*.fits"))
    if not files:
        print(f"No LEGACY FITS files found in {FITS_DIR}")
        return

    success, failed, skipped = 0, 0, 0
    for fp in files:
        info = parse_filename(fp.name)
        if info is None:
            print(f"⚠ Cannot parse: {fp.name} — skipping")
            skipped += 1
            continue

        if info["band"] not in bands:
            skipped += 1
            continue

        print(f"\n{fp.name}")
        print(f"  RA={info['ra']}, Dec={info['dec']}, FOV={info['fov']}', "
              f"Size={info['width']}×{info['height']}, Band={info['band']}")

        download_one(info, fp, dry_run=args.dry_run)

        if not args.dry_run:
            # Verify downloaded file
            try:
                from astropy.io import fits
                import numpy as np
                with fits.open(str(fp), memmap=True) as hdul:
                    data = hdul[0].data if hdul[0].data is not None else None
                if data is not None and not np.all(data == 0):
                    print(f"  ✓ Verified: non-zero data, shape={data.shape}")
                    success += 1
                else:
                    print(f"  ✗ Still all-zero — may need different parameters")
                    failed += 1
            except Exception as e:
                print(f"  ✗ Verification failed: {e}")
                failed += 1

            time.sleep(1)  # Rate limit: 1 req/s

    print(f"\n{'='*60}")
    print(f"Done: {success} success, {failed} failed, {skipped} skipped")
    if args.dry_run:
        print("DRY-RUN mode — no files downloaded. Remove --dry-run to execute.")

if __name__ == "__main__":
    main()
```

### 2.5 下载后验证

```bash
# 1. 重新扫描 LEGACY 文件完整性
curl "http://localhost:8200/pipeline/files?survey=LEGACY&check_integrity=true"

# 预期结果: "defective_count": 0
# 如果仍有 defective 文件，单独检查并重试

# 2. 重建缩略图缓存
curl -X POST "http://localhost:8200/pipeline/cache/warmup?size=200&max_files=0"

# 3. 确认 Firefly 能正常显示 LEGACY FITS
# 打开前端 → FITS Search → 选择 LEGACY 文件 → 点击 Firefly 查看
```

---

## 3. 备用数据源

如果 legacysurvey.org 不可用或响应慢，可使用以下替代方案：

| 数据源 | URL | 说明 |
|--------|-----|------|
| Legacy Survey DR10 | https://www.legacysurvey.org/dr10/ | 正式数据发布页 |
| NOIRLab Astro Data Lab | https://datalab.noirlab.edu/ | 提供 SQL 查询 + 批量下载 |
| SkyView Virtual Observatory | https://skyview.gsfc.nasa.gov/ | 支持 LEGACY 波段直接下载 FITS |
| 本地替代 | 用 DSS2 代替 LEGACY | DSS2 覆盖相同天区且数据正常 |

---

## 4. 长期防护措施

### 4.1 自动化数据完整性检查

已在 Pipeline 中实现：
- `GET /pipeline/files?check_integrity=true` — 文件列表 + 全零检测
- `GET /pipeline/file/integrity?filename=...` — 单文件检查
- Thumbnail 端点拒绝生成全零数据缩略图（HTTP 422）

### 4.2 建议纳入 CI/部署流程

```bash
# 部署后自动检查
curl -s "http://localhost:8200/pipeline/files?check_integrity=true" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
  print(f'{d[\"defective_count\"]} defective FITS found'); \
  sys.exit(1 if d['defective_count'] > 0 else 0)"
```

### 4.3 前端防护

前端在文件浏览器中应：
1. 调用 `GET /pipeline/files?check_integrity=true` 获取文件列表
2. 对 `defective: true` 的文件显示 "⚠ 数据异常" 标签
3. 禁止在 Firefly/FITS 查看器中打开 defective 文件
4. 在多波段统计面板中不计入 defective 巡天的数量
