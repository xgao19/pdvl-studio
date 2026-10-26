from __future__ import annotations
import json
import os
import tomllib
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


def codex_runtime() -> dict:
    """Only PDVL's private runtime config; never read the user's Codex login/config."""
    directory = (home() / 'codex').resolve()
    try:
        if directory == (Path.home() / '.codex').resolve():
            raise ValueError()
        cfg = tomllib.loads((directory / 'config.toml').read_text(encoding='utf-8'))
        provider = cfg['model_provider']
        definition = cfg['model_providers'][provider]
        model, base, key = cfg['model'], definition['base_url'], definition['env_key']
        if not all(isinstance(value, str) and value for value in (provider, model, base, key)):
            raise ValueError()
        if provider in ('openai', 'ollama', 'lmstudio'):
            raise ValueError()
        if definition.get('wire_api', 'responses') != 'responses' or definition.get('requires_openai_auth', False):
            raise ValueError()
        if 'auth' in definition or 'experimental_bearer_token' in definition:
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('Configure the isolated Codex provider in PDVL_HOME/codex/config.toml using env_key and Responses') from None
    return {'home': str(directory), 'model': model, 'provider': provider,
            'name': definition.get('name', provider), 'base_url': base.rstrip('/'), 'env_key': key}


def codex_public() -> dict:
    try:
        runtime = codex_runtime()
    except ValueError as error:
        return {'configured': False, 'available': False, 'detail': str(error)}
    return {'configured': True, 'available': bool(os.getenv(runtime['env_key'])),
            'model': runtime['model'], 'provider': runtime['provider'], 'title': runtime['name']}


def codex_environment(runtime: dict) -> dict:
    """A child-only environment: no inherited app login, session, or OpenAI key overrides."""
    names = {'PATH', 'HOME', 'USER', 'LOGNAME', 'SHELL', 'TMPDIR', 'TMP', 'TEMP', 'LANG',
             'SYSTEMROOT', 'WINDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY'}
    env = {key: value for key, value in os.environ.items() if key in names or key.startswith('LC_')}
    key = os.getenv(runtime['env_key'])
    if not key:
        raise ValueError('Missing API key for the isolated Codex provider')
    env.update({runtime['env_key']: key, 'CODEX_HOME': runtime['home'], 'CODEX_SQLITE_HOME': runtime['home']})
    return env
