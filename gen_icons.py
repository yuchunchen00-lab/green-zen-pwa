#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_icons.py — 綠野仙蔬 PWA 圖示產生器
================================================

純程式繪製（無外部素材、無字型相依），一次產出 PWA / iOS / Windows
所需的完整圖示組，輸出至 ./icons/。

用法:
    pip install pillow
    python gen_icons.py                 # 產生全部圖示
    python gen_icons.py --out assets/ic # 自訂輸出資料夾
    python gen_icons.py --clean         # 先清空輸出資料夾再產生

產出內容:
    icons/icon-{72,96,128,144,152,180,192,256,384,512}.png   一般圖示（圓角）
    icons/maskable-{192,512}.png                             Android 可遮罩圖示（滿版 + 安全區）
    icons/apple-touch-icon.png                               iOS 主畫面（180x180，不透明方形）
    icons/favicon-{16,32,48}.png + favicon.ico               瀏覽器分頁圖示
    icons/shortcut-{dish,farm,hero}.png                      manifest shortcuts 用（96x96）
    icons/icon.svg                                           向量原稿（可無限放大）
    icons/og-cover.png                                       社群分享縮圖（1200x630）
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    sys.exit("找不到 Pillow，請先安裝：pip install pillow")


# --------------------------------------------------------------------------
# 品牌設定
# --------------------------------------------------------------------------

BRAND = {
    "grad_top": (16, 185, 129),    # #10b981 emerald-500
    "grad_bottom": (4, 95, 70),    # #045f46 emerald-800
    "leaf": (255, 255, 255),       # 葉片主體
    "vein": (16, 185, 129),        # 葉脈（疊在白葉上）
    "ink": (6, 78, 59),            # #064e3b emerald-900
}

# shortcut 圖示的配色變化
SHORTCUT_THEMES = {
    "dish": ((52, 211, 153), (5, 150, 105)),
    "farm": ((132, 204, 22), (63, 98, 18)),
    "hero": ((45, 212, 191), (15, 118, 110)),
}

SS = 4  # 超取樣倍率（先畫 4 倍大再縮小 = 平滑邊緣）


# --------------------------------------------------------------------------
# 繪圖工具
# --------------------------------------------------------------------------

def quad_bezier(p0, p1, p2, steps: int = 90):
    """二次貝茲曲線取樣，回傳點座標串列。"""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]
        y = u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    return pts


def vertical_gradient(size: int, top_rgb, bottom_rgb) -> Image.Image:
    """產生由上至下的線性漸層底圖。"""
    grad = Image.new("RGB", (1, size))
    px = grad.load()
    for y in range(size):
        t = y / max(size - 1, 1)
        px[0, y] = (
            round(top_rgb[0] + (bottom_rgb[0] - top_rgb[0]) * t),
            round(top_rgb[1] + (bottom_rgb[1] - top_rgb[1]) * t),
            round(top_rgb[2] + (bottom_rgb[2] - top_rgb[2]) * t),
        )
    return grad.resize((size, size), Image.Resampling.BICUBIC)


def rounded_mask(size: int, radius_ratio: float) -> Image.Image:
    """圓角方形遮罩；radius_ratio = 0 代表正方形滿版。"""
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    if radius_ratio <= 0:
        d.rectangle((0, 0, size - 1, size - 1), fill=255)
    else:
        d.rounded_rectangle(
            (0, 0, size - 1, size - 1),
            radius=int(size * radius_ratio),
            fill=255,
        )
    return mask


def leaf_polygon(cx: float, cy: float, scale: float):
    """
    以 (cx, cy) 為中心、scale 為邊長，產生一片由左下指向右上的葉子輪廓。
    座標以單位正方形 (0~1) 定義後再換算，方便等比縮放。
    """
    def pt(ux, uy):
        return (cx + (ux - 0.5) * scale, cy + (uy - 0.5) * scale)

    base = pt(0.16, 0.86)   # 葉柄端
    tip = pt(0.86, 0.14)    # 葉尖
    ctrl_upper = pt(0.18, 0.22)   # 上緣控制點（較飽滿）
    ctrl_lower = pt(0.80, 0.84)   # 下緣控制點

    outline = quad_bezier(base, ctrl_upper, tip)
    outline += quad_bezier(tip, ctrl_lower, base)[1:]
    return outline, base, tip


def draw_leaf(layer: Image.Image, cx, cy, scale, fill, vein_color):
    """在 RGBA 圖層上畫出葉柄 + 葉片主體 + 主脈 + 側脈。"""
    draw = ImageDraw.Draw(layer)
    outline, base, tip = leaf_polygon(cx, cy, scale)

    # 葉柄先畫，之後被葉身覆蓋接點，看起來才是連續的一筆
    stem_end = (base[0] - scale * 0.13, base[1] + scale * 0.11)
    draw.line([base, stem_end], fill=fill,
              width=max(2, int(scale * 0.055)))
    draw.polygon(outline, fill=fill)

    # 葉脈畫在獨立圖層，再用葉身輪廓（內縮）當遮罩，確保不會超出葉緣
    veins = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    vd = ImageDraw.Draw(veins)

    mid_ctrl = (
        base[0] + (tip[0] - base[0]) * 0.42 + scale * 0.07,
        base[1] + (tip[1] - base[1]) * 0.42 + scale * 0.07,
    )
    spine = quad_bezier(base, mid_ctrl, tip, steps=70)
    vd.line(spine, fill=vein_color, width=max(2, int(scale * 0.035)), joint="curve")

    vein_w = max(2, int(scale * 0.024))
    for frac in (0.26, 0.42, 0.58, 0.74):
        sx, sy = spine[int(len(spine) * frac)]
        reach = scale * 0.34 * (1 - frac * 0.55)
        end = (sx - reach * 0.88, sy - reach * 0.66)
        ctrl = (sx - reach * 0.26, sy - reach * 0.56)
        vd.line(quad_bezier((sx, sy), ctrl, end, steps=24),
                fill=vein_color, width=vein_w, joint="curve")

    clip = Image.new("L", layer.size, 0)
    ImageDraw.Draw(clip).polygon(
        leaf_polygon(cx, cy, scale * 0.96)[0], fill=255)
    veins.putalpha(Image.composite(veins.getchannel("A"), clip, clip))
    layer.alpha_composite(veins)


def render_icon(size: int, *, radius_ratio: float = 0.22,
                leaf_scale: float = 0.62, theme=None,
                opaque: bool = False) -> Image.Image:
    """渲染單張圖示。leaf_scale 為葉片佔畫布的比例。"""
    top, bottom = theme or (BRAND["grad_top"], BRAND["grad_bottom"])
    work = size * SS

    canvas = vertical_gradient(work, top, bottom).convert("RGBA")

    # 右下角的大片半透明葉影，呼應網頁 hero 的裝飾
    shadow = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.polygon(leaf_polygon(work * 0.82, work * 0.84, work * 0.72)[0],
               fill=(255, 255, 255, 28))
    canvas = Image.alpha_composite(canvas, shadow)

    # 主葉片
    layer = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    draw_leaf(layer, work / 2, work / 2, work * leaf_scale,
              BRAND["leaf"], top)
    canvas = Image.alpha_composite(canvas, layer)

    # 套用圓角
    canvas.putalpha(rounded_mask(work, radius_ratio))
    icon = canvas.resize((size, size), Image.Resampling.LANCZOS)

    if opaque:  # iOS 不支援透明，直接壓在品牌底色上
        flat = Image.new("RGB", (size, size), BRAND["ink"])
        flat.paste(icon, (0, 0), icon)
        return flat
    return icon


# --------------------------------------------------------------------------
# SVG 原稿（與 PNG 同一套幾何，方便日後設計師接手）
# --------------------------------------------------------------------------

SVG_SOURCE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img"
     aria-label="綠野仙蔬 Green Zen Bistro">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#10b981"/>
      <stop offset="100%" stop-color="#045f46"/>
    </linearGradient>
    <clipPath id="round"><rect width="512" height="512" rx="113" ry="113"/></clipPath>
  </defs>
  <g clip-path="url(#round)">
    <rect width="512" height="512" fill="url(#bg)"/>
    <path d="M330 492 Q245 388 507 309 Q585 452 330 492 Z" fill="#ffffff" opacity="0.11"/>
    <g transform="translate(256 256) scale(3.17) translate(-32 -32)">
      <path d="M12.6 61.1 Q13.2 15.6 59.5 11.3 Q63.9 56.6 12.6 61.1 Z" fill="#ffffff"/>
      <path d="M12.6 61.1 Q40.5 38.4 59.5 11.3" stroke="#10b981" stroke-width="2.2"
            fill="none" stroke-linecap="round"/>
      <g stroke="#10b981" stroke-width="1.4" fill="none" stroke-linecap="round">
        <path d="M33.6 40.2 Q28.3 35.0 22.9 33.4"/>
        <path d="M40.3 32.4 Q36.1 28.2 31.6 26.9"/>
        <path d="M46.6 25.1 Q43.3 21.9 39.6 20.8"/>
      </g>
      <path d="M12.6 61.1 L6.2 66.9" stroke="#ffffff" stroke-width="3.2" stroke-linecap="round"/>
    </g>
  </g>
</svg>
"""


# --------------------------------------------------------------------------
# 社群分享縮圖
# --------------------------------------------------------------------------

def render_og_cover(width: int = 1200, height: int = 630) -> Image.Image:
    """1200x630 的 Open Graph 封面圖（漸層 + 葉片構圖）。"""
    grad = vertical_gradient(max(width, height),
                             BRAND["grad_top"], BRAND["grad_bottom"])
    cover = grad.resize((width, height), Image.Resampling.BICUBIC).convert("RGBA")

    deco = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    dd.polygon(leaf_polygon(width * 0.86, height * 0.78, height * 1.15)[0],
               fill=(255, 255, 255, 26))
    dd.polygon(leaf_polygon(width * 0.12, height * 0.18, height * 0.70)[0],
               fill=(255, 255, 255, 18))
    cover = Image.alpha_composite(cover, deco)

    badge = render_icon(260, radius_ratio=0.24)
    cover.paste(badge, (int(width * 0.08), int(height / 2 - 130)), badge)
    return cover.convert("RGB")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

STANDARD_SIZES = [72, 96, 128, 144, 152, 180, 192, 256, 384, 512]
FAVICON_SIZES = [16, 32, 48]


def main() -> int:
    ap = argparse.ArgumentParser(description="產生綠野仙蔬 PWA 圖示組")
    ap.add_argument("--out", default="icons", help="輸出資料夾（預設: icons）")
    ap.add_argument("--clean", action="store_true", help="產生前先清空輸出資料夾")
    args = ap.parse_args()

    out = Path(args.out)
    if args.clean and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    made: list[tuple[str, int]] = []

    def save(img: Image.Image, name: str, **kw):
        path = out / name
        img.save(path, **kw)
        made.append((name, path.stat().st_size))

    # 1) 一般圖示（圓角、透明外圍）
    for s in STANDARD_SIZES:
        save(render_icon(s), f"icon-{s}.png", optimize=True)

    # 2) Android maskable：滿版方形 + 葉片縮小至安全區（約 60%）
    for s in (192, 512):
        save(render_icon(s, radius_ratio=0, leaf_scale=0.46),
             f"maskable-{s}.png", optimize=True)

    # 3) iOS 主畫面圖示：不透明、圓角交給系統
    save(render_icon(180, radius_ratio=0, opaque=True),
         "apple-touch-icon.png", optimize=True)

    # 4) favicon
    for s in FAVICON_SIZES:
        save(render_icon(s, radius_ratio=0.18, leaf_scale=0.74),
             f"favicon-{s}.png", optimize=True)
    ico_base = render_icon(256, radius_ratio=0.18, leaf_scale=0.74)
    ico_path = out / "favicon.ico"
    ico_base.save(ico_path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    made.append(("favicon.ico", ico_path.stat().st_size))

    # 5) manifest shortcuts 圖示
    for key, theme in SHORTCUT_THEMES.items():
        save(render_icon(96, radius_ratio=0.24, theme=theme),
             f"shortcut-{key}.png", optimize=True)

    # 6) 向量原稿
    svg_path = out / "icon.svg"
    svg_path.write_text(SVG_SOURCE, encoding="utf-8")
    made.append(("icon.svg", svg_path.stat().st_size))

    # 7) 社群分享縮圖
    save(render_og_cover(), "og-cover.png", optimize=True, quality=90)

    total = sum(size for _, size in made)
    print(f"\n✅ 已輸出 {len(made)} 個檔案至 {out.resolve()}\n")
    for name, size in made:
        print(f"   {name:<26} {size / 1024:7.1f} KB")
    print(f"\n   {'合計':<26} {total / 1024:7.1f} KB\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
