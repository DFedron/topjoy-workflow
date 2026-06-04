import json
import os


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

