from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def home() -> Path:
    raw = Path(os.getenv("PDVL_HOME", str(ROOT / ".local"))).expanduser()
    p = raw if raw.is_absolute() else ROOT / raw
    p.mkdir(parents=True, exist_ok=True)
    return p

def model_settings() -> dict:
    path = Path(os.getenv("PDVL_MODELS_FILE", str(ROOT / "configs/models.json")))
    data = json.loads(path.read_text(encoding="utf-8"))
    for m in data["models"]:
        if m["model"].startswith("${") and m["model"].endswith("}"):
            m["model"] = os.getenv(m["model"][2:-1], "local-model")
    return data

PROVIDER_ENV = {
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1"),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com"),
    "custom": ("CUSTOM_API_KEY", None),
}

def provider_key(model: dict) -> str | None:
    return os.getenv(PROVIDER_ENV[model["provider"]][0]) or None

def provider_base(model: dict) -> str:
    return (os.getenv("CUSTOM_API_BASE") if model["provider"] == "custom"
            else PROVIDER_ENV[model["provider"]][1]) or ""
