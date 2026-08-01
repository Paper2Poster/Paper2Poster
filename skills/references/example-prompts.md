# Example Prompts

## Codex: full package

```text
Use $paper2poster-poster to turn `paper.pdf` into a 48x36 research poster package. Produce `poster_brief.md`, `poster_copy.md`, `poster_layout.md`, `poster_runbook.md`, and a draft `poster.yaml`. Keep the copy concise, emphasize the strongest quantitative results, and do not invent unsupported claims.
```

## Codex: Paper2Poster execution focused

```text
Use $paper2poster-poster to prepare this paper for the Paper2Poster pipeline. I want a repo-ready folder structure, a `poster.yaml` draft, and the exact `python -m PosterAgent.new_pipeline` command I should run. Assume NeurIPS-style branding unless the paper suggests otherwise.
```

## Claude: full package

```text
Follow the workflow in `skills/SKILL.md` and the reference files in `skills/references/`. Turn this paper into a poster package with a brief, poster-ready copy, a layout plan, and a runbook. Keep every technical claim grounded in the source paper.
```

## Claude: content only

```text
Using the local `skills/` instructions as the workflow, convert this paper into concise poster copy only. I want a title block, motivation, method, results, conclusion, and a short QR/contact placeholder. Optimize for scanability rather than completeness.
```
