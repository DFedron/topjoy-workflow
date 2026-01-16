import os
import sys
import math
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from dataclasses import dataclass
from typing import List, Tuple, Optional

from PIL import Image, ImageTk

import os, sys, json, datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from email.utils import parsedate_to_datetime
# ---- Optional drag&drop (tkinterdnd2) ----
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False
    TkinterDnD = None
    DND_FILES = None


SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

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


# ---------------- Scrollable Frame (whole app scroll) ----------------
class ScrolledFrame(ttk.Frame):
    """外层可滚动容器：Canvas + inner Frame"""
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(self.canvas)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # 鼠标滚轮滚动整个界面（当鼠标在该区域时）
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _on_inner_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # 让 inner 宽度跟随 canvas，避免横向裁切
        self.canvas.itemconfigure(self.inner_id, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _bind_wheel(self, _event=None):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_wheel(self, _event=None):
        self.canvas.unbind_all("<MouseWheel>")


@dataclass
class PackedItem:
    path: str
    name: str
    w: int
    h: int
    x: int = 0
    y: int = 0


def is_image_file(p: str) -> bool:
    return os.path.splitext(p.lower())[1] in SUPPORTED_EXTS


def next_pow2(x: int) -> int:
    if x <= 1:
        return 1
    return 1 << (x - 1).bit_length()


def list_images_in_folder(folder: str) -> List[str]:
    out = []
    for root, _, files in os.walk(folder):
        for f in files:
            p = os.path.join(root, f)
            if is_image_file(p):
                out.append(p)
    return out


# ---------------- Packing (simple shelf / best-fit) ----------------
def shelf_pack(items: List[PackedItem], max_width: int, padding: int) -> Tuple[int, int, List[PackedItem]]:
    x = padding
    y = padding
    shelf_h = 0
    used_w = 0
    used_h = 0

    for it in items:
        iw = it.w + padding
        ih = it.h + padding

        if x + iw > max_width and x > padding:
            x = padding
            y += shelf_h
            shelf_h = 0

        it.x = x
        it.y = y

        x += iw
        shelf_h = max(shelf_h, ih)

        used_w = max(used_w, it.x + it.w + padding)
        used_h = max(used_h, it.y + it.h + padding)

    return used_w, used_h, items


def pack_auto(items: List[PackedItem], mode: str, padding: int) -> Tuple[int, int, List[PackedItem]]:
    """
    mode:
      - "tight": 尽量小（会尝试多次宽度，找 area 最小）
      - "square": 尽量正方形
      - "pot": 2^n（POT）
    """
    if not items:
        return 0, 0, []

    items = sorted(items, key=lambda a: (max(a.w, a.h), a.w * a.h), reverse=True)

    total_area = sum((it.w + padding) * (it.h + padding) for it in items)
    max_w = max(it.w for it in items) + 2 * padding

    guess = int(math.sqrt(total_area))
    guess = max(guess, max_w)

    candidates = []
    if mode == "tight":
        for k in range(10):
            candidates.append(max_w if k == 0 else int(guess * (1.0 + 0.15 * k)))
    elif mode == "square":
        for k in range(8):
            candidates.append(int(guess * (0.85 + 0.1 * k)))
    elif mode == "pot":
        base = next_pow2(guess)
        for k in range(6):
            candidates.append(base * (2 ** k))
    else:
        candidates = [guess]

    best = None  # (score, w, h, packed_items)
    for cw in candidates:
        w, h, packed = shelf_pack([PackedItem(**vars(i)) for i in items], cw, padding)

        if mode == "pot":
            w2 = next_pow2(w)
            h2 = next_pow2(h)
        elif mode == "square":
            s = max(w, h)
            w2, h2 = s, s
        else:
            w2, h2 = w, h

        area = w2 * h2
        aspect_penalty = abs((w2 / max(h2, 1)) - 1.0)
        score = area + area * 0.15 * aspect_penalty

        if best is None or score < best[0]:
            best = (score, w2, h2, packed)

    _, out_w, out_h, out_items = best
    return out_w, out_h, out_items


def build_atlas(items: List[PackedItem], atlas_w: int, atlas_h: int, bg_rgba=(0, 0, 0, 0)) -> Image.Image:
    atlas = Image.new("RGBA", (atlas_w, atlas_h), bg_rgba)
    for it in items:
        img = Image.open(it.path).convert("RGBA")
        atlas.paste(img, (it.x, it.y), img)
    return atlas


# ---------------- GUI ----------------
class AtlasPackerGUI:
    """
    parent: UI 挂载的容器（Frame）
    window: 顶层窗口（Tk），用于 title/icon/geometry
    """
    def __init__(self, parent, window: Optional[tk.Tk] = None):
        self.root = parent
        self.window = window if window is not None else parent

        # 只对 Tk 调用这些
        if hasattr(self.window, "title"):
            self.window.title("PNG 图集打包工具 (Atlas Packer)")
        if hasattr(self.window, "minsize"):
            self.window.minsize(900, 1000)

        self.paths: List[str] = []
        self.preview_imgtk: Optional[ImageTk.PhotoImage] = None
        self.last_atlas: Optional[Image.Image] = None
        self.last_items: List[PackedItem] = []
        self.last_out_dir: Optional[str] = None

        self.mode_var = tk.StringVar(value="tight")
        self.padding_var = tk.IntVar(value=0)
        self.output_name_var = tk.StringVar(value="atlas")
        self.bg_var = tk.StringVar(value="transparent")  # transparent / white / black

        self.compress_var = tk.BooleanVar(value=True)
        self.tinify_user_var = tk.StringVar(value="")
        self.tinify_key_var = tk.StringVar(value="")
        self.tinify_concurrency_var = tk.IntVar(value=2)
       

        # 预览缩放
        self.preview_scale = 1.0
        self._preview_canvas_img_id = None

        self._build_ui()
        self._setup_dnd()
        self._bind_preview_wheel_route()

    def _build_ui(self):
        # Left: list + controls
        left = ttk.Frame(self.root, padding=10)
        left.pack(side=tk.LEFT, fill=tk.Y)

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X)

        ttk.Button(btn_row, text="选择图片(多选)", command=self.add_files).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_row, text="选择文件夹", command=self.add_folder).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_row, text="清空", command=self.clear_all).pack(side=tk.LEFT, padx=3)

        hint = "拖拽支持：{}\n".format("已启用 ✅" if DND_AVAILABLE else "未启用（可 pip install tkinterdnd2）")
        ttk.Label(left, text=hint).pack(anchor="w", pady=(8, 0))

        # --- Listbox + Scrollbar ---
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.Y, pady=6)

        self.listbox = tk.Listbox(list_frame, width=55, height=24, selectmode=tk.EXTENDED)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)

        self.listbox.pack(side=tk.LEFT, fill=tk.Y)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        ctrl = ttk.LabelFrame(left, text="打包设置", padding=10)
        ctrl.pack(fill=tk.X, pady=8)

        ttk.Label(ctrl, text="图集尺寸模式：").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(ctrl, text="紧凑(最小)", value="tight", variable=self.mode_var).grid(row=1, column=0, sticky="w")
        ttk.Radiobutton(ctrl, text="正方形", value="square", variable=self.mode_var).grid(row=2, column=0, sticky="w")
        ttk.Radiobutton(ctrl, text="4次幂(POT)", value="pot", variable=self.mode_var).grid(row=3, column=0, sticky="w")

        ttk.Label(ctrl, text="边距 padding(px)：").grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Spinbox(ctrl, from_=0, to=64, textvariable=self.padding_var, width=8).grid(row=5, column=0, sticky="w")

        ttk.Label(ctrl, text="背景：").grid(row=6, column=0, sticky="w", pady=(10, 0))
        bg_row = ttk.Frame(ctrl)
        bg_row.grid(row=7, column=0, sticky="w")
        ttk.Radiobutton(bg_row, text="透明", value="transparent", variable=self.bg_var).pack(side=tk.LEFT)
        ttk.Radiobutton(bg_row, text="白", value="white", variable=self.bg_var).pack(side=tk.LEFT, padx=8)
        ttk.Radiobutton(bg_row, text="黑", value="black", variable=self.bg_var).pack(side=tk.LEFT)

        ttk.Label(ctrl, text="输出文件名：").grid(row=8, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(ctrl, textvariable=self.output_name_var, width=20).grid(row=9, column=0, sticky="w")

        ttk.Checkbutton(ctrl, text="导出时使用 Tinify 压缩", variable=self.compress_var).grid(row=10, column=0, sticky="w", pady=(10, 0))

        act = ttk.Frame(left)
        act.pack(fill=tk.X, pady=8)
        ttk.Button(act, text="预览打包", command=self.preview).pack(side=tk.LEFT, padx=3)
        ttk.Button(act, text="导出 PNG", command=self.export).pack(side=tk.LEFT, padx=3)

        self.status = ttk.Label(left, text="状态：等待选择图片", wraplength=400)
        self.status.pack(fill=tk.X, pady=(10, 0))

        # Right: preview + scrollbars
        right = ttk.Frame(self.root, padding=10)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        ttk.Label(right, text="预览（可滚动查看全图）：").pack(anchor="w")

        canvas_frame = ttk.Frame(right)
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=6)

        self.canvas = tk.Canvas(canvas_frame, bg="#222222", highlightthickness=0)
        self.hbar = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        self.vbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.info_label = ttk.Label(right, text="", wraplength=600)
        self.info_label.pack(anchor="w")

        # listbox wheel
        self.listbox.bind("<MouseWheel>", lambda e: self.listbox.yview_scroll(int(-e.delta / 120), "units"))

    def _setup_dnd(self):
        if not DND_AVAILABLE:
            return
        if not hasattr(self.window, "drop_target_register"):
            return
        self.listbox.drop_target_register(DND_FILES)
        self.listbox.dnd_bind("<<Drop>>", self._on_drop)

    @staticmethod
    def _split_dnd_paths(s: str) -> List[str]:
        out = []
        buf = ""
        in_brace = False
        for ch in s:
            if ch == "{":
                in_brace = True
                buf = ""
            elif ch == "}":
                in_brace = False
                if buf:
                    out.append(buf)
                    buf = ""
            elif ch.isspace() and not in_brace:
                if buf:
                    out.append(buf)
                    buf = ""
            else:
                buf += ch
        if buf:
            out.append(buf)
        return out

    def _on_drop(self, event):
        raw = event.data
        paths = self._split_dnd_paths(raw)
        self._add_paths(paths)

    def _bind_preview_wheel_route(self):
        """
        解决“整体滚动”和“预览滚动”冲突，并支持 Ctrl+滚轮缩放：
        - 鼠标在预览 canvas 内：滚动/缩放预览
        - 鼠标离开预览 canvas：交给外层 ScrolledFrame（外层 bind_all 会接管）
        """
        CTRL_MASK = 0x0004  # Windows Tk: Control
        SHIFT_MASK = 0x0001  # Shift

        def zoom_at_mouse(event, zoom_in: bool):
            if self.last_atlas is None:
                return

            old_s = float(self.preview_scale)
            factor = 1.1 if zoom_in else (1.0 / 1.1)
            new_s = max(0.1, min(old_s * factor, 8.0))  # 缩放范围可调

            if abs(new_s - old_s) < 1e-6:
                return

            # 当前鼠标对应的“画布坐标”（缩放前）
            mouse_x = self.canvas.canvasx(event.x)
            mouse_y = self.canvas.canvasy(event.y)

            # 计算鼠标点在内容中的相对位置（0~1）
            # 用 last_atlas 原尺寸 * old_s
            aw, ah = self.last_atlas.size
            old_w = max(1, int(aw * old_s))
            old_h = max(1, int(ah * old_s))
            rel_x = mouse_x / old_w
            rel_y = mouse_y / old_h

            # 更新缩放并重绘
            self.preview_scale = new_s
            self._render_preview(self.last_atlas, self.last_items)

            # 让缩放后仍尽量把“鼠标指向的相对位置”对齐回去
            new_w = max(1, int(aw * new_s))
            new_h = max(1, int(ah * new_s))
            target_x = rel_x * new_w
            target_y = rel_y * new_h

            # 计算新的滚动位置，让 target_x/target_y 出现在鼠标附近
            view_w = max(1, self.canvas.winfo_width())
            view_h = max(1, self.canvas.winfo_height())

            # 希望 target 点在窗口中保持在 event.x/event.y 附近
            left = target_x - event.x
            top = target_y - event.y

            # 归一化到 xview/yview 的 0~1
            max_left = max(1, new_w - view_w)
            max_top = max(1, new_h - view_h)

            self.canvas.xview_moveto(max(0.0, min(left / max_left, 1.0)))
            self.canvas.yview_moveto(max(0.0, min(top / max_top, 1.0)))

        def on_canvas_wheel(event):
            # Ctrl + 滚轮：缩放
            if event.state & CTRL_MASK:
                zoom_at_mouse(event, zoom_in=(event.delta > 0))
                return

            # Shift + 滚轮：横向滚动
            if event.state & SHIFT_MASK:
                self.canvas.xview_scroll(int(-event.delta / 120), "units")
            else:
                self.canvas.yview_scroll(int(-event.delta / 120), "units")

        def bind_canvas_wheel(_e):
            self.canvas.bind_all("<MouseWheel>", on_canvas_wheel)

        def unbind_canvas_wheel(_e):
            self.canvas.unbind_all("<MouseWheel>")

        self.canvas.bind("<Enter>", bind_canvas_wheel)
        self.canvas.bind("<Leave>", unbind_canvas_wheel)


        def bind_canvas_wheel(_e):
            self.canvas.bind_all("<MouseWheel>", on_canvas_wheel)

        def unbind_canvas_wheel(_e):
            # 解除后，外层 ScrolledFrame 的 bind_all 会接管
            self.canvas.unbind_all("<MouseWheel>")

        self.canvas.bind("<Enter>", bind_canvas_wheel)
        self.canvas.bind("<Leave>", unbind_canvas_wheel)

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="选择图片（可多选）",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All", "*.*")]
        )
        self._add_paths(list(files))

    def add_folder(self):
        folder = filedialog.askdirectory(title="选择一个文件夹（会递归扫描图片）")
        if not folder:
            return
        imgs = list_images_in_folder(folder)
        self._add_paths(imgs)

    def clear_all(self):
        self.paths.clear()
        self.listbox.delete(0, tk.END)
        self.canvas.delete("all")
        self.canvas.configure(scrollregion=(0, 0, 0, 0))
        self.status.config(text="状态：已清空")
        self.info_label.config(text="")
        self.last_atlas = None
        self.last_items = []
        self.last_out_dir = None
        self.preview_imgtk = None

    def _add_paths(self, paths: List[str]):
        added = 0
        for p in paths:
            p = p.strip().strip('"')
            if not p:
                continue
            if os.path.isdir(p):
                imgs = list_images_in_folder(p)
                for ip in imgs:
                    if ip not in self.paths:
                        self.paths.append(ip)
                        added += 1
            else:
                if is_image_file(p) and os.path.exists(p) and p not in self.paths:
                    self.paths.append(p)
                    added += 1

        self.paths.sort()
        self.listbox.delete(0, tk.END)
        for p in self.paths:
            self.listbox.insert(tk.END, p)

        self.status.config(text=f"状态：已选择 {len(self.paths)} 张图片（新增 {added}）")

    def _make_items(self) -> List[PackedItem]:
        items = []
        for p in self.paths:
            try:
                with Image.open(p) as im:
                    w, h = im.size
                items.append(PackedItem(path=p, name=os.path.basename(p), w=w, h=h))
            except Exception as e:
                print(f"[WARN] 读取失败: {p} -> {e}")
        return items

    def _bg_rgba(self):
        v = self.bg_var.get()
        if v == "white":
            return (255, 255, 255, 255)
        if v == "black":
            return (0, 0, 0, 255)
        return (0, 0, 0, 0)

    def preview(self):
        if not self.paths:
            messagebox.showwarning("提示", "请先选择图片或文件夹。")
            return

        items = self._make_items()
        if not items:
            messagebox.showerror("错误", "没有可用图片（可能都读取失败或格式不支持）。")
            return

        mode = self.mode_var.get()
        padding = int(self.padding_var.get())

        atlas_w, atlas_h, packed_items = pack_auto(items, mode, padding)
        atlas = build_atlas(packed_items, atlas_w, atlas_h, self._bg_rgba())

        self.last_atlas = atlas
        self.last_items = packed_items
        self.preview_scale = 1.0

        self.last_out_dir = os.path.dirname(self.paths[0])

        self._render_preview(atlas, packed_items)
        self.status.config(text=f"状态：预览完成 | 模式={mode} | 尺寸={atlas_w}x{atlas_h} | 输出目录={self.last_out_dir}")

    def _render_preview(self, atlas: Image.Image, items: List[PackedItem]):
        """按 self.preview_scale 渲染预览（支持滚动与缩放）"""
        self.canvas.delete("all")

        aw, ah = atlas.size
        s = float(self.preview_scale)

        # 缩放后的尺寸
        sw = max(1, int(aw * s))
        sh = max(1, int(ah * s))

        # 用 NEAREST 更清晰（像素图/图集常用）；想更平滑可改成 LANCZOS
        scaled = atlas.resize((sw, sh), Image.Resampling.NEAREST)

        self.preview_imgtk = ImageTk.PhotoImage(scaled)
        self._preview_canvas_img_id = self.canvas.create_image(0, 0, anchor="nw", image=self.preview_imgtk)

        # 画框（同步缩放）
        for it in items:
            x1 = int(it.x * s)
            y1 = int(it.y * s)
            x2 = int((it.x + it.w) * s)
            y2 = int((it.y + it.h) * s)
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="#00ff66")

        # 更新滚动区域
        self.canvas.configure(scrollregion=(0, 0, sw, sh))

        self.info_label.config(
            text=f"图集：{aw}x{ah} | 预览：{sw}x{sh} | 缩放：{s:.2f}x | "
                 f"滚轮纵向滚动，Shift+滚轮横向，Ctrl+滚轮缩放"
        )


    def export(self):
        if self.last_atlas is None or not self.last_items:
            self.preview()
            if self.last_atlas is None:
                return

        out_dir = self.last_out_dir or os.path.dirname(self.paths[0])
        base = self.output_name_var.get().strip() or "atlas"
        out_png = os.path.join(out_dir, f"{base}.png")

        do_compress = bool(self.compress_var.get())
        user = self.tinify_user_var.get().strip()
        key = self.tinify_key_var.get().strip()
        concurrency = int(self.tinify_concurrency_var.get())

        # UI：禁用按钮避免重复点击（你如果有按钮引用可以做得更细）
        self.status.config(text="状态：正在导出..." + ("（Tinify 压缩中）" if do_compress else ""))

        import threading, tempfile, asyncio

        def worker():
            try:
                # 1) 先写入临时文件（Tinify 需要读文件）
                with tempfile.TemporaryDirectory() as td:
                    tmp_in = os.path.join(td, "atlas_uncompressed.png")
                    self.last_atlas.save(tmp_in, format="PNG", optimize=True)

                    if not do_compress:
                        # 不压缩：直接写目标
                        os.makedirs(os.path.dirname(out_png), exist_ok=True)
                        # 直接复制文件内容（避免 PIL 再编码一次也行）
                        with open(tmp_in, "rb") as fsrc, open(out_png, "wb") as fdst:
                            fdst.write(fsrc.read())
                    else:
                        # 2) 压缩：调用你的 TinifyAsyncCompressor
                        # 这里按你现有的 compress_one 用法集成
                        from tinify_async_compress import TinifyAsyncCompressor, Config, TinyReqMode, CompressResult

                        async def _run():
                            cfg = Config(
                                tinyReqMode=TinyReqMode.WEB,
                                mail=user,
                                key=key,
                                concurrency=concurrency,
                                retries=3
                            )

                            # 这些回调如果要更新 UI，必须用 self.window.after 回主线程
                            def on_finished(res: CompressResult):
                                self.window.after(0, lambda: self.status.config(
                                    text=f"状态：Tinify OK -> {os.path.basename(res.output_path)} ({res.size} bytes)"
                                ))

                            def on_error(res: CompressResult):
                                self.window.after(0, lambda: self.status.config(
                                    text=f"状态：Tinify ERR -> {res.errmsg}"
                                ))

                            async with TinifyAsyncCompressor(cfg, on_finished=on_finished, on_error=on_error) as comp:
                                res = await comp.compress_one(tmp_in, out_png)
                                if not res.ok:
                                    raise RuntimeError(res.errmsg)

                        asyncio.run(_run())

                # 完成：回主线程提示
                self.window.after(0, lambda: (
                    self.status.config(text=f"状态：导出成功 ✅\n{out_png}"),
                    messagebox.showinfo("完成", f"已导出：\n{out_png}")
                ))
            except Exception as e:
                self.window.after(0, lambda: messagebox.showerror("导出失败", str(e)))

        threading.Thread(target=worker, daemon=True).start()



def main():
    # 顶层窗口必须是 Tk（或 TkinterDnD.Tk），图标/标题都对它设置
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    # 过期时间（UTC）——比如 2026-01-10 00:00:00 UTC
    expire_utc = datetime.datetime(2026, 3, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)

    # 启动前校验：过期/无法验证 → 只弹通知并退出
    check_expired_or_exit(root, expire_utc, app_name="atlas_packer", offline_mode="strict")

    root.geometry("1150x720")
    root.minsize(900, 600)

    # PNG 图标（同目录放 app.png；PyInstaller 也可用）
    set_window_icon_png(root, "app.png")

    # ✅ 外层整体滚动容器
    scroller = ScrolledFrame(root)
    scroller.pack(fill="both", expand=True)

    # ✅ UI 挂到 scroller.inner，但窗口相关仍用 root
    AtlasPackerGUI(scroller.inner, window=root)

    root.mainloop()


if __name__ == "__main__":
    main()
