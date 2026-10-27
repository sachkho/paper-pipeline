You are triaging this week's research papers for one researcher. Work only with the files in this repository; do not invent papers, results or numbers.

## Inputs
- `config.yaml`: read `project_context` (who the reader is and what they work on) and `folders` (each folder's `name` and `description`, which is its relevance rubric).
- `work/meta.json`: `max_cards` is the maximum number of cards to write.
- `work/candidates.json`: the shortlist. Each entry has `key`, `title`, `abstract`, `authors`, `date`, `source`, `suggested_folder` (from embedding similarity, often but not always right), and `text_path` when full text is available.

## Procedure
1. Read `config.yaml`, `work/meta.json` and `work/candidates.json`. From titles and abstracts alone, choose at most `max_cards` papers that this reader should see. Judge against the project context and folder rubrics, not general interest. Prefer papers that would change what the reader does or reads next. It is fine to choose fewer if the week is weak; never pad.
2. For each chosen paper, if it has a `text_path`, read that file (it may be truncated) before writing. Otherwise work from the abstract and say so in `limitations`.
3. Write one file per chosen paper to `work/cards/<n>.json` (n = 01, 02, …), containing exactly this JSON object:

```json
{
  "key": "<the candidate's key, copied exactly>",
  "folder": "<one folder name from config.yaml, copied exactly>",
  "verdict": "read" | "skim" | "skip",
  "priority": 1 | 2 | 3,
  "tldr": "2 sentences: what they did and what they found.",
  "contribution": "The actual new thing (method, dataset, result), concretely.",
  "data_and_methods": "Data/modality (fMRI, MEG, game, benchmark…), subjects or environments, model, evaluation.",
  "relevance": "Why it matters (or doesn't) for this reader's project specifically. Name the connection.",
  "limitations": "Main weaknesses or caveats; note if you only had the abstract."
}
```

Field rules:
- `verdict`: "read" = should read in full; "skim" = know it exists, read figures/abstract; "skip" = included only because it looked relevant but isn't. Use "skip" sparingly — if it's skip, usually just don't write a card.
- `priority`: 1 = this week, 2 = soon, 3 = backlog.
- Plain English, no hype, no adjectives like "groundbreaking". Each text field at most ~80 words.
- Do not quote more than a short phrase from any paper; summarize in your own words.

When all cards are written, stop. Do not modify any other file.
