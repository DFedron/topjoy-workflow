import asyncio
import os
import queue
import tempfile
import threading
from typing import List

import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image, ImageTk

from .constants import PREVIEW_SIZE
from .dependencies import (
    Config,
    CompressResult,
    DND_FILES,
    DND_OK,
    TINIFY_OK,
    TinyReqMode,
    TinifyAsyncCompressor,
    TkinterDnD,
)
from .image_ops import (
    align_to_4,
    collect_images_from_folder,
    compute_target_canvas,
    crop_transparent_area,
    crop_with_bbox,
    downscale_to_max_side,
    expand_bbox,
    expand_image_to_canvas,
    get_alpha_bbox,
    is_image_file,
    parse_bg_color,
)
from .models import ImageTask
from .resources import set_window_icon_png
from .settings import load_settings, save_settings


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
        self.prefix = tk.StringVar(value="")
        self.suffix = tk.StringVar(value="")
        self.overwrite = tk.BooleanVar(value=False)

        # ---- 背景 & 放大 ----
        self.bg = tk.StringVar(value="transparent")
        self.allow_upscale = tk.BooleanVar(value=False)
        self.trim_transparent = tk.BooleanVar(value=True)
        self.trim_padding = tk.StringVar(value="0")
        self.trim_mode = tk.StringVar(value="batch")
        self.direct_output = tk.BooleanVar(value=False)

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
        self._batch_trim_bbox: tuple[int, int, int, int] | None = None

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
        tk.Label(row1, text="前缀:").pack(side="left", padx=(10, 0))
        tk.Entry(row1, textvariable=self.prefix, width=10).pack(side="left")
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
        tk.Checkbutton(row3, text="裁切透明边缘", variable=self.trim_transparent,
                       command=self.rebuild_all_tasks).pack(side="left", padx=(10, 0))
        tk.Label(row3, text="模式:").pack(side="left", padx=(8, 0))
        tk.OptionMenu(row3, self.trim_mode, "batch", "single",
                      command=lambda _=None: self.rebuild_all_tasks()).pack(side="left")
        tk.Label(row3, text="保留边距:").pack(side="left", padx=(8, 0))
        tk.Entry(row3, textvariable=self.trim_padding, width=6).pack(side="left")
        tk.Label(row3, text="px").pack(side="left", padx=(2, 10))
        tk.Checkbutton(row3, text="直接输出裁切结果", variable=self.direct_output,
                       command=self.rebuild_all_tasks).pack(side="left", padx=(0, 10))

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
        self.prefix.set(cfg.get("prefix", self.prefix.get()))
        self.suffix.set(cfg.get("suffix", self.suffix.get()))
        self.overwrite.set(bool(cfg.get("overwrite", self.overwrite.get())))
        self.bg.set(cfg.get("bg", self.bg.get()))
        self.allow_upscale.set(bool(cfg.get("allow_upscale", self.allow_upscale.get())))
        self.trim_transparent.set(bool(cfg.get("trim_transparent", self.trim_transparent.get())))
        self.trim_padding.set(cfg.get("trim_padding", self.trim_padding.get()))
        self.trim_mode.set(cfg.get("trim_mode", self.trim_mode.get()))
        self.direct_output.set(bool(cfg.get("direct_output", self.direct_output.get())))
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
            "prefix": self.prefix.get(),
            "suffix": self.suffix.get(),
            "overwrite": bool(self.overwrite.get()),
            "bg": self.bg.get(),
            "allow_upscale": bool(self.allow_upscale.get()),
            "trim_transparent": bool(self.trim_transparent.get()),
            "trim_padding": self.trim_padding.get(),
            "trim_mode": self.trim_mode.get(),
            "direct_output": bool(self.direct_output.get()),
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
        self.add_tasks(paths)

    def add_folder(self):
        folder = filedialog.askdirectory(title="选择文件夹（添加里面的图片）")
        if not folder:
            return
        self.add_tasks(collect_images_from_folder(folder))

    def on_drop(self, event):
        files = self.tk.splitlist(event.data)
        paths = []
        for f in files:
            f = f.strip("{}")
            if is_image_file(f):
                paths.append(f)
        self.add_tasks(paths)

    def add_tasks(self, paths):
        added_indices = []
        skipped = 0

        for raw_path in paths:
            path = os.path.abspath(raw_path)
            if path in self.task_index:
                continue
            try:
                with Image.open(path) as img:
                    rgba = img.convert("RGBA")
                    w, h = rgba.size
                    alpha_bbox = get_alpha_bbox(rgba)
            except Exception as e:
                skipped += 1
                self.log(f"[跳过] 读取失败: {path} ({e})")
                continue

            task = ImageTask(src_path=path, src_size=(w, h), alpha_bbox=alpha_bbox)
            self.tasks.append(task)
            idx = len(self.tasks) - 1
            self.task_index[path] = idx
            added_indices.append(idx)

        if not added_indices:
            return

        for idx in added_indices:
            self.listbox.insert("end", os.path.basename(self.tasks[idx].src_path))

        self._batch_trim_bbox = self._compute_batch_trim_bbox()

        last_idx = added_indices[-1]
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(last_idx)
        self.rebuild_selected_preview()

        if len(added_indices) > 1:
            msg = f"已添加 {len(added_indices)} 张图片。"
            if skipped:
                msg += f" 跳过 {skipped} 张。"
            self.log(msg)

    def add_task(self, path: str):
        path = os.path.abspath(path)
        if path in self.task_index:
            return
        try:
            with Image.open(path) as img:
                rgba = img.convert("RGBA")
                w, h = rgba.size
                alpha_bbox = get_alpha_bbox(rgba)
        except Exception as e:
            self.log(f"[跳过] 读取失败: {path} ({e})")
            return

        task = ImageTask(src_path=path, src_size=(w, h), alpha_bbox=alpha_bbox)
        self.tasks.append(task)
        self.task_index[path] = len(self.tasks) - 1
        self._batch_trim_bbox = self._compute_batch_trim_bbox()
        self.listbox.insert("end", os.path.basename(path))

        # 自动选中并显示
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set("end")
        self.rebuild_selected_preview()

    def clear_tasks(self):
        self.tasks.clear()
        self.task_index.clear()
        self._batch_trim_bbox = None
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
        self._batch_trim_bbox = self._compute_batch_trim_bbox()

        self.preview_label.config(image="")
        self.info_label.config(text="")
        self._preview_tk = None

    def _retain_failed_tasks(self, failed_paths: set[str]):
        if not self.tasks:
            return
        kept = [t for t in self.tasks if t.src_path in failed_paths]
        self.tasks = kept
        self.task_index = {t.src_path: i for i, t in enumerate(self.tasks)}
        self._batch_trim_bbox = self._compute_batch_trim_bbox()

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

    def _get_non_negative_int(self, s: str, default: int) -> int:
        try:
            v = int(str(s).strip())
            return v if v >= 0 else default
        except Exception:
            return default

    def _compute_batch_trim_bbox(self) -> tuple[int, int, int, int] | None:
        if not self.trim_transparent.get() or self.trim_mode.get() != "batch":
            return None
        if not self.tasks:
            return None

        trim_padding = self._get_non_negative_int(self.trim_padding.get(), 0)
        union_bbox = None

        for task in self.tasks:
            bbox = task.alpha_bbox
            if bbox is None:
                continue
            bbox = expand_bbox(bbox, task.src_size[0], task.src_size[1], trim_padding)
            if union_bbox is None:
                union_bbox = bbox
            else:
                union_bbox = (
                    min(union_bbox[0], bbox[0]),
                    min(union_bbox[1], bbox[1]),
                    max(union_bbox[2], bbox[2]),
                    max(union_bbox[3], bbox[3]),
                )
        return union_bbox

    def _load_source_image_for_task(self, task: ImageTask) -> Image.Image:
        src_img = Image.open(task.src_path).convert("RGBA")
        if self.trim_transparent.get():
            trim_padding = self._get_non_negative_int(self.trim_padding.get(), 0)
            if self.trim_mode.get() == "batch":
                src_img = crop_with_bbox(src_img, self._batch_trim_bbox)
            else:
                src_img = crop_transparent_area(src_img, trim_padding)
        return src_img

    def _recompute_task(self, task: ImageTask):
        ow = self._get_int(self.out_w.get(), 512)
        oh = self._get_int(self.out_h.get(), 512)
        ms = self._get_int(self.max_side.get(), 1024)

        bg = parse_bg_color(self.bg.get())
        allow_up = bool(self.allow_upscale.get())
        direct_output = bool(self.direct_output.get())

        try:
            src_img = self._load_source_image_for_task(task)
            task.content_size = src_img.size

            if direct_output:
                if self.use_max_side.get():
                    bw, bh, pre_scale = downscale_to_max_side(src_img.size[0], src_img.size[1], ms)
                else:
                    pre_scale = min(ow / src_img.size[0], oh / src_img.size[1])
                    if not allow_up:
                        pre_scale = min(pre_scale, 1.0)
                    bw = max(1, int(round(src_img.size[0] * pre_scale)))
                    bh = max(1, int(round(src_img.size[1] * pre_scale)))
                if self.use_align4.get():
                    # 直接输出不会补画布，因此在这里把最终输出尺寸本身对齐到 4 的倍数。
                    bw = align_to_4(bw, self.align4_mode.get())
                    bh = align_to_4(bh, self.align4_mode.get())
                cw, ch = bw, bh
            else:
                cw, ch, bw, bh, pre_scale = compute_target_canvas(
                    src_img.size[0], src_img.size[1],
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

            # 先预缩放到 base_size（允许放大或缩小）
            if (bw, bh) != src_img.size:
                src_img = src_img.resize((bw, bh), Image.LANCZOS)

            if direct_output:
                expanded = src_img
                task.scale_to_canvas = 1.0
                task.resized_size = src_img.size
            else:
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
            task.content_size = task.src_size
            task.base_size = task.src_size
            task.canvas_size = task.src_size
            task.scale_to_canvas = 1.0
            task.resized_size = (0, 0)
            self.log(f"[预览失败] {os.path.basename(task.src_path)}: {e}")

    def rebuild_all_tasks(self):
        if not self.tasks:
            return
        self._batch_trim_bbox = self._compute_batch_trim_bbox()
        for t in self.tasks:
            self._recompute_task(t)
        self.log("已重算全部任务的尺寸与预览。")
        self.rebuild_selected_preview()

    def rebuild_selected_preview(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self._batch_trim_bbox = self._compute_batch_trim_bbox()
        self._recompute_task(self.tasks[idx])
        self.on_select_task(None)

    def on_select_task(self, _):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        t = self.tasks[idx]
        if t.preview_pil is None:
            self._batch_trim_bbox = self._compute_batch_trim_bbox()
            self._recompute_task(t)
        if t.preview_pil is None:
            self.preview_label.config(image="")
            self.info_label.config(text="预览不可用")
            self._preview_tk = None
            return

        self._preview_tk = ImageTk.PhotoImage(t.preview_pil)
        self.preview_label.config(image=self._preview_tk)

        sw, sh = t.src_size
        tw, th = t.content_size
        cw, ch = t.canvas_size
        total_scale = t.pre_scale * t.scale_to_canvas

        self.info_label.config(
            text=(
                f"文件: {os.path.basename(t.src_path)}\n"
                f"变化前: {sw} x {sh}\n"
                f"裁切后: {tw} x {th}\n"
                f"变化后: {cw} x {ch}\n"
                f"裁切模式: {'整批统一' if self.trim_mode.get() == 'batch' else '单张独立'}\n"
                f"输出模式: {'直接输出' if self.direct_output.get() else '补画布'}\n"
                f"缩放: {total_scale:.4f}"
            )
        )

    # ---------------- output path ----------------

    def _resolve_output_path(self, src_path: str) -> str:
        prefix = (self.prefix.get().strip() or "")
        suffix = (self.suffix.get().strip() or "")

        if self.overwrite.get():
            src_dir = os.path.dirname(src_path)
            base, ext = os.path.splitext(os.path.basename(src_path))
            ext = ext or ".png"
            return os.path.join(src_dir, f"{prefix}{base}{suffix}{ext}")

        out_dir = self.output_dir.get().strip()
        if not out_dir:
            raise ValueError("未勾选覆盖时，必须选择输出文件夹。")

        base = os.path.splitext(os.path.basename(src_path))[0]
        return os.path.join(out_dir, f"{prefix}{base}{suffix}.png")

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
            self._batch_trim_bbox = self._compute_batch_trim_bbox()

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
        src_img = self._load_source_image_for_task(task)

        bw, bh = task.base_size
        if (bw, bh) != src_img.size:
            # 与预览一致的 pre-scale
            src_img = src_img.resize((bw, bh), Image.LANCZOS)

        if self.direct_output.get():
            expanded = src_img
        else:
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
    try:
        set_window_icon_png(root, "app.png")
        root.mainloop()
    finally:
        try:
            root.destroy()
        except Exception:
            pass

