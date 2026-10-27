"""Weekly step 3: turn Claude's cards into Zotero items in the Inbox."""
from __future__ import annotations

import json

from . import zotero_io as zio
from .common import STATE, WORK, folder_names, load_config, read_json, write_json

REQUIRED = ("key", "folder", "verdict", "priority", "tldr")


def load_cards(cands: dict[str, dict], folders: list[str], max_cards: int) -> list[dict]:
    cards = []
    for path in sorted((WORK / "cards").glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[push] unreadable card {path.name}: {e}")
            continue
        if any(k not in card for k in REQUIRED):
            print(f"[push] incomplete card {path.name}")
            continue
        if card["key"] not in cands:
            print(f"[push] card for unknown key {card['key']} — ignored")
            continue
        if card["folder"] not in folders:
            card["folder"] = cands[card["key"]].get("suggested_folder", folders[0])
        cards.append(card)
    cards.sort(key=lambda c: (int(c.get("priority", 3)), -cands[c["key"]].get("score", 0)))
    return cards[:max_cards]


def main() -> None:
    cfg = load_config()
    cands = {c["key"]: c for c in read_json(WORK / "candidates.json", [])}
    if not cands:
        print("[push] no candidates this week")
        return
    folders = folder_names(cfg)
    cards = load_cards(cands, folders, cfg["run"]["max_cards"])

    zot = zio.connect()
    inbox = zio.ensure_collections(zot, [cfg["zotero"]["inbox"]])[cfg["zotero"]["inbox"]]
    created = 0
    for card in cards:
        try:
            zio.create_paper(zot, cands[card["key"]], card, inbox, cfg["zotero"]["pipeline_tag"])
            created += 1
        except Exception as e:
            print(f"[push] failed {card['key']}: {e}")
    print(f"[push] {created}/{len(cards)} cards added to Zotero Inbox")

    # Everything shortlisted this week is marked seen, carded or not,
    # so rejected papers don't come back next week.
    seen = set(read_json(STATE / "seen.json", [])) | set(cands)
    write_json(STATE / "seen.json", sorted(seen))
    history = read_json(STATE / "history.json", [])
    history.append({"date": read_json(WORK / "meta.json", {}).get("date"),
                    "shortlisted": len(cands), "carded": len(cards), "created": created})
    write_json(STATE / "history.json", history)


if __name__ == "__main__":
    main()
