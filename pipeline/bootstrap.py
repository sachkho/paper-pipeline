"""One-time: create the Zotero collections and import the seed papers in seeds.yaml."""
from __future__ import annotations

import yaml

from . import sources, zotero_io as zio
from .common import ROOT, folder_names, load_config, norm_title


def _overlap(a: str, b: str) -> float:
    """Word-set similarity, to reject S2 'best matches' that are actually other papers."""
    A, B = set(norm_title(a).split()), set(norm_title(b).split())
    return len(A & B) / max(1, len(A | B))


def main() -> None:
    cfg = load_config()
    folders = folder_names(cfg)
    with open(ROOT / "seeds.yaml", encoding="utf-8") as f:
        seeds = yaml.safe_load(f) or {}

    zot = zio.connect()
    colls = zio.ensure_collections(zot, folders + [cfg["zotero"]["inbox"]])
    have = {norm_title(it["data"].get("title")) for it in zio.library_papers(zot)}

    missing = []
    for folder, titles in seeds.items():
        if folder not in colls:
            print(f"[bootstrap] '{folder}' is not in config.yaml folders — skipped")
            continue
        for title in titles or []:
            p = sources.s2_match_full(title)
            if not p or _overlap(title, p.get("title", "")) < 0.6:
                missing.append(title)
                continue
            if norm_title(p["title"]) in have:
                print(f"[bootstrap] already in library: {p['title']}")
                continue
            c = sources.s2_to_cand(p)
            try:
                item = zot.item_template("journalArticle")
                item["title"] = c["title"]
                item["creators"] = [{"creatorType": "author", "name": a} for a in c["authors"][:30]]
                item["abstractNote"] = c["abstract"]
                item["url"] = c["url"]
                item["date"] = c["date"]
                item["DOI"] = c.get("doi") or ""
                item["publicationTitle"] = p.get("venue") or ("arXiv" if c.get("arxiv") else "")
                extra = [f"S2: {c['s2_id']}"]
                if c.get("arxiv"):
                    extra.append(f"arXiv: {c['arxiv']}")
                item["extra"] = "\n".join(extra)
                item["collections"] = [colls[folder]]
                resp = zot.create_items([item])
                if resp.get("successful"):
                    have.add(norm_title(c["title"]))
                    print(f"[bootstrap] + {folder}: {c['title']}")
                else:
                    print(f"[bootstrap] rejected: {title}: {resp.get('failed')}")
            except Exception as e:
                print(f"[bootstrap] error on '{title}': {e}")

    if missing:
        print("\n[bootstrap] NOT FOUND on Semantic Scholar — add these by hand:")
        for t in missing:
            print(f"  - {t}")


if __name__ == "__main__":
    main()
