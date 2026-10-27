"""Offline tests: parsing, ranking, card validation, Zotero item building (no network)."""
import datetime as dt
import json

import numpy as np
import pytest

from pipeline import push, rank, sources, zotero_io as zio
from pipeline.common import paper_key

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
 <entry>
  <id>http://arxiv.org/abs/2610.01234v2</id>
  <published>2026-10-24T17:00:00Z</published>
  <title>World Models
   for Doom</title>
  <summary>We train a world model on ViZDoom.</summary>
  <author><name>A. Author</name></author><author><name>B. Author</name></author>
  <arxiv:doi>10.1234/xyz</arxiv:doi>
 </entry>
 <entry>
  <id>http://arxiv.org/abs/2601.00001v1</id>
  <published>2026-01-02T00:00:00Z</published>
  <title>Old paper</title><summary>old</summary>
 </entry>
</feed>"""


def test_arxiv_parse_filters_by_date_and_normalises():
    out = sources.parse_arxiv_feed(ATOM, dt.date(2026, 10, 20))
    assert len(out) == 1
    c = out[0]
    assert c["arxiv"] == "2610.01234" and c["key"] == "arxiv:2610.01234"
    assert c["title"] == "World Models for Doom"
    assert c["authors"] == ["A. Author", "B. Author"]
    assert c["pdf_url"].endswith("2610.01234")


def test_biorxiv_keeps_latest_version_and_category():
    rows = [
        {"doi": "10.1101/2026.10.01.1", "version": "1", "category": "neuroscience", "title": "T", "abstract": "a", "authors": "X, Y.; Z, W."},
        {"doi": "10.1101/2026.10.01.1", "version": "2", "category": "neuroscience", "title": "T", "abstract": "a2", "authors": "X, Y."},
        {"doi": "10.1101/2026.10.02.2", "version": "1", "category": "genomics", "title": "G", "abstract": "g", "authors": ""},
    ]
    out = sources.parse_biorxiv_rows(rows, {"neuroscience"})
    assert len(out) == 1 and out[0]["abstract"] == "a2" and out[0]["url"].endswith("v2")


def test_s2_to_cand_prefers_arxiv_key():
    c = sources.s2_to_cand({"paperId": "a" * 40, "title": "P", "abstract": "x",
                            "externalIds": {"ArXiv": "2501.00002", "DOI": "10.5/ABC"}, "authors": [{"name": "N"}]})
    assert c["key"] == "arxiv:2501.00002" and c["s2_id"] == "a" * 40


def test_rank_quota_and_negatives(monkeypatch):
    # fake embedding: deterministic vectors keyed by first word
    basis = {"rl": [1, 0, 0], "neuro": [0, 1, 0], "ethics": [0, 0, 1]}
    def fake_embed(texts):
        v = np.array([basis.get(t.split()[0].lower().strip("."), [0.3, 0.3, 0.3]) for t in texts], float)
        return v / np.linalg.norm(v, axis=1, keepdims=True)
    monkeypatch.setattr(rank, "embed", fake_embed)
    cands = [{"key": f"k{i}", "title": w, "abstract": "x"} for i, w in
             enumerate(["rl"] * 10 + ["neuro"] * 2 + ["ethics"])]
    fv = {"RL": fake_embed(["rl"]), "Neuro": fake_embed(["neuro"]), "Ethics": fake_embed(["ethics"])}
    out = rank.rank(cands, fv, np.zeros((0, 3)), 0.5, n=6)
    folders = [c["suggested_folder"] for c in out]
    assert len(out) == 6 and "Neuro" in folders and "Ethics" in folders
    # a binned 'rl' paper should push rl candidates down
    out2 = rank.rank([dict(c) for c in cands], fv, fake_embed(["rl"]), 0.5, n=13)
    assert out2[0]["suggested_folder"] != "RL"


def test_item_key_and_s2_id():
    d = {"title": "X", "archiveID": "arXiv:2610.01234", "extra": "S2: " + "b" * 40}
    assert zio.item_key(d) == "arxiv:2610.01234"
    assert zio.s2_id(d) == "b" * 40
    assert zio.item_key({"title": "Hello, World!", "DOI": "10.1/AB"}) == "doi:10.1/ab"


def test_load_cards_validates(tmp_path, monkeypatch):
    monkeypatch.setattr(push, "WORK", tmp_path)
    (tmp_path / "cards").mkdir()
    good = {"key": "arxiv:1", "folder": "Neuro", "verdict": "read", "priority": 2, "tldr": "t"}
    badfolder = {**good, "key": "arxiv:2", "folder": "Nope", "priority": 1}
    unknown = {**good, "key": "arxiv:999"}
    for i, c in enumerate([good, badfolder, unknown]):
        (tmp_path / "cards" / f"{i}.json").write_text(json.dumps(c))
    (tmp_path / "cards" / "broken.json").write_text("{not json")
    cands = {"arxiv:1": {"score": 0.5}, "arxiv:2": {"score": 0.4, "suggested_folder": "RL"}}
    cards = push.load_cards(cands, ["RL", "Neuro"], 10)
    assert [c["key"] for c in cards] == ["arxiv:2", "arxiv:1"]  # priority 1 first
    assert cards[0]["folder"] == "RL"                           # invalid folder repaired


class FakeZot:
    def __init__(self):
        self.created, self.attached, self.removed = [], [], []
    def item_template(self, t):
        if t == "note":
            return {"itemType": "note", "note": ""}
        return {"itemType": t, "title": "", "creators": [], "abstractNote": "", "url": "", "date": "",
                "DOI": "", "archiveID": "", "repository": "", "extra": "", "collections": [], "tags": []}
    def create_items(self, items, parentid=None):
        self.created.append((items[0], parentid))
        return {"successful": {"0": {"key": f"K{len(self.created)}"}}}
    def attachment_simple(self, files, parentid=None):
        self.attached.append((files, parentid))
    def deletefrom_collection(self, coll, item):
        self.removed.append(item["key"])
    def everything(self, x):
        return x
    def collection_items_top(self, key):
        return [{"key": "A", "data": {"itemType": "preprint", "collections": ["INBOX", "F1"]}},
                {"key": "B", "data": {"itemType": "preprint", "collections": ["INBOX"]}},
                {"key": "N", "data": {"itemType": "note", "collections": ["INBOX", "F1"]}}]


def test_create_paper_and_clean_inbox(tmp_path):
    z = FakeZot()
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    cand = {"key": "arxiv:2610.01234", "title": "T", "authors": ["A"], "abstract": "ab", "url": "u",
            "date": "2026-10-24", "arxiv": "2610.01234", "source": "arXiv", "score": 0.7,
            "s2_id": "c" * 40, "pdf_path": str(pdf)}
    card = {"key": cand["key"], "folder": "RL", "verdict": "read", "priority": 1, "tldr": "<b>x</b> & y"}
    key = zio.create_paper(z, cand, card, "INBOX", "pipeline")
    item, _ = z.created[0]
    assert key == "K1" and item["collections"] == ["INBOX"]
    assert item["archiveID"] == "arXiv:2610.01234" and item["extra"].startswith("S2: ")
    assert {"tag": "suggest:RL"} in item["tags"]
    note, parent = z.created[1]
    assert parent == "K1" and "&lt;b&gt;x&lt;/b&gt; &amp; y" in note["note"]
    assert z.attached == [([str(pdf)], "K1")]
    assert zio.clean_inbox(z, "INBOX", {"F1"}) == 1 and z.removed == ["A"]


def test_paper_key_fallbacks():
    assert paper_key(None, None, "A  Title: v2!") == "title:a title v2"


def test_pdf_backfill(monkeypatch, tmp_path):
    from pipeline import pdfs
    monkeypatch.setattr(pdfs, "WORK", tmp_path)
    class R:
        status_code = 200
        content = b"%PDF-1.5 data"
    monkeypatch.setattr(pdfs, "http", lambda *a, **k: R())
    class Z:
        attached = []
        def children(self, key):
            return [{"data": {"itemType": "attachment", "contentType": "application/pdf"}}] if key == "HAS" else []
        def attachment_simple(self, files, parentid=None):
            self.attached.append(parentid)
    z = Z()
    papers = [{"key": "HAS", "data": {"title": "a", "url": "https://arxiv.org/abs/2301.04104"}},
              {"key": "AX", "data": {"title": "b", "extra": "S2: x\narXiv: 2301.04104"}},
              {"key": "NO", "data": {"title": "c", "DOI": "10.1038/nature06976"}}]
    pdfs.backfill(z, papers)
    assert z.attached == ["AX"]
