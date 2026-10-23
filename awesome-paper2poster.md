# Awesome Paper2Poster

A curated list of resources around **paper-to-poster generation**: systems that turn scientific papers into posters, follow-up work, related paper-to-slides tools, benchmarks and evaluation, and useful building blocks.

Contributions are welcome — please open a PR to add a resource (one line per entry, with a short description).

## Contents

- [Start Here](#start-here)
- [Follow-up & Related Poster Systems](#follow-up--related-poster-systems)
- [Paper-to-Slides (Related)](#paper-to-slides-related)
- [Benchmarks & Evaluation](#benchmarks--evaluation)
- [Tools & Building Blocks](#tools--building-blocks)

## Start Here

- [Paper2Poster (this repo)](https://github.com/Paper2Poster/Paper2Poster) — PosterAgent: a top-down, visual-in-the-loop multi-agent system from `paper.pdf` to editable `poster.pptx`.
- [Paper (arXiv:2505.21497)](https://arxiv.org/abs/2505.21497) — *Paper2Poster: Multimodal Poster Automation from Scientific Papers*.
- [Project Page](https://paper2poster.github.io/) — overview, results and examples.
- [Dataset (Hugging Face)](https://huggingface.co/datasets/Paper2Poster/Paper2Poster) — conference papers paired with author-designed posters.
- [Demo (Hugging Face Spaces)](https://huggingface.co/spaces/camel-ai/Paper2Poster) — try Paper2Poster in the browser.
- [Agent SKILL](skills/) — lightweight skill for AI agents (Codex / Claude) to prepare poster-ready content from a paper, no dependency required.

## Follow-up & Related Poster Systems

- [Paper2Video](https://github.com/showlab/Paper2Video) — follow-up work: from a paper to a video presentation.
- [PosterMELD](https://github.com/Jackey0903/PosterMELD) — multi-agent paper-to-poster generation for controllable design diversity, with editable print-ready outputs.
- [ResearchStudio (paper2poster skill)](https://github.com/microsoft/ResearchStudio/blob/main/ResearchStudio-Reel/skills/paper2poster/README.md) — a paper2poster rendering skill in Microsoft's ResearchStudio pipeline (HTML + PDF + PNG + editable PPTX).

## Paper-to-Slides (Related)

- [PPTAgent](https://github.com/icip-cas/PPTAgent) — document-to-presentation generation and evaluation beyond text-to-slides (EMNLP 2025).
- [SlideGen](https://github.com/Y-Research-SBU/SlideGen) — collaborative multimodal agents for scientific slide generation from papers.
- [ArcDeck](https://github.com/RehgLab/ArcDeck) — narrative-driven paper-to-slide generation (ECCV 2026).

## Benchmarks & Evaluation

- [Paper2Poster Benchmark](https://huggingface.co/datasets/Paper2Poster/Paper2Poster) — the first benchmark and metric suite for poster generation: Visual Quality, Textual Coherence, VLM-as-Judge, and PaperQuiz.
- PaperQuiz — a poster is good if readers (VLMs as simulated readers) can answer questions about the paper after reading only the poster; introduced in [Paper2Poster](https://arxiv.org/abs/2505.21497).
- [PPTEval](https://aclanthology.org/2025.emnlp-main.728/) — presentation evaluation across Content, Design, and Coherence, from PPTAgent.

## Tools & Building Blocks

- [Docling](https://github.com/docling-project/docling) — PDF parsing and document conversion, for distilling a paper into a structured asset library.
- [MinerU](https://github.com/opendatalab/MinerU) — PDF extraction of text, figures, tables and formulas for downstream generation.
- [python-pptx](https://github.com/scanny/python-pptx) — programmatic PowerPoint generation, for building editable posters and slides.

---

Back to the [Paper2Poster README](README.md).
