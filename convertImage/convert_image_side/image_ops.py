import os
from typing import List

from PIL import Image

from .constants import SUPPORTED_EXTS


def is_image_file(path: str) -> bool:
    return os.path.isfile(path) and path.lower().endswith(SUPPORTED_EXTS)


def collect_images_from_folder(folder: str) -> List[str]:
    paths = []
    for name in os.listdir(folder):
        p = os.path.join(folder, name)
        if is_image_file(p):
            paths.append(p)
    paths.sort()
    return paths


def parse_bg_color(text: str):
    """
    支持：
    - transparent / 空
    - #RRGGBB 或 #RRGGBBAA
    - R,G,B 或 R,G,B,A
    """
    s = (text or "").strip().lower()
    if s in ("transparent", "透明", ""):
        return (0, 0, 0, 0)

    if s.startswith("#"):
        hexs = s[1:]
        if len(hexs) == 6:
            r = int(hexs[0:2], 16)
            g = int(hexs[2:4], 16)
            b = int(hexs[4:6], 16)
            return (r, g, b, 255)
        if len(hexs) == 8:
            r = int(hexs[0:2], 16)
            g = int(hexs[2:4], 16)
            b = int(hexs[4:6], 16)
            a = int(hexs[6:8], 16)
            return (r, g, b, a)
        raise ValueError("Hex 颜色格式应为 #RRGGBB 或 #RRGGBBAA")

    parts = [p.strip() for p in s.split(",")]
    if len(parts) in (3, 4):
        vals = [int(x) for x in parts]
        if any(v < 0 or v > 255 for v in vals):
            raise ValueError("RGBA 每个通道应在 0~255")
        if len(vals) == 3:
            vals.append(255)
        return tuple(vals)

    raise ValueError("背景颜色格式不正确：用 transparent 或 #RRGGBB 或 R,G,B(,A)")


def crop_transparent_area(img: Image.Image, padding: int = 0) -> Image.Image:
    """
    按 alpha 通道裁切四周完全透明的区域，并可保留透明边距。
    如果图片没有非透明像素，则保持原图不变，避免得到空尺寸图片。
    """
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    alpha = img.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return img

    left, top, right, bottom = bbox
    pad = max(0, int(padding))
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(img.width, right + pad)
    bottom = min(img.height, bottom + pad)
    return img.crop((left, top, right, bottom))


def get_alpha_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return img.getchannel("A").getbbox()


def expand_bbox(
    bbox: tuple[int, int, int, int],
    width: int,
    height: int,
    padding: int = 0,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    pad = max(0, int(padding))
    return (
        max(0, left - pad),
        max(0, top - pad),
        min(width, right + pad),
        min(height, bottom + pad),
    )


def crop_with_bbox(img: Image.Image, bbox: tuple[int, int, int, int] | None) -> Image.Image:
    if bbox is None:
        return img
    left, top, right, bottom = bbox
    left = max(0, min(img.width, left))
    top = max(0, min(img.height, top))
    right = max(left, min(img.width, right))
    bottom = max(top, min(img.height, bottom))
    return img.crop((left, top, right, bottom))


def align_to_4(n: int, mode: str = "up") -> int:
    """把 n 对齐到 4 的倍数。mode: up / down / nearest"""
    if n <= 0:
        return 4
    r = n % 4
    if r == 0:
        return n
    if mode == "up":
        return n + (4 - r)
    if mode == "down":
        return max(4, n - r)
    down = max(4, n - r)
    up = n + (4 - r)
    return down if abs(n - down) <= abs(up - n) else up


def downscale_to_max_side(w: int, h: int, max_side: int) -> tuple[int, int, float]:
    """
    等比缩放到最长边=max_side（允许放大或缩小）。
    返回：base_w, base_h, pre_scale。
    """
    if max_side <= 0:
        return w, h, 1.0
    m = max(w, h)
    if m <= 0:
        return w, h, 1.0

    pre_scale = max_side / m
    base_w = max(1, int(round(w * pre_scale)))
    base_h = max(1, int(round(h * pre_scale)))
    return base_w, base_h, pre_scale


def compute_target_canvas(
    src_w: int,
    src_h: int,
    use_max_side: bool,
    max_side: int,
    allow_upscale: bool,
    use_align4: bool,
    align_mode: str,
    out_w: int,
    out_h: int,
) -> tuple[int, int, int, int, float]:
    """
    返回：
      canvas_w, canvas_h, base_w, base_h, pre_scale
    """
    if use_max_side:
        base_w, base_h, pre_scale = downscale_to_max_side(src_w, src_h, max_side)
    else:
        scale = min(out_w / src_w, out_h / src_h)
        if not allow_upscale:
            scale = min(scale, 1.0)
        base_w = max(1, int(round(src_w * scale)))
        base_h = max(1, int(round(src_h * scale)))
        pre_scale = scale

    if use_align4:
        canvas_w = align_to_4(base_w if use_max_side else out_w, align_mode)
        canvas_h = align_to_4(base_h if use_max_side else out_h, align_mode)
        return canvas_w, canvas_h, base_w, base_h, pre_scale

    return (
        base_w if use_max_side else out_w,
        base_h if use_max_side else out_h,
        base_w,
        base_h,
        pre_scale,
    )


def expand_image_to_canvas(
    img: Image.Image,
    canvas_w: int,
    canvas_h: int,
    allow_upscale: bool,
    bg_rgba=(0, 0, 0, 0),
) -> tuple[Image.Image, float, tuple[int, int]]:
    """
    在画布上居中贴入（等比缩放），返回：
    - expanded RGBA
    - scale_to_canvas（从输入 img 到贴入画布的缩放）
    - resized_size（贴入画布的尺寸）
    """
    w, h = img.size
    scale = min(canvas_w / w, canvas_h / h)
    if not allow_upscale:
        scale = min(scale, 1.0)

    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))

    resized = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (canvas_w, canvas_h), bg_rgba)
    offset = ((canvas_w - new_w) // 2, (canvas_h - new_h) // 2)
    canvas.paste(resized, offset, resized)

    return canvas, scale, (new_w, new_h)

