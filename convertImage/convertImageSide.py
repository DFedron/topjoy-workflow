import os
import queue
import threading
import tempfile
import asyncio
from dataclasses import dataclass
from typing import Optional, List, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox

import os, sys, json, datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from email.utils import parsedate_to_datetime
from PIL import Image, ImageTk

# ---- 可选：拖拽支持 ----
DND_OK = False
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_OK = True
except Exception:
    TkinterDnD = None
    DND_FILES = None

# ---- 可选：Tinify 压缩模块（同目录：tinify_async_compress.py）----
TINIFY_OK = False
try:
    from tinify_async_compress import TinifyAsyncCompressor, Config, TinyReqMode, CompressResult
    TINIFY_OK = True
except Exception:
    TINIFY_OK = False

SUPPORTED_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga")
PREVIEW_SIZE = 360

# ---------------- PyInstaller resource helper ----------------
def resource_path(relative_path: str) -> str:
    """兼容 PyInstaller：开发环境=脚本目录；打包后=_MEIPASS"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)  # type: ignore[attr-defined]
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def set_window_icon_png(window: tk.Tk, png_name: str = "app.png"):
    """用 PNG 设置窗口图标（标题栏/任务栏），兼容 PyInstaller"""
    icon_path = resource_path(png_name)
    try:
        icon_img = tk.PhotoImage(file=icon_path)
        window.iconphoto(True, icon_img)
        # 保留引用，避免被 GC 回收导致图标失效
        window._icon_img_ref = icon_img  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[WARN] 设置窗口图标失败: {icon_path} -> {e}")

def get_network_utc_time(timeout=3) -> datetime.datetime:
    """
    通过 HTTP Date 头获取网络 UTC 时间（不依赖本机时间）
    依次尝试多个站点，提升成功率
    """
    urls = [
        "https://www.google.com/generate_204",
        "https://www.cloudflare.com",
        "https://www.microsoft.com",
    ]
    last_err = None
    for url in urls:
        try:
            req = Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=timeout) as resp:
                date_str = resp.headers.get("Date")
                if not date_str:
                    continue
                dt = parsedate_to_datetime(date_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                return dt.astimezone(datetime.timezone.utc)
        except (URLError, HTTPError, TimeoutError) as e:
            last_err = e
            continue
    raise RuntimeError(f"Failed to get network time: {last_err}")

def _license_cache_path(app_name="atlas_packer") -> str:
    # 放到用户目录，避免被打包路径影响
    base = os.path.join(os.path.expanduser("~"), f".{app_name}")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "time_cache.json")


def _settings_path(app_name="convertImageSide") -> str:
    base = os.path.join(os.path.expanduser("~"), f".{app_name}")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "settings.json")


def load_settings(app_name="convertImageSide") -> dict:
    p = _settings_path(app_name)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_settings(data: dict, app_name="convertImageSide"):
    p = _settings_path(app_name)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, indent=2)
    except Exception:
        pass

def load_cached_network_time(app_name="atlas_packer") -> datetime.datetime | None:
    p = _license_cache_path(app_name)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        # ISO string in UTC
        return datetime.datetime.fromisoformat(obj["last_network_utc"]).astimezone(datetime.timezone.utc)
    except Exception:
        return None

def save_cached_network_time(dt_utc: datetime.datetime, app_name="atlas_packer"):
    p = _license_cache_path(app_name)
    obj = {"last_network_utc": dt_utc.astimezone(datetime.timezone.utc).isoformat()}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def check_expired_or_exit(root, expire_utc: datetime.datetime, app_name="atlas_packer", offline_mode="strict"):
    """
    offline_mode:
      - "strict": 无法获取网络时间就禁止启动（最符合你“不能打开软件”）
      - "cache": 断网时用缓存网络时间判断；没缓存则禁止
    """
    import tkinter.messagebox as mb

    try:
        now_utc = get_network_utc_time()
        # 防回拨：网络时间也缓存下来，下次断网还能判断
        save_cached_network_time(now_utc, app_name=app_name)
    except Exception:
        if offline_mode == "cache":
            cached = load_cached_network_time(app_name=app_name)
            if cached is None:
                mb.showerror("错误", "无网络，软件无法启动。")
                root.destroy()
                sys.exit(0)
            now_utc = cached
        else:
            mb.showerror("错误", "无网络，软件无法启动。")
            root.destroy()
            sys.exit(0)

    if now_utc >= expire_utc:
        mb.showerror("已过期", f"软件已过期。\n请联系管理员更新。")
        root.destroy()
        sys.exit(0)


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
    # nearest
    down = max(4, n - r)
    up = n + (4 - r)
    return down if abs(n - down) <= abs(up - n) else up


def downscale_to_max_side(w: int, h: int, max_side: int) -> tuple[int, int, float]:
    """
    等比缩放到最长边=max_side（允许放大或缩小）
    返回：base_w, base_h, pre_scale
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
    语义：
      - base_w/base_h：对齐4之前的“预缩放尺寸”
      - canvas_w/canvas_h：对齐4后的画布尺寸（允许非正方形）
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
    bg_rgba=(0, 0, 0, 0)
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


@dataclass
class ImageTask:
    src_path: str
    src_size: Tuple[int, int] = (0, 0)

    # 预缩放尺寸（对齐4之前）
    base_size: Tuple[int, int] = (0, 0)
    pre_scale: float = 1.0

    # 画布尺寸（对齐4之后）
    canvas_size: Tuple[int, int] = (0, 0)

    # 贴入画布时缩放（一般=1，除非 allow_upscale/固定尺寸等导致）
    scale_to_canvas: float = 1.0
    resized_size: Tuple[int, int] = (0, 0)

    preview_pil: Optional[Image.Image] = None


RootBase = TkinterDnD.Tk if DND_OK else tk.Tk


class App(RootBase):
    def __init__(self):
        super().__init__()
        self.title("convertImageSide")
        self.geometry("900x1000")

        self.tasks: List[ImageTask] = []
        self.task_index: dict[str, int] = {}

        # ---- 输出 ----
        self.output_dir = tk.StringVar(value="")
        self.suffix = tk.StringVar(value="")
        self.overwrite = tk.BooleanVar(value=False)

        # ---- 背景 & 放大 ----
        self.bg = tk.StringVar(value="transparent")
        self.allow_upscale = tk.BooleanVar(value=False)

        # ---- 固定宽高（当不用 max_side 时才作为目标）----
        self.out_w = tk.StringVar(value="512")
        self.out_h = tk.StringVar(value="512")

        # ---- 新增：预缩放 max_side（默认 1024）----
        self.use_max_side = tk.BooleanVar(value=True)
        self.max_side = tk.StringVar(value="512")

        # ---- 对齐4 ----
        self.use_align4 = tk.BooleanVar(value=True)
        self.align4_mode = tk.StringVar(value="nearest")  # 推荐 up，保证满足 %4==0

        # ---- Tinify ----
        self.enable_compress = tk.BooleanVar(value=True)
        self.tinify_key = tk.StringVar(value=os.environ.get("TINIFY_API_KEY", ""))
        self.concurrency = tk.StringVar(value="2")

        # ---- 日志/线程 ----
        self._stop_flag = threading.Event()
        self._worker_thread = None
        self._log_queue = queue.Queue()

        self._preview_tk = None

        self._load_settings()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if DND_OK:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self.on_drop)

        self.after(80, self._drain_log)
        self._refresh_output_dir_state()

    # ---------------- UI ----------------

    def _build_ui(self):
        pad = 8

        top = tk.Frame(self)
        top.pack(fill="x", padx=pad, pady=pad)

        # 输出行
        row1 = tk.Frame(top)
        row1.pack(fill="x", pady=2)
        tk.Checkbutton(row1, text="原路径原名覆盖", variable=self.overwrite,
                       command=self._refresh_output_dir_state).pack(side="left")
        tk.Label(row1, text="输出文件夹:", width=12, anchor="w").pack(side="left", padx=(10, 0))
        self.out_entry = tk.Entry(row1, textvariable=self.output_dir)
        self.out_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.out_btn = tk.Button(row1, text="选择...", command=self.pick_output_dir)
        self.out_btn.pack(side="left")
        tk.Label(row1, text="后缀:").pack(side="left", padx=(10, 0))
        tk.Entry(row1, textvariable=self.suffix, width=10).pack(side="left")

        # 参数行（预缩放 + 对齐4）
        row2 = tk.Frame(top)
        row2.pack(fill="x", pady=(6, 2))

        tk.Checkbutton(row2, text="最大尺寸（最长边= max_side）", variable=self.use_max_side,
                       command=self.rebuild_all_tasks).pack(side="left")
        tk.Label(row2, text="max_side:").pack(side="left", padx=(8, 0))
        tk.Entry(row2, textvariable=self.max_side, width=8).pack(side="left")
        # tk.Label(row2, text="(默认 1024)").pack(side="left", padx=(6, 18))

        tk.Checkbutton(row2, text="对齐到 4 的倍数（BC7/GPU block）", variable=self.use_align4,
                       command=self.rebuild_all_tasks).pack(side="left")
        tk.Label(row2, text="模式:").pack(side="left", padx=(8, 0))
        tk.OptionMenu(row2, self.align4_mode, "up", "nearest", "down",
                      command=lambda _=None: self.rebuild_all_tasks()).pack(side="left")
        # tk.Label(row2, text="(推荐 up)").pack(side="left", padx=(6, 0))

        # 参数行（背景/放大/固定宽高备用）
        row3 = tk.Frame(top)
        row3.pack(fill="x", pady=2)

        tk.Checkbutton(row3, text="允许放大小图", variable=self.allow_upscale,
                       command=self.rebuild_all_tasks).pack(side="left")

        # tk.Label(row3, text="背景:").pack(side="left", padx=(14, 0))
        # tk.Entry(row3, textvariable=self.bg, width=18).pack(side="left", padx=(0, 10))
        # tk.Label(row3, text="transparent / #RRGGBB / R,G,B").pack(side="left", padx=(0, 16))

        tk.Label(row3, text="固定输出宽:").pack(side="left")
        tk.Entry(row3, textvariable=self.out_w, width=8).pack(side="left")
        tk.Label(row3, text="高:").pack(side="left")
        tk.Entry(row3, textvariable=self.out_h, width=8).pack(side="left")
        tk.Button(row3, text="应用到全部(重算预览)", command=self.rebuild_all_tasks).pack(side="left", padx=8)
        tk.Label(row3, text="(当关闭 max_side 时使用)").pack(side="left", padx=(8, 0))

        # Tinify 行
        row4 = tk.Frame(top)
        row4.pack(fill="x", pady=(6, 2))
        tk.Checkbutton(row4, text="启用 TinyPNG 压缩", variable=self.enable_compress).pack(side="left")
        # tk.Label(row4, text="Tinify Key:").pack(side="left", padx=(12, 6))
        # tk.Entry(row4, textvariable=self.tinify_key, width=56).pack(side="left", fill="x", expand=True)
        # tk.Label(row4, text="并发:").pack(side="left", padx=(10, 6))
        # tk.Entry(row4, textvariable=self.concurrency, width=6).pack(side="left")
        if not TINIFY_OK:
            tk.Label(row4, text="(未找到 tinify_async_compress.py，无法压缩)", fg="#b00").pack(side="left", padx=8)

        # 中部：列表 + 预览
        mid = tk.Frame(self)
        mid.pack(fill="both", expand=True, padx=pad, pady=(0, pad))

        left = tk.Frame(mid, width=380)
        left.pack(side="left", fill="y")

        right = tk.Frame(mid)
        right.pack(side="right", fill="both", expand=True)

        # 左侧按钮
        tk.Label(left, text="任务列表（可多选/文件夹/拖拽）").pack(anchor="w")
        btnrow = tk.Frame(left)
        btnrow.pack(fill="x", pady=4)
        tk.Button(btnrow, text="添加图片(多选)", command=self.add_files).pack(side="left", fill="x", expand=True)
        tk.Button(btnrow, text="添加文件夹", command=self.add_folder).pack(side="left", fill="x", expand=True, padx=6)

        self.listbox = tk.Listbox(left, height=18)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select_task)

        btnrow2 = tk.Frame(left)
        btnrow2.pack(fill="x", pady=6)
        tk.Button(btnrow2, text="移除选中", command=self.remove_selected).pack(side="left", fill="x", expand=True)
        tk.Button(btnrow2, text="清空", command=self.clear_tasks).pack(side="left", fill="x", expand=True, padx=(6, 0))

        # 右侧预览
        tk.Label(right, text="扩图预览").pack(anchor="w")
        self.preview_label = tk.Label(right, bd=1, relief="solid")
        self.preview_label.pack(pady=6)

        self.info_label = tk.Label(right, text="", justify="left")
        self.info_label.pack(anchor="w")

        # 底部：操作 + 日志
        bottom = tk.Frame(self)
        bottom.pack(fill="x", padx=pad, pady=(0, pad))

        ctrl = tk.Frame(bottom)
        ctrl.pack(fill="x")
        tk.Button(ctrl, text="开始处理", height=2, command=self.start_run).pack(side="left")
        tk.Button(ctrl, text="停止", height=2, command=self.stop_run).pack(side="left", padx=8)
        tk.Button(ctrl, text="重建选中预览", command=self.rebuild_selected_preview).pack(side="left", padx=8)
        tk.Button(ctrl, text="重建全部预览", command=self.rebuild_all_tasks).pack(side="left", padx=8)

        self.log_text = tk.Text(bottom, height=8)
        self.log_text.pack(fill="both", expand=True, pady=(6, 0))

        # 提示
        self.log("预览=扩图后的效果（不压缩）；Tinify 仅最终输出时执行。")
        if DND_OK:
            self.log("拖拽已启用：把图片拖到窗口里即可添加。")
        else:
            self.log("拖拽未启用：如需拖拽请安装 tkinterdnd2。")

    def _refresh_output_dir_state(self):
        if self.overwrite.get():
            self.out_entry.configure(state="disabled")
            self.out_btn.configure(state="disabled")
        else:
            self.out_entry.configure(state="normal")
            self.out_btn.configure(state="normal")

    def _load_settings(self):
        cfg = load_settings()
        if not cfg:
            return
        self.output_dir.set(cfg.get("output_dir", self.output_dir.get()))
        self.suffix.set(cfg.get("suffix", self.suffix.get()))
        self.overwrite.set(bool(cfg.get("overwrite", self.overwrite.get())))
        self.bg.set(cfg.get("bg", self.bg.get()))
        self.allow_upscale.set(bool(cfg.get("allow_upscale", self.allow_upscale.get())))
        self.out_w.set(cfg.get("out_w", self.out_w.get()))
        self.out_h.set(cfg.get("out_h", self.out_h.get()))
        self.use_max_side.set(bool(cfg.get("use_max_side", self.use_max_side.get())))
        self.max_side.set(cfg.get("max_side", self.max_side.get()))
        self.use_align4.set(bool(cfg.get("use_align4", self.use_align4.get())))
        self.align4_mode.set(cfg.get("align4_mode", self.align4_mode.get()))
        self.enable_compress.set(bool(cfg.get("enable_compress", self.enable_compress.get())))
        self.tinify_key.set(cfg.get("tinify_key", self.tinify_key.get()))
        self.concurrency.set(cfg.get("concurrency", self.concurrency.get()))

    def _save_settings(self):
        data = {
            "output_dir": self.output_dir.get(),
            "suffix": self.suffix.get(),
            "overwrite": bool(self.overwrite.get()),
            "bg": self.bg.get(),
            "allow_upscale": bool(self.allow_upscale.get()),
            "out_w": self.out_w.get(),
            "out_h": self.out_h.get(),
            "use_max_side": bool(self.use_max_side.get()),
            "max_side": self.max_side.get(),
            "use_align4": bool(self.use_align4.get()),
            "align4_mode": self.align4_mode.get(),
            "enable_compress": bool(self.enable_compress.get()),
            "tinify_key": self.tinify_key.get(),
            "concurrency": self.concurrency.get(),
        }
        save_settings(data)

    def _on_close(self):
        self._save_settings()
        self.destroy()

    # ---------------- logging ----------------

    def log(self, msg: str):
        self._log_queue.put(msg)

    def _drain_log(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
        except queue.Empty:
            pass
        self.after(80, self._drain_log)

    # ---------------- task ops ----------------

    def pick_output_dir(self):
        p = filedialog.askdirectory(title="选择输出文件夹")
        if p:
            self.output_dir.set(p)
            self.log(f"输出目录：{p}")

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择图片（可多选）",
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tga")]
        )
        for p in paths:
            self.add_task(p)

    def add_folder(self):
        folder = filedialog.askdirectory(title="选择文件夹（添加里面的图片）")
        if not folder:
            return
        for p in collect_images_from_folder(folder):
            self.add_task(p)

    def on_drop(self, event):
        files = self.tk.splitlist(event.data)
        for f in files:
            f = f.strip("{}")
            if is_image_file(f):
                self.add_task(f)

    def add_task(self, path: str):
        path = os.path.abspath(path)
        if path in self.task_index:
            return
        try:
            img = Image.open(path)
            w, h = img.size
        except Exception as e:
            self.log(f"[跳过] 读取失败: {path} ({e})")
            return

        task = ImageTask(src_path=path, src_size=(w, h))
        self._recompute_task(task)

        self.tasks.append(task)
        self.task_index[path] = len(self.tasks) - 1
        self.listbox.insert("end", os.path.basename(path))

        # 自动选中并显示
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set("end")
        self.listbox.event_generate("<<ListboxSelect>>")

    def clear_tasks(self):
        self.tasks.clear()
        self.task_index.clear()
        self.listbox.delete(0, "end")
        self.preview_label.config(image="")
        self.info_label.config(text="")
        self._preview_tk = None

    def remove_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        del self.tasks[idx]
        self.listbox.delete(idx)

        self.task_index.clear()
        for i, t in enumerate(self.tasks):
            self.task_index[t.src_path] = i

        self.preview_label.config(image="")
        self.info_label.config(text="")
        self._preview_tk = None

    def _retain_failed_tasks(self, failed_paths: set[str]):
        if not self.tasks:
            return
        kept = [t for t in self.tasks if t.src_path in failed_paths]
        self.tasks = kept
        self.task_index = {t.src_path: i for i, t in enumerate(self.tasks)}

        self.listbox.delete(0, "end")
        for t in self.tasks:
            self.listbox.insert("end", os.path.basename(t.src_path))

        if self.tasks:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self.on_select_task(None)
        else:
            self.preview_label.config(image="")
            self.info_label.config(text="")
            self._preview_tk = None

    # ---------------- recompute/preview ----------------

    def _get_int(self, s: str, default: int) -> int:
        try:
            v = int(str(s).strip())
            return v if v > 0 else default
        except Exception:
            return default

    def _recompute_task(self, task: ImageTask):
        ow = self._get_int(self.out_w.get(), 512)
        oh = self._get_int(self.out_h.get(), 512)
        ms = self._get_int(self.max_side.get(), 1024)

        bg = parse_bg_color(self.bg.get())
        allow_up = bool(self.allow_upscale.get())

        cw, ch, bw, bh, pre_scale = compute_target_canvas(
            task.src_size[0], task.src_size[1],
            use_max_side=self.use_max_side.get(),
            max_side=ms,
            allow_upscale=allow_up,
            use_align4=self.use_align4.get(),
            align_mode=self.align4_mode.get(),
            out_w=ow,
            out_h=oh
        )
        task.base_size = (bw, bh)
        task.pre_scale = pre_scale
        task.canvas_size = (cw, ch)

        # 为保证“预览与最终一致”：预览也先做 pre-scale resize，再贴入 canvas
        try:
            src_img = Image.open(task.src_path).convert("RGBA")

            # 先预缩放到 base_size（允许放大或缩小）
            if (bw, bh) != task.src_size:
                src_img = src_img.resize((bw, bh), Image.LANCZOS)

            expanded, scale_to_canvas, resized_size = expand_image_to_canvas(
                src_img, cw, ch, allow_up, bg
            )
            task.scale_to_canvas = scale_to_canvas
            task.resized_size = resized_size

            preview = expanded.copy()
            preview.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.LANCZOS)
            task.preview_pil = preview
        except Exception as e:
            task.preview_pil = None
            task.scale_to_canvas = 1.0
            task.resized_size = (0, 0)
            self.log(f"[预览失败] {os.path.basename(task.src_path)}: {e}")

    def rebuild_all_tasks(self):
        if not self.tasks:
            return
        for t in self.tasks:
            self._recompute_task(t)
        self.log("已重算全部任务的尺寸与预览。")
        self.rebuild_selected_preview()

    def rebuild_selected_preview(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self._recompute_task(self.tasks[idx])
        self.on_select_task(None)

    def on_select_task(self, _):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        t = self.tasks[idx]
        if t.preview_pil is None:
            self.preview_label.config(image="")
            self.info_label.config(text="预览不可用")
            self._preview_tk = None
            return

        self._preview_tk = ImageTk.PhotoImage(t.preview_pil)
        self.preview_label.config(image=self._preview_tk)

        sw, sh = t.src_size
        cw, ch = t.canvas_size
        total_scale = t.pre_scale * t.scale_to_canvas

        self.info_label.config(
            text=(
                f"文件: {os.path.basename(t.src_path)}\n"
                f"变化前: {sw} x {sh}\n"
                f"变化后: {cw} x {ch}\n"
                f"缩放: {total_scale:.4f}"
            )
        )

    # ---------------- output path ----------------

    def _resolve_output_path(self, src_path: str) -> str:
        if self.overwrite.get():
            return src_path

        out_dir = self.output_dir.get().strip()
        if not out_dir:
            raise ValueError("未勾选覆盖时，必须选择输出文件夹。")

        suffix = (self.suffix.get().strip() or "")
        base = os.path.splitext(os.path.basename(src_path))[0]
        return os.path.join(out_dir, f"{base}{suffix}.png")

    # ---------------- run ----------------

    def start_run(self):
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showwarning("提示", "正在处理中，请先停止或等待完成。")
            return

        if not self.tasks:
            messagebox.showerror("出错", "没有任务。请添加图片/文件夹或拖拽图片进窗口。")
            return

        if self.enable_compress.get():
            if not TINIFY_OK:
                messagebox.showerror("出错", "未找到 tinify_async_compress.py，无法启用压缩。")
                return
            # key = self.tinify_key.get().strip()
            # if not key:
            #     messagebox.showerror("出错", "启用压缩需要 Tinify API Key（或设置环境变量 TINIFY_API_KEY）。")
            #     return

        self._stop_flag.clear()
        self._worker_thread = threading.Thread(target=self._worker_main, daemon=True)
        self._worker_thread.start()

    def stop_run(self):
        self._stop_flag.set()
        self.log("收到停止请求：将尽快停止（当前步骤结束后停止）。")

    def _worker_main(self):
        try:
            bg_rgba = parse_bg_color(self.bg.get())
            allow_upscale = bool(self.allow_upscale.get())
            do_compress = bool(self.enable_compress.get())
            tinify_key = self.tinify_key.get().strip()

            concurrency = self._get_int(self.concurrency.get(), 4)

            # 确保参数一致（最终输出与预览同一策略）
            for t in self.tasks:
                self._recompute_task(t)

            # 1) 不压缩：逐个输出 expanded
            if not do_compress:
                ok = 0
                total = len(self.tasks)
                for i, t in enumerate(self.tasks, 1):
                    if self._stop_flag.is_set():
                        self.log("已停止。")
                        break

                    out_path = self._resolve_output_path(t.src_path)
                    self._final_expand_and_save(t, out_path, bg_rgba, allow_upscale)
                    ok += 1
                    self.log(f"[{i}/{total}] OK -> {out_path}")

                self._show_info_threadsafe("完成", f"处理完成：{ok}/{total}")
                return

            # 2) 压缩：先生成临时 expanded，再 Tinify 压缩到最终输出
            prepared = []
            total = len(self.tasks)

            for i, t in enumerate(self.tasks, 1):
                if self._stop_flag.is_set():
                    self.log("已停止（在开始压缩前停止）。")
                    break

                out_path = self._resolve_output_path(t.src_path)

                td = tempfile.TemporaryDirectory()
                tmp_in = os.path.join(td.name, "expanded.png")

                self._final_expand_and_save(t, tmp_in, bg_rgba, allow_upscale)
                prepared.append((td, tmp_in, out_path, t.src_path))
                self.log(f"[准备 {i}/{total}] expanded -> {tmp_in}")

            if not prepared:
                self._show_info_threadsafe("完成", "没有需要压缩的任务。")
                return

            async def _run_batch():
                input_to_src = {tmp_in: src_path for (_, tmp_in, _, src_path) in prepared}
                cfg = Config(
                    tinyReqMode=TinyReqMode.WEB,   # ✅ 用你之前的 WEB 模式
                    mail="api",                    # WEB 模式这两个字段未必用得上，但保留
                    key=tinify_key,                # 如果你的 WEB 模式不需要 key，也可以留空
                    concurrency=concurrency,
                    retries=3
                )

                # 可选：如果你想在 UI 上显示状态，你需要先在 UI 里放一个 status label
                # 这里我用 log 输出，如果你有 self.status_label，就改成 self.after(...) 更新它
                def on_finished(res: CompressResult):
                    src = input_to_src.get(res.input_path, res.input_path)
                    self.log(f"[Tinify OK] {os.path.basename(src)} ({res.size} bytes)")

                def on_error(res: CompressResult):
                    src = input_to_src.get(res.input_path, res.input_path)
                    self.log(f"[Tinify ERR] {os.path.basename(src)} -> {res.errmsg}")

                async with TinifyAsyncCompressor(cfg, on_finished=on_finished, on_error=on_error) as comp:
                    sem = asyncio.Semaphore(concurrency)

                    async def _one(tmp_in: str, out_path: str, src_path: str):
                        if self._stop_flag.is_set():
                            raise asyncio.CancelledError()
                        async with sem:
                            if self._stop_flag.is_set():
                                raise asyncio.CancelledError()
                            res = await comp.compress_one(tmp_in, out_path)
                            if not res.ok:
                                raise RuntimeError(f"{os.path.basename(src_path)} -> {res.errmsg}")
                            return res

                    tasks = [
                        asyncio.create_task(_one(tmp_in, out_path, src_path))
                        for (_, tmp_in, out_path, src_path) in prepared
                    ]

                    async def _watch_stop():
                        stop_logged = False
                        while True:
                            if all(t.done() for t in tasks):
                                return
                            if self._stop_flag.is_set():
                                if not stop_logged:
                                    self.log("收到停止请求：正在取消压缩任务...")
                                    stop_logged = True
                                for t in tasks:
                                    t.cancel()
                                return
                            await asyncio.sleep(0.2)

                    watcher = asyncio.create_task(_watch_stop())
                    try:
                        return await asyncio.gather(*tasks, return_exceptions=True)
                    finally:
                        watcher.cancel()
            self.log("开始 Tinify 批量压缩（最后一步）...")
            results = asyncio.run(_run_batch())

            ok = 0
            failed_paths = {t.src_path for t in self.tasks}
            stop_logged = False
            for idx, r in enumerate(results):
                if isinstance(r, asyncio.CancelledError):
                    if not stop_logged:
                        self.log("[Tinify STOP] 已取消剩余压缩任务。")
                        stop_logged = True
                elif isinstance(r, Exception):
                    self.log(f"[Tinify ERR] {r}")
                else:
                    ok += 1
                    self.log(f"[Tinify OK] {r.output_path} ({r.size} bytes)")
                    failed_paths.discard(prepared[idx][3])

            for td, *_ in prepared:
                try:
                    td.cleanup()
                except Exception:
                    pass

            if failed_paths:
                failed_names = ", ".join(sorted(os.path.basename(p) for p in failed_paths))
                self.log(f"[Tinify FAIL LIST] {failed_names}")
            else:
                self.log("[Tinify FAIL LIST] 无")

            self.after(0, lambda: self._retain_failed_tasks(failed_paths))
            self._show_info_threadsafe("完成", f"压缩完成：{ok}/{len(results)}")

        except Exception as e:
            self.log(f"[ERR] {e}")
            self._show_error_threadsafe("出错", str(e))

    def _final_expand_and_save(self, task: ImageTask, out_path: str, bg_rgba, allow_upscale: bool):
        """
        最终输出与预览一致：
          1) 读原图
          2) 先预缩放到 base_size
          3) 再贴入对齐后的 canvas_size
          4) 保存 expanded（如启用压缩则它是 tmp_in）
        """
        src_img = Image.open(task.src_path).convert("RGBA")

        bw, bh = task.base_size
        if (bw, bh) != task.src_size:
            # 与预览一致的 pre-scale
            src_img = src_img.resize((bw, bh), Image.LANCZOS)

        cw, ch = task.canvas_size
        expanded, _, _ = expand_image_to_canvas(src_img, cw, ch, allow_upscale, bg_rgba)

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        expanded.save(out_path)

    def _show_info_threadsafe(self, title, msg):
        self.after(0, lambda: messagebox.showinfo(title, msg))

    def _show_error_threadsafe(self, title, msg):
        self.after(0, lambda: messagebox.showerror(title, msg))


def main():
    root = App()
    expire_utc = datetime.datetime(2026, 3, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
    try:
        check_expired_or_exit(root, expire_utc, app_name="atlas_packer", offline_mode="strict")
        set_window_icon_png(root, "app.png")
        root.mainloop()
    finally:
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
    # App().mainloop()
