"""Attach PDFs to papers in your folders that only have metadata (e.g. seed imports)."""
from __future__ import annotations

from .common import WORK, arxiv_id, http, safe_name


def _has_pdf(zot, item_key: str) -> bool:
    for ch in zot.children(item_key):
        d = ch["data"]
        if d.get("itemType") == "attachment" and d.get("contentType") == "application/pdf":
            return True
    return False


def _arxiv_of(data: dict) -> str | None:
    for field in ("archiveID", "url", "extra", "DOI"):
        ax = arxiv_id(data.get(field))
        if ax:
            return ax
    return None


def backfill(zot, papers: list[dict], limit: int = 50) -> None:
    attached, no_source = 0, []
    out = WORK / "backfill"
    out.mkdir(parents=True, exist_ok=True)
    for it in papers:
        if attached >= limit:
            break
        d = it["data"]
        if _has_pdf(zot, it["key"]):
            continue
        ax = _arxiv_of(d)
        if not ax:
            no_source.append(d.get("title", it["key"]))
            continue
        try:
            r = http("GET", f"https://arxiv.org/pdf/{ax}", retries=3, timeout=90, pause=3.0)
            if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                no_source.append(d.get("title", it["key"]))
                continue
            path = out / f"{safe_name(ax)}.pdf"
            path.write_bytes(r.content)
            zot.attachment_simple([str(path)], parentid=it["key"])
            attached += 1
            print(f"[pdf] attached: {d.get('title', '')[:80]}")
        except Exception as e:
            print(f"[pdf] failed for {d.get('title', '')[:60]}: {e}")
    print(f"[pdf] {attached} PDF(s) attached")
    if no_source:
        print("[pdf] no open-access arXiv PDF for these — in Zotero desktop use "
              "right-click → 'Find Full Text', or attach your own copy:")
        for t in no_source:
            print(f"  - {t}")
