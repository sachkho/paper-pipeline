"""Embedding-based ranking of candidates against your Zotero folders."""
from __future__ import annotations

import numpy as np

_MODEL = None
MODEL_NAME = "BAAI/bge-small-en-v1.5"


def embed(texts: list[str]) -> np.ndarray:
    global _MODEL
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    if _MODEL is None:
        from fastembed import TextEmbedding
        _MODEL = TextEmbedding(MODEL_NAME)
    vecs = np.array(list(_MODEL.embed([t[:2000] for t in texts])), dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True).clip(min=1e-9)


def folder_scores(cand: np.ndarray, folder_vecs: dict[str, np.ndarray], k: int = 3) -> dict[str, np.ndarray]:
    """Mean of the top-k cosine similarities between each candidate and a folder's papers."""
    out = {}
    for name, F in folder_vecs.items():
        if len(F) == 0:
            continue
        sims = cand @ F.T                        # (n_cand, n_folder)
        kk = min(k, sims.shape[1])
        out[name] = np.sort(sims, axis=1)[:, -kk:].mean(axis=1)
    return out


def rank(cands: list[dict], folder_vecs: dict[str, np.ndarray], neg_vecs: np.ndarray,
         neg_weight: float, n: int) -> list[dict]:
    if not cands:
        return []
    C = embed([f"{c['title']}. {c['abstract']}" for c in cands])
    scores = folder_scores(C, folder_vecs)
    names = list(scores)
    S = np.stack([scores[nm] for nm in names], axis=1)   # (n_cand, n_folders)
    best = S.max(axis=1)
    penalty = (C @ neg_vecs.T).max(axis=1) if len(neg_vecs) else np.zeros(len(cands))
    final = best - neg_weight * np.clip(penalty - 0.5, 0, None)  # only penalise close matches
    for i, c in enumerate(cands):
        c["score"] = float(final[i])
        c["suggested_folder"] = names[int(S[i].argmax())]
        c["folder_scores"] = {nm: round(float(S[i, j]), 3) for j, nm in enumerate(names)}
    ordered = sorted(cands, key=lambda c: c["score"], reverse=True)
    # Reserve a few slots per folder so one busy area can't crowd out the others.
    quota = max(1, n // (2 * len(names)))
    picked, seen = [], set()
    for nm in names:
        for c in [c for c in ordered if c["suggested_folder"] == nm][:quota]:
            picked.append(c)
            seen.add(c["key"])
    for c in ordered:
        if len(picked) >= n:
            break
        if c["key"] not in seen:
            picked.append(c)
            seen.add(c["key"])
    return sorted(picked[:n], key=lambda c: c["score"], reverse=True)
