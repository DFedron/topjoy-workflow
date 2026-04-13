from __future__ import annotations

import base64
import tkinter as tk
from tkinter import filedialog, messagebox

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from Crypto.Util.Padding import unpad

FIXED_KEY = "Topjoy"


def _derive_key(key: str) -> bytes:
    # Match C# key.PadRight(32).Substring(0, 32) then UTF8 bytes.
    return key.ljust(32)[:32].encode("utf-8")


def decrypt_cipher_text(cipher_text_b64: str) -> str:
    raw = base64.b64decode(cipher_text_b64)

    cipher = AES.new(_derive_key(FIXED_KEY), AES.MODE_CBC, iv=bytes(16))
    decrypted = cipher.decrypt(raw)
    unpadded = unpad(decrypted, AES.block_size, style="pkcs7")

    return unpadded.decode("utf-8")


def encrypt_plain_text(plain_text: str) -> str:
    raw = plain_text.encode("utf-8")

    cipher = AES.new(_derive_key(FIXED_KEY), AES.MODE_CBC, iv=bytes(16))
    encrypted = cipher.encrypt(pad(raw, AES.block_size, style="pkcs7"))

    return base64.b64encode(encrypted).decode("utf-8")


class DecryptApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Topjoy Decrypt Tool")
        self.geometry("860x560")
        self.minsize(700, 460)

        self._build_ui()

    def _build_ui(self) -> None:
        root = tk.Frame(self, padx=12, pady=12)
        root.pack(fill="both", expand=True)

        info = tk.Label(
            root,
            text="算法: AES-CBC + PKCS7",
            anchor="w",
            justify="left",
        )
        info.pack(fill="x", pady=(0, 10))

        src_label = tk.Label(root, text="输入内容", anchor="w")
        src_label.pack(fill="x")

        self.src_text = tk.Text(root, height=10, wrap="word")
        self.src_text.pack(fill="both", expand=True, pady=(4, 10))

        btns = tk.Frame(root)
        btns.pack(fill="x", pady=(0, 10))

        tk.Button(btns, text="加密", width=12, command=self.on_encrypt).pack(side="left", padx=(0, 8))
        tk.Button(btns, text="解密", width=12, command=self.on_decrypt).pack(side="left")
        tk.Button(btns, text="从文件加载", width=12, command=self.on_load_file).pack(side="left", padx=8)
        tk.Button(btns, text="保存结果", width=12, command=self.on_save_file).pack(side="left")
        tk.Button(btns, text="清空", width=12, command=self.on_clear).pack(side="right")

        dst_label = tk.Label(root, text="结果", anchor="w")
        dst_label.pack(fill="x")

        self.dst_text = tk.Text(root, height=12, wrap="word")
        self.dst_text.pack(fill="both", expand=True, pady=(4, 0))

    def on_encrypt(self) -> None:
        plain_text = self.src_text.get("1.0", "end").rstrip("\n")
        if not plain_text:
            messagebox.showwarning("提示", "请输入明文。")
            return

        try:
            cipher_text = encrypt_plain_text(plain_text)
        except Exception as exc:
            messagebox.showerror("加密失败", f"{exc}")
            return

        self.dst_text.delete("1.0", "end")
        self.dst_text.insert("1.0", cipher_text)

    def on_decrypt(self) -> None:
        cipher_text = self.src_text.get("1.0", "end").strip()
        if not cipher_text:
            messagebox.showwarning("提示", "请输入 Base64 密文。")
            return

        try:
            plain_text = decrypt_cipher_text(cipher_text)
        except Exception as exc:
            messagebox.showerror("解密失败", f"{exc}")
            return

        self.dst_text.delete("1.0", "end")
        self.dst_text.insert("1.0", plain_text)

    def on_load_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择密文文件",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            messagebox.showerror("读取失败", f"{exc}")
            return

        self.src_text.delete("1.0", "end")
        self.src_text.insert("1.0", content)

    def on_save_file(self) -> None:
        content = self.dst_text.get("1.0", "end").rstrip("\n")
        if not content:
            messagebox.showwarning("提示", "没有可保存的解密结果。")
            return

        path = filedialog.asksaveasfilename(
            title="保存解密结果",
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as exc:
            messagebox.showerror("保存失败", f"{exc}")
            return

        messagebox.showinfo("完成", "保存成功。")

    def on_clear(self) -> None:
        self.src_text.delete("1.0", "end")
        self.dst_text.delete("1.0", "end")


if __name__ == "__main__":
    app = DecryptApp()
    app.mainloop()

