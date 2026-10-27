# paper-pipeline

Weekly literature monitoring for the Digital Brain Project. Every Sunday evening a GitHub Action:

1. **Syncs with Zotero.** Reads the papers in your folders (positive examples) and the pipeline papers you trashed (negative examples). Removes from the Inbox anything you've already filed.
2. **Gathers candidates** from the past 7 days: arXiv queries per folder, bioRxiv neuroscience, and Semantic Scholar recommendations seeded with your kept/binned papers.
3. **Ranks them locally** by embedding similarity to each folder (no LLM), keeps the top 30, downloads the PDFs.
4. **Has Claude (your subscription, via Claude Code) read them** and write at most 15 cards: TL;DR, contribution, data & methods, relevance to the project, limitations, a verdict and a suggested folder.
5. **Pushes the cards into Zotero's `Inbox`** as items with the PDF attached and the card as a note.

## Smash or pass (on the iPad)

Open the **Inbox** collection in Zotero.

| You want to | Do this |
|---|---|
| **Keep** | Add the item to a folder collection (long-press → *Add to Collection*). The next run removes it from the Inbox. |
| **Bin** | Move it to the Trash. The next run records it as a negative example, so similar papers rank lower. |
| **Decide later** | Leave it in the Inbox. |

Each card's suggested folder is shown as a `suggest:<folder>` tag, and its priority (1 = read this week) as a `priority:<n>` tag.

## Setup (once, ~15 minutes)

1. **Repository.** Push this folder to a private GitHub repo.
2. **Zotero API key.** On zotero.org → Settings → Security → *Applications* (`zotero.org/settings/keys`):
   - Note **your user ID** (the number shown as *"Your user ID for use in API calls"*).
   - *Create new private key* with **Allow library access**, **Allow notes access** and **Allow write access**.
3. **Claude token.** On your laptop, with Claude Code installed, run `claude setup-token` and copy the token it prints (it starts with `sk-ant-oat01-`). It draws on your Claude subscription, not API billing, and lasts about a year.
4. **(Optional) Semantic Scholar API key.** It works without one but is rate-limited; request one from Semantic Scholar's API page if runs start failing on `[s2]`.
5. **Secrets.** In the GitHub repo: Settings → Secrets and variables → Actions → *New repository secret*:
   - `ZOTERO_USER_ID`
   - `ZOTERO_API_KEY`
   - `CLAUDE_CODE_OAUTH_TOKEN`
   - `S2_API_KEY` (optional)
6. **Seed your library.** Edit `seeds.yaml` (uncomment what you want), then Actions → *Bootstrap Zotero (run once)* → *Run workflow*. Check the log for titles it couldn't find and add those by hand.
7. **First run.** Actions → *Weekly papers* → *Run workflow*. Afterwards it runs by itself every Sunday at 16:41 UTC.

## Tuning

Everything lives in `config.yaml`:

- `folders`: names (must match Zotero collections), rubric descriptions, arXiv queries. Add a folder here and it's created in Zotero on the next run.
- `run.max_cards`, `run.n_candidates`: volume.
- `run.fulltext_chars`: how much of each PDF Claude reads. This is the main lever on subscription usage.

## Notes

- **Zotero storage.** The free tier gives 300 MB, roughly 100–150 papers. Trashed items still count until you empty the Trash; negatives are already recorded by then.
- **bioRxiv PDFs** are sometimes blocked for automated downloads. Those cards are written from the abstract, and the card says so.
- **Debugging.** Each run uploads its shortlist and cards as a workflow artifact (kept 30 days).
- **State** (`state/`) is committed back to the repo: what has been seen, your negatives, cached Semantic Scholar IDs, a run history.
