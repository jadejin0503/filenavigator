#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 assets/pfn_logo_source.png 生成 assets/app_icon.ico（多尺寸），供 PyInstaller 嵌入 exe。

Windows 桌面/资源管理器显示的 exe 图标来自 PE 内嵌 ICO，与运行时 setWindowIcon 无关；
若只换了 PNG 未更新 app_icon.ico，桌面上仍会显示旧图标。
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    png_path = os.path.join(root, "assets", "pfn_logo_source.png")
    ico_path = os.path.join(root, "assets", "app_icon.ico")
    if not os.path.isfile(png_path):
        print(f"[build_app_icon] 未找到: {png_path}", file=sys.stderr)
        return 1
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("[build_app_icon] 需要 Pillow，请执行: pip install Pillow", file=sys.stderr)
        return 1

    def _round_corners_rgba(im: "Image.Image", radius_px: int) -> "Image.Image":
        """将 RGBA 方形图裁成圆角矩形（alpha 与圆角外透明）。"""
        im = im.convert("RGBA")
        w, h = im.size
        r = max(0, min(radius_px, w // 2, h // 2))
        if r <= 0:
            return im
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, w, h), radius=r, fill=255)
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.paste(im, (0, 0), mask)
        return out

    im = Image.open(png_path).convert("RGBA")
    try:
        resample = Image.Resampling.LANCZOS
    except AttributeError:
        resample = Image.LANCZOS  # type: ignore[attr-defined]
    # 先缩到 256，再用 Pillow 一次写入多尺寸 ICO（append_images 易只写出 16x16）
    im256 = im.resize((256, 256), resample)
    # 打包 exe 图标圆角（256 基准像素半径；比例约 27%，各嵌入尺寸随缩放保持观感一致）
    im256 = _round_corners_rgba(im256, 70)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    im256.save(ico_path, format="ICO", sizes=sizes)
    print(f"[build_app_icon] 已写入: {ico_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
