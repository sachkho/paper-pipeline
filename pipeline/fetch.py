"""Weekly step 1: sync with Zotero, gather candidates, rank, download full text.

Output: work/candidates.json (+ work/papers/<key>.pdf/.txt) for the Claude step.
"""
from __future__ import annotations

import datetime as dt
import io

import numpy as np
from pypdf import PdfReader

from . import pdfs, rank, sources, zotero_io as zio
from .common import (STATE, WORK, arxiv_id, folder_names, http, load_config, norm_title,
                     read_json, safe_name, write_json)


def download_text(cand: dict, max_chars: int) -> None:
    url = cand.get("pdf_url")
    if not url:
        return
    try:
        r = http("GET", url, retries=2, timeout=90)
        if r.status_code != 200 or not r.content.startswith(b"%PDF") or len(r.content) > 30e6:
            print(f"[pdf] skip {cand['key']}: status {r.status_code}")
            return
        reader = PdfReader(io.BytesIO(r.content))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:
        print(f"[pdf] failed {cand['key']}: {e}")
        return
    if len(text) < 2000:  # scanned or extraction failed
        return
    base = WORK / "papers" / safe_name(cand["key"])
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".pdf").write_bytes(r.content)
    base.with_suffix(".txt").write_text(text[:max_chars], encoding="utf-8")
    cand["pdf_path"] = str(base.with_suffix(".pdf"))
    cand["text_path"] = str(base.with_suffix(".txt").relative_to(WORK.parent))


def main() -> None:
    cfg = load_config()
    run = cfg["run"]
    today = dt.date.today()
    since = today - dt.timedelta(days=run["lookback_days"])
    folders = folder_names(cfg)
    tag = cfg["zotero"]["pipeline_tag"]

    # ---- Zotero sync ----
    zot = zio.connect()
    colls = zio.ensure_collections(zot, folders + [cfg["zotero"]["inbox"]])
    inbox = colls[cfg["zotero"]["inbox"]]
    moved = zio.clean_inbox(zot, inbox, {colls[f] for f in folders})
    print(f"[zotero] {moved} filed item(s) removed from Inbox")

    folder_items = {f: zio.collection_papers(zot, colls[f]) for f in folders}
    # Papers you add to a folder by hand get their arXiv PDF attached too.
    pdfs.backfill(zot, [it for f in folders for it in folder_items[f]], limit=10)
    library = zio.library_papers(zot)

    negatives = read_json(STATE / "negatives.json", {})
    for it in zio.trashed_pipeline_papers(zot, tag):
        d = it["data"]
        negatives.setdefault(zio.item_key(d), {"title": d.get("title", ""), "text": zio.item_text(d),
                                               "s2_id": zio.s2_id(d)})
    write_json(STATE / "negatives.json", negatives)

    seen = set(read_json(STATE / "seen.json", []))
    seen |= {zio.item_key(it["data"]) for it in library} | set(negatives)
    seen_titles = {norm_title(it["data"].get("title")) for it in library}
    seen_titles |= {norm_title(v["title"]) for v in negatives.values()}

    # ---- Semantic Scholar ids of your kept papers (cached) ----
    s2_cache = read_json(STATE / "s2_ids.json", {})
    budget = 40
    pos_ids = []
    for items in folder_items.values():
        for it in items:
            d = it["data"]
            k = zio.item_key(d)
            sid = zio.s2_id(d) or s2_cache.get(k)
            if sid is None and budget > 0:
                budget -= 1
                ax = arxiv_id(d.get("archiveID")) or arxiv_id(d.get("url"))
                try:
                    sid = sources.s2_resolve(ax, d.get("DOI"), d.get("title")) or ""
                    s2_cache[k] = sid
                except Exception as e:  # rate-limited: retry next week, don't crash
                    print(f"[s2] could not resolve '{d.get('title', '')[:60]}': {e}")
                    sid = None
            if sid:
                pos_ids.append(sid)
    write_json(STATE / "s2_ids.json", s2_cache)
    neg_ids = [v["s2_id"] for v in negatives.values() if v.get("s2_id")]

    # ---- gather candidates ----
    cands: list[dict] = []
    for f in cfg["folders"]:
        for q in f.get("arxiv_queries", []):
            try:
                got = sources.arxiv_search(q, since, run["arxiv_max_results"])
                print(f"[arxiv] {len(got):4d} from {q[:70]}")
                cands += got
            except Exception as e:
                print(f"[arxiv] query failed ({q[:50]}): {e}")
    try:
        got = sources.biorxiv_recent(since, today, cfg["biorxiv"]["categories"])
        print(f"[biorxiv] {len(got)}")
        cands += got
    except Exception as e:
        print(f"[biorxiv] failed: {e}")
    try:
        recs = sources.s2_recommendations(pos_ids, neg_ids, run["s2_recs_limit"])
        cutoff = (today - dt.timedelta(days=run["s2_recs_max_age_days"])).isoformat()
        recs = [c for c in recs if (c.get("date") or "0") >= cutoff]
        print(f"[s2] {len(recs)} recent recommendations")
        cands += recs
    except Exception as e:
        print(f"[s2] failed: {e}")

    uniq, titles = {}, set()
    for c in cands:
        nt = norm_title(c["title"])
        if not c["title"] or not c["abstract"] or c["key"] in seen or nt in seen_titles:
            continue
        if c["key"] in uniq or nt in titles:
            continue
        uniq[c["key"]] = c
        titles.add(nt)
    cands = list(uniq.values())
    print(f"[rank] {len(cands)} new unique candidates")

    # ---- rank ----
    folder_vecs = {}
    for f in cfg["folders"]:
        texts = [zio.item_text(it["data"]) for it in folder_items[f["name"]]] + [f["description"]]
        folder_vecs[f["name"]] = rank.embed(texts)
    neg_vecs = rank.embed([v["text"] for v in negatives.values()]) if negatives else np.zeros((0, 384))
    short = rank.rank(cands, folder_vecs, neg_vecs, run["negative_weight"], run["n_candidates"])

    # ---- full text ----
    for c in short:
        download_text(c, run["fulltext_chars"])
    n_txt = sum(1 for c in short if c.get("text_path"))
    print(f"[pdf] full text for {n_txt}/{len(short)}")

    write_json(WORK / "candidates.json", short)
    write_json(WORK / "meta.json", {"date": today.isoformat(), "folders": folders,
                                     "max_cards": run["max_cards"]})
    print(f"[done] {len(short)} candidates written to work/candidates.json")


if __name__ == "__main__":
    main()
