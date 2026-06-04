import os
import sys
import tkinter as tk


def resource_path(relative_path: str) -> str:
    """兼容 PyInstaller：开发环境=项目根目录；打包后=_MEIPASS。"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)  # type: ignore[attr-defined]
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), relative_path)


def set_window_icon_png(window: tk.Tk, png_name: str = "app.png"):
    """用 PNG 设置窗口图标（标题栏/任务栏），兼容 PyInstaller。"""
    icon_path = resource_path(png_name)
    try:
        icon_img = tk.PhotoImage(file=icon_path)
        window.iconphoto(True, icon_img)
        window._icon_img_ref = icon_img  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[WARN] 设置窗口图标失败: {icon_path} -> {e}")

