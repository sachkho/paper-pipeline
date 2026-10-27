"""Candidate sources: arXiv, bioRxiv, Semantic Scholar recommendations."""
from __future__ import annotations

import datetime as dt
import re

import feedparser

from .common import arxiv_id, http, paper_key, s2_headers

S2 = "https://api.semanticscholar.org"
S2_FIELDS = "paperId,title,abstract,externalIds,authors,publicationDate,openAccessPdf,url"


def _cand(**kw) -> dict:
    kw["key"] = paper_key(kw.get("arxiv"), kw.get("doi"), kw.get("title"))
    kw.setdefault("authors", [])
    kw["abstract"] = " ".join((kw.get("abstract") or "").split())
    kw["title"] = " ".join((kw.get("title") or "").split())
    return kw


# ---------------- arXiv ----------------

def parse_arxiv_feed(text: str, since: dt.date) -> list[dict]:
    feed = feedparser.parse(text)
    out = []
    for e in feed.entries:
        published = dt.date.fromisoformat(e.published[:10])
        if published < since:
            continue
        ax = arxiv_id(e.id)
        out.append(_cand(
            arxiv=ax,
            doi=getattr(e, "arxiv_doi", None),
            title=e.title,
            abstract=e.summary,
            authors=[a.name for a in getattr(e, "authors", [])],
            date=published.isoformat(),
            url=f"https://arxiv.org/abs/{ax}",
            pdf_url=f"https://arxiv.org/pdf/{ax}",
            source="arXiv",
        ))
    return out


def arxiv_search(query: str, since: dt.date, max_results: int) -> list[dict]:
    r = http("GET", "https://export.arxiv.org/api/query", pause=3.0, params={
        "search_query": query, "start": 0, "max_results": max_results,
        "sortBy": "submittedDate", "sortOrder": "descending",
    })
    r.raise_for_status()
    return parse_arxiv_feed(r.text, since)


def arxiv_title_search(title: str, max_results: int = 5) -> list[dict]:
    words = re.sub(r"[^A-Za-z0-9 ]+", " ", title).split()
    query = " AND ".join(f"ti:{w}" for w in words if len(w) > 2)[:900]
    r = http("GET", "https://export.arxiv.org/api/query", pause=3.0,
             params={"search_query": query, "max_results": max_results})
    r.raise_for_status()
    return parse_arxiv_feed(r.text, dt.date.min)


# ---------------- bioRxiv ----------------

def parse_biorxiv_rows(rows: list[dict], categories: set[str]) -> list[dict]:
    latest: dict[str, dict] = {}
    for row in rows:
        if row.get("category", "").strip().lower() not in categories:
            continue
        doi = row["doi"].lower()
        if doi in latest and int(latest[doi]["version"]) >= int(row["version"]):
            continue
        latest[doi] = row
    out = []
    for doi, row in latest.items():
        authors = [a.strip() for a in row.get("authors", "").split(";") if a.strip()]
        out.append(_cand(
            doi=doi,
            title=row["title"],
            abstract=row.get("abstract", ""),
            authors=authors,
            date=row.get("date", ""),
            url=f"https://www.biorxiv.org/content/{doi}v{row['version']}",
            pdf_url=f"https://www.biorxiv.org/content/{doi}v{row['version']}.full.pdf",
            source="bioRxiv",
        ))
    return out


def biorxiv_recent(since: dt.date, until: dt.date, categories: list[str]) -> list[dict]:
    cats = {c.lower() for c in categories}
    rows, cursor, total = [], 0, None
    while total is None or cursor < total:
        url = f"https://api.biorxiv.org/details/biorxiv/{since}/{until}/{cursor}"
        params = {"category": categories[0]} if len(categories) == 1 else None
        r = http("GET", url, params=params, pause=0.5)
        r.raise_for_status()
        data = r.json()
        batch = data.get("collection", [])
        if not batch:
            break
        rows.extend(batch)
        total = int(data["messages"][0].get("total", 0))
        cursor += len(batch)
    return parse_biorxiv_rows(rows, cats)


# ---------------- Semantic Scholar ----------------

def s2_to_cand(p: dict) -> dict:
    ext = p.get("externalIds") or {}
    return _cand(
        arxiv=ext.get("ArXiv"),
        doi=ext.get("DOI"),
        title=p.get("title"),
        abstract=p.get("abstract"),
        authors=[a.get("name", "") for a in (p.get("authors") or [])],
        date=p.get("publicationDate") or "",
        url=p.get("url") or "",
        pdf_url=(p.get("openAccessPdf") or {}).get("url") or (f"https://arxiv.org/pdf/{ext['ArXiv']}" if ext.get("ArXiv") else None),
        s2_id=p.get("paperId"),
        source="Semantic Scholar recommendation",
    )


def s2_recommendations(pos: list[str], neg: list[str], limit: int) -> list[dict]:
    if not pos:
        return []
    r = http("POST", f"{S2}/recommendations/v1/papers", pause=1.1, headers=s2_headers(),
             params={"fields": S2_FIELDS, "limit": limit},
             json={"positivePaperIds": pos[:100], "negativePaperIds": neg[:100]})
    if r.status_code != 200:
        print(f"[s2] recommendations failed: {r.status_code} {r.text[:200]}")
        return []
    return [s2_to_cand(p) for p in r.json().get("recommendedPapers", []) if p.get("title")]


def s2_resolve(arxiv: str | None, doi: str | None, title: str | None) -> str | None:
    """Find a Semantic Scholar paperId for a library item (cached by caller)."""
    ident = f"ARXIV:{arxiv}" if arxiv else (f"DOI:{doi}" if doi else None)
    if ident:
        r = http("GET", f"{S2}/graph/v1/paper/{ident}", pause=1.1, headers=s2_headers(),
                 params={"fields": "paperId"})
        if r.status_code == 200:
            return r.json().get("paperId")
    if title:
        r = http("GET", f"{S2}/graph/v1/paper/search/match", pause=1.1, headers=s2_headers(),
                 params={"query": title, "fields": "paperId,title"})
        if r.status_code == 200 and r.json().get("data"):
            return r.json()["data"][0]["paperId"]
    return None


def s2_match_full(title: str) -> dict | None:
    """Title lookup returning full metadata (used by bootstrap)."""
    r = http("GET", f"{S2}/graph/v1/paper/search/match", pause=1.1, headers=s2_headers(),
             params={"query": title, "fields": S2_FIELDS + ",venue"})
    if r.status_code == 200 and r.json().get("data"):
        return r.json()["data"][0]
    return None
