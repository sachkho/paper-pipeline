"""Shared helpers: config, state files, HTTP with retries, paper keys."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
WORK = ROOT / "work"
UA = {"User-Agent": "paper-pipeline/1.0 (personal literature monitoring)"}


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def folder_names(cfg: dict) -> list[str]:
    return [f["name"] for f in cfg["folders"]]


# ---------- state ----------

def read_json(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


# ---------- keys ----------

_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


def arxiv_id(text: str | None) -> str | None:
    if not text:
        return None
    m = _ARXIV_RE.search(text)
    return m.group(1) if m else None


def norm_title(title: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def paper_key(arxiv: str | None = None, doi: str | None = None, title: str | None = None) -> str:
    """Stable identifier used for dedup and file names."""
    if arxiv:
        return f"arxiv:{arxiv}"
    if doi:
        return f"doi:{doi.lower()}"
    return f"title:{norm_title(title)[:80]}"


def safe_name(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", key)


# ---------- http ----------

def http(method: str, url: str, *, retries: int = 4, pause: float = 0.0, **kw) -> requests.Response:
    headers = {**UA, **kw.pop("headers", {})}
    timeout = kw.pop("timeout", 60)
    last = None
    for attempt in range(retries):
        if pause:
            time.sleep(pause)
        try:
            r = requests.request(method, url, headers=headers, timeout=timeout, **kw)
        except requests.RequestException as e:  # network hiccup
            last = e
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = RuntimeError(f"{r.status_code} on {url}")
            time.sleep(2 ** (attempt + 1))
            continue
        return r
    raise RuntimeError(f"giving up on {url}: {last}")


def s2_headers() -> dict:
    key = os.environ.get("S2_API_KEY")
    return {"x-api-key": key} if key else {}
