from dataclasses import dataclass
from typing import Optional, Tuple

from PIL import Image


@dataclass
class ImageTask:
    src_path: str
    src_size: Tuple[int, int] = (0, 0)
    alpha_bbox: Optional[Tuple[int, int, int, int]] = None
    content_size: Tuple[int, int] = (0, 0)

    # 预缩放尺寸（对齐4之前）
    base_size: Tuple[int, int] = (0, 0)
    pre_scale: float = 1.0

    # 画布尺寸（对齐4之后）
    canvas_size: Tuple[int, int] = (0, 0)

    # 贴入画布时缩放（一般=1，除非 allow_upscale/固定尺寸等导致）
    scale_to_canvas: float = 1.0
    resized_size: Tuple[int, int] = (0, 0)

    preview_pil: Optional[Image.Image] = None

