import datetime
import json
import os
import sys
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def get_network_utc_time(timeout=3) -> datetime.datetime:
    """
    通过 HTTP Date 头获取网络 UTC 时间（不依赖本机时间）。
    依次尝试多个站点，提升成功率。
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
      - "strict": 无法获取网络时间就禁止启动
      - "cache": 断网时用缓存网络时间判断；没缓存则禁止
    """
    import tkinter.messagebox as mb

    try:
        now_utc = get_network_utc_time()
        save_cached_network_time(now_utc, app_name=app_name)
    except Exception:
        if offline_mode == "cache":
            cached = load_cached_network_time(app_name=app_name)
            if cached is None:
                mb.showerror("错误", "文件损坏")
                root.destroy()
                sys.exit(0)
            now_utc = cached
        else:
            mb.showerror("错误", "文件损坏")
            root.destroy()
            sys.exit(0)

    if now_utc >= expire_utc:
        mb.showerror("已过期", "文件损坏")
        root.destroy()
        sys.exit(0)

