"""Thin layer over pyzotero for the operations the pipeline needs."""
from __future__ import annotations

import html
import os
import re

from pyzotero import zotero

from .common import arxiv_id, paper_key

SKIP_TYPES = {"note", "attachment", "annotation"}


def connect() -> zotero.Zotero:
    uid = os.environ.get("ZOTERO_USER_ID", "").strip()
    key = os.environ.get("ZOTERO_API_KEY", "").strip()
    if not uid.isdigit():
        raise SystemExit(
            "ZOTERO_USER_ID is missing or not a number. Add it as a repository secret "
            "(the numeric 'user ID for use in API calls' on zotero.org/settings/keys, not your username).")
    if not key:
        raise SystemExit("ZOTERO_API_KEY is missing. Add it as a repository secret.")
    return zotero.Zotero(uid, "user", key)


def ensure_collections(zot, names: list[str]) -> dict[str, str]:
    """Return {name: collection_key}, creating any missing top-level collection."""
    existing = {c["data"]["name"]: c["key"] for c in zot.everything(zot.collections())}
    for name in names:
        if name not in existing:
            resp = zot.create_collections([{"name": name}])
            existing[name] = resp["successful"]["0"]["key"]
            print(f"[zotero] created collection '{name}'")
    return {n: existing[n] for n in names}


def _papers(items: list[dict]) -> list[dict]:
    return [it for it in items if it["data"].get("itemType") not in SKIP_TYPES]


def collection_papers(zot, coll_key: str) -> list[dict]:
    return _papers(zot.everything(zot.collection_items_top(coll_key)))


def library_papers(zot) -> list[dict]:
    return _papers(zot.everything(zot.top()))


def trashed_pipeline_papers(zot, tag: str) -> list[dict]:
    items = _papers(zot.everything(zot.trash()))
    return [it for it in items if any(t["tag"] == tag for t in it["data"].get("tags", []))]


def item_key(data: dict) -> str:
    ax = arxiv_id(data.get("archiveID")) or arxiv_id(data.get("url")) or arxiv_id(data.get("extra"))
    if not ax and "arxiv" in (data.get("DOI") or "").lower():
        ax = arxiv_id(data["DOI"])
    return paper_key(arxiv=ax, doi=data.get("DOI") or None, title=data.get("title"))


def s2_id(data: dict) -> str | None:
    m = re.search(r"^S2:\s*([0-9a-f]{40})", data.get("extra") or "", re.M)
    return m.group(1) if m else None


def item_text(data: dict) -> str:
    return f"{data.get('title', '')}. {data.get('abstractNote', '')}".strip()


def clean_inbox(zot, inbox_key: str, folder_keys: set[str]) -> int:
    """Items you filed into a folder are removed from the Inbox automatically."""
    moved = 0
    for it in collection_papers(zot, inbox_key):
        if folder_keys & set(it["data"].get("collections", [])):
            zot.deletefrom_collection(inbox_key, it)
            moved += 1
    return moved


# ---------- writing ----------

def _creators(authors: list[str]) -> list[dict]:
    return [{"creatorType": "author", "name": a} for a in authors[:30]]


def _note_html(card: dict, cand: dict) -> str:
    def p(label, text):
        return f"<p><strong>{label}.</strong> {html.escape(str(text or '—'))}</p>"

    return (
        f"<h2>Pipeline card — {html.escape(card.get('verdict', '').upper())}"
        f" · priority {card.get('priority', '?')}</h2>"
        + p("TL;DR", card.get("tldr"))
        + p("Contribution", card.get("contribution"))
        + p("Data & methods", card.get("data_and_methods"))
        + p("Why it matters here", card.get("relevance"))
        + p("Limitations", card.get("limitations"))
        + p("Suggested folder", card.get("folder"))
        + f"<p><em>Source: {html.escape(cand.get('source', ''))} · ranking score "
        f"{cand.get('score', 0):.3f} · summary from {'full text' if cand.get('pdf_path') else 'abstract only'}</em></p>"
    )


def create_paper(zot, cand: dict, card: dict, inbox_key: str, tag: str) -> str:
    try:
        item = zot.item_template("preprint")
    except Exception:  # very old servers: fall back
        item = zot.item_template("journalArticle")
    item["title"] = cand["title"]
    item["creators"] = _creators(cand.get("authors", []))
    item["abstractNote"] = cand.get("abstract", "")
    item["url"] = cand.get("url", "")
    item["date"] = cand.get("date", "")
    if "DOI" in item and cand.get("doi"):
        item["DOI"] = cand["doi"]
    if "archiveID" in item and cand.get("arxiv"):
        item["archiveID"] = f"arXiv:{cand['arxiv']}"
    if "repository" in item:
        item["repository"] = cand.get("source", "")
    extra = [f"Pipeline-key: {cand['key']}"]
    if cand.get("s2_id"):
        extra.insert(0, f"S2: {cand['s2_id']}")
    item["extra"] = "\n".join(extra)
    item["collections"] = [inbox_key]
    item["tags"] = [
        {"tag": tag},
        {"tag": f"suggest:{card.get('folder', '')}"},
        {"tag": f"priority:{card.get('priority', '')}"},
    ]
    resp = zot.create_items([item])
    if not resp.get("successful"):
        raise RuntimeError(f"Zotero rejected item {cand['key']}: {resp.get('failed')}")
    key = resp["successful"]["0"]["key"]

    note = zot.item_template("note")
    note["note"] = _note_html(card, cand)
    zot.create_items([note], parentid=key)

    if cand.get("pdf_path") and os.path.exists(cand["pdf_path"]):
        try:
            zot.attachment_simple([cand["pdf_path"]], parentid=key)
        except Exception as e:  # storage full etc. — keep the item anyway
            print(f"[zotero] PDF upload failed for {cand['key']}: {e}")
    return key
