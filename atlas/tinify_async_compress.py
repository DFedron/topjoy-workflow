import asyncio
import base64
import json
import os
import random
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

import aiofiles
import aiohttp

SUPPORTED_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga")


class TinyReqMode(str, Enum):
    API = "api"
    WEB = "web"  # 不推荐：网页内部接口，易变且可能触发风控


@dataclass
class Config:
    tinyReqMode: TinyReqMode = TinyReqMode.WEB

    # Tinify API 账号配置（官方接口用）
    mail: str = ""   # Tinify API 的用户名（通常是 "api" 或你的账户名，取决于你用的方式）
    key: str = ""    # Tinify API key

    # 并发数（建议 2~6，视网络和额度）
    concurrency: int = 4

    # 超时（秒）
    timeout_shrink: int = 180
    timeout_download: int = 120

    # 重试
    retries: int = 3
    retry_backoff: float = 0.8  # 基础退避


@dataclass
class CompressResult:
    ok: bool
    input_path: str
    output_path: str
    size: int = 0
    errmsg: str = ""


def is_image_file(path: str) -> bool:
    return os.path.isfile(path) and path.lower().endswith(SUPPORTED_EXTS)


def list_images(input_path: str) -> list[str]:
    """输入可以是文件或文件夹，输出图片文件列表（文件夹只扫一层，可改递归）。"""
    if os.path.isfile(input_path):
        return [input_path] if is_image_file(input_path) else []
    if os.path.isdir(input_path):
        res = []
        for name in os.listdir(input_path):
            p = os.path.join(input_path, name)
            if is_image_file(p):
                res.append(p)
        res.sort()
        return res
    return []


def relpath_under_root(root: str, file_path: str) -> str:
    """用于保持目录结构。"""
    try:
        return os.path.relpath(file_path, root)
    except ValueError:
        # 不在同盘符等情况：退化为 basename
        return os.path.basename(file_path)


class TinifyAsyncCompressor:
    def __init__(
        self,
        config: Config,
        on_finished: Optional[Callable[[CompressResult], None]] = None,
        on_error: Optional[Callable[[CompressResult], None]] = None,
    ):
        self.config = config
        self.on_finished = on_finished
        self.on_error = on_error

        self._session: Optional[aiohttp.ClientSession] = None
        self._sem = asyncio.Semaphore(max(1, config.concurrency))

    @staticmethod
    def _generate_ip() -> str:
        return ".".join(str(random.randint(1, 254)) for _ in range(4))

    def _auth_header(self) -> dict:
        auth_str = f"{self.config.mail}:{self.config.key}"
        auth_base64 = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        return {"Authorization": f"Basic {auth_base64}"}

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._session:
            await self._session.close()

    async def compress_one(self, input_file: str, output_file: str) -> CompressResult:
        """压缩单张图片：POST shrink -> GET output.url -> 写文件"""
        assert self._session is not None, "session not initialized"

        async with self._sem:
            try:
                # 读文件
                async with aiofiles.open(input_file, "rb") as f:
                    binary = await f.read()

                # shrink（拿到 output.url）
                output_url, expected_size = await self._shrink(binary)

                # download
                data = await self._download(output_url)

                # 写输出
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                async with aiofiles.open(output_file, "wb") as f:
                    await f.write(data)

                res = CompressResult(
                    ok=True,
                    input_path=input_file,
                    output_path=output_file,
                    size=len(data),
                    errmsg="",
                )
                if self.on_finished:
                    self.on_finished(res)
                return res

            except Exception as e:
                res = CompressResult(
                    ok=False,
                    input_path=input_file,
                    output_path=output_file,
                    size=0,
                    errmsg=str(e),
                )
                if self.on_error:
                    self.on_error(res)
                return res

    async def _shrink(self, binary: bytes) -> tuple[str, int]:
        """调用 Tinify shrink，返回 (output_url, output_size_guess)."""
        assert self._session is not None

        if self.config.tinyReqMode == TinyReqMode.WEB:
            # ⚠️ 不推荐：网页内部接口，可能不稳定/风控
            url = "https://tinify.com/backend/opt/shrink"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36",
                "Content-Type": "application/x-www-form-urlencoded",
                "x-forwarded-for": self._generate_ip(),
            }
        else:
            url = "https://api.tinify.com/shrink"
            headers = self._auth_header()

        timeout = aiohttp.ClientTimeout(total=self.config.timeout_shrink)

        last_err = None
        for attempt in range(self.config.retries + 1):
            try:
                async with self._session.post(url, data=binary, headers=headers, timeout=timeout) as resp:
                    text = await resp.text()

                    # Tinify API 成功一般是 201 Created；部分情况 200
                    if resp.status not in (200, 201):
                        # 429/5xx 适合重试
                        if resp.status in (429, 500, 502, 503, 504):
                            raise RuntimeError(f"shrink HTTP {resp.status}: {text}")
                        raise RuntimeError(f"shrink failed HTTP {resp.status}: {text}")

                    data = json.loads(text)
                    out = data.get("output") or {}
                    out_url = out.get("url", "")
                    if not out_url:
                        raise RuntimeError(f"shrink response missing output.url: {text}")

                    out_size = int(out.get("size") or 0)
                    return out_url, out_size

            except Exception as e:
                last_err = e
                if attempt < self.config.retries:
                    await asyncio.sleep(self.config.retry_backoff * (2 ** attempt))
                else:
                    break

        raise RuntimeError(f"shrink error after retries: {last_err}")

    async def _download(self, url: str) -> bytes:
        """下载压缩后的图片二进制"""
        assert self._session is not None

        headers = {}
        if self.config.tinyReqMode == TinyReqMode.WEB:
            headers = {"x-forwarded-for": self._generate_ip()}

        timeout = aiohttp.ClientTimeout(total=self.config.timeout_download)

        last_err = None
        for attempt in range(self.config.retries + 1):
            try:
                async with self._session.get(url, headers=headers, timeout=timeout) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        if resp.status in (429, 500, 502, 503, 504):
                            raise RuntimeError(f"download HTTP {resp.status}: {text}")
                        raise RuntimeError(f"download failed HTTP {resp.status}: {text}")

                    return await resp.read()

            except Exception as e:
                last_err = e
                if attempt < self.config.retries:
                    await asyncio.sleep(self.config.retry_backoff * (2 ** attempt))
                else:
                    break

        raise RuntimeError(f"download error after retries: {last_err}")


async def compress_path(
    input_path: str,
    output_root: str,
    config: Config,
    keep_structure: bool = True,
):
    """
    input_path: 单文件或文件夹
    output_root: 输出根目录
    keep_structure: 输入是文件夹时，是否保持相对路径结构（默认保持）
    """
    images = list_images(input_path)
    if not images:
        raise RuntimeError("未找到可处理的图片。")

    # 输入根：用于计算相对路径
    input_root = input_path if os.path.isdir(input_path) else os.path.dirname(input_path)

    def on_finished(res: CompressResult):
        print(f"[OK] {res.input_path} -> {res.output_path} ({res.size} bytes)")

    def on_error(res: CompressResult):
        print(f"[ERR] {res.input_path} -> {res.output_path} : {res.errmsg}")

    os.makedirs(output_root, exist_ok=True)

    async with TinifyAsyncCompressor(config, on_finished=on_finished, on_error=on_error) as comp:
        tasks = []
        for img_path in images:
            if keep_structure and os.path.isdir(input_path):
                rel = relpath_under_root(input_root, img_path)
                # 输出扩展名：通常 Tinify 输出仍是同格式，但这里我们保持原扩展名
                out_path = os.path.join(output_root, rel)
            else:
                out_path = os.path.join(output_root, os.path.basename(img_path))

            tasks.append(comp.compress_one(img_path, out_path))

        results = await asyncio.gather(*tasks)
        ok_count = sum(1 for r in results if r.ok)
        print(f"Done: {ok_count}/{len(results)}")
        return results


if __name__ == "__main__":
    # 示例：把 pow2 输出目录作为输入，然后压缩到 compressed 目录
    cfg = Config(
        tinyReqMode=TinyReqMode.WEB,
        mail=os.environ.get("TINIFY_USER", "api"),
        key=os.environ.get("TINIFY_API_KEY", ""),
        concurrency=4,
        retries=3,
    )

    if not cfg.key:
        raise SystemExit("请先设置环境变量 TINIFY_API_KEY（以及可选 TINIFY_USER）。")

    in_path = r"./pow2_out"       # 你的扩图输出目录（或单个文件）
    out_root = r"./compressed"    # 压缩输出目录
    asyncio.run(compress_path(in_path, out_root, cfg, keep_structure=True))
