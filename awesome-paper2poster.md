# Awesome Paper2Poster [![Awesome](https://cdn.rawgit.com/sindresorhus/awesome/d7305f38d29fed78fa85652e3a63e154dd8e8829/media/badge.svg)](https://github.com/sindresorhus/awesome) <!-- omit in toc -->
A curated list of methods, benchmarks, agent skills and tools for turning scientific papers into posters, together with closely related paper-to-slides, paper-to-video and paper-to-webpage work.

<p align="center">
<img src="assets/teaser.jpeg" width="720px"/>
</p>

<p align="center">
(Source: <a href="https://paper2poster.github.io/">Paper2Poster</a>.)
</p>

Contributions are welcome — please open a PR following the entry format below.

## Table of Contents <!-- omit in toc -->
- [Paper2Poster Family](#paper2poster-family)
- [Paper-to-Poster Methods](#paper-to-poster-methods)
- [Benchmarks and Datasets](#benchmarks-and-datasets)
- [Agent Skills](#agent-skills)
- [Paper-to-Slides](#paper-to-slides)
- [Paper-to-Video](#paper-to-video)
- [Paper-to-Webpage](#paper-to-webpage)
- [Tools and Building Blocks](#tools-and-building-blocks)

### Paper2Poster Family

+ [Paper2Poster: Multimodal Poster Automation from Scientific Papers (NeurIPS 2025 D&B)](https://arxiv.org/abs/2505.21497)  
  [![Star](https://img.shields.io/github/stars/Paper2Poster/Paper2Poster.svg?style=social&label=Star)](https://github.com/Paper2Poster/Paper2Poster)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2505.21497)
  [![Website](https://img.shields.io/badge/Website-9cf)](https://paper2poster.github.io/)
  [![Dataset](https://img.shields.io/badge/Dataset-orange)](https://huggingface.co/datasets/Paper2Poster/Paper2Poster)
  [![Demo](https://img.shields.io/badge/Demo-blue)](https://huggingface.co/spaces/camel-ai/Paper2Poster)  
  PosterAgent: a top-down, visual-in-the-loop multi-agent system from `paper.pdf` to an editable `poster.pptx`, plus the first poster benchmark with the PaperQuiz metric.

+ [Paper2Video: Automatic Video Generation from Scientific Papers](https://arxiv.org/abs/2510.05096)  
  [![Star](https://img.shields.io/github/stars/showlab/Paper2Video.svg?style=social&label=Star)](https://github.com/showlab/Paper2Video)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2510.05096)
  [![Website](https://img.shields.io/badge/Website-9cf)](https://showlab.github.io/Paper2Video/)  
  Follow-up work: PaperTalker generates presentation videos (slides, subtitles, cursor, speech, talking head); benchmark of 101 paper–video pairs.

+ [Paper2Poster SKILL](https://github.com/Paper2Poster/Paper2Poster/tree/main/skills)  
  [![Star](https://img.shields.io/github/stars/Paper2Poster/Paper2Poster.svg?style=social&label=Star)](https://github.com/Paper2Poster/Paper2Poster)  
  Lightweight, dependency-free skill for AI agents (Codex / Claude) to prepare poster-ready content from a paper.

### Paper-to-Poster Methods

+ [PosterGen: Aesthetic-Aware Multi-Modal Paper-to-Poster Generation via Multi-Agent LLMs (CVPR 2026 Findings)](https://arxiv.org/abs/2508.17188)  
  [![Star](https://img.shields.io/github/stars/Y-Research-SBU/PosterGen.svg?style=social&label=Star)](https://github.com/Y-Research-SBU/PosterGen)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2508.17188)  
  Design-principle-guided agents (Parser, Curator, Layout, Color, Font, Renderer) producing editable PPTX posters.

+ [P2P: Automated Paper-to-Poster Generation and Fine-Grained Benchmark (ICLR 2026)](https://arxiv.org/abs/2505.17104)  
  [![Star](https://img.shields.io/github/stars/multimodal-art-projection/P2P.svg?style=social&label=Star)](https://github.com/multimodal-art-projection/P2P)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2505.17104)  
  Three agents with checker modules generate HTML-rendered posters; releases P2PInstruct and P2PEval.

+ [PosterMELD: Multi-Agent Paper-to-Poster Generation for Controllable Design Diversity](https://imhaojie.github.io/PosterMELD/)  
  [![Star](https://img.shields.io/github/stars/imhaojie/PosterMELD.svg?style=social&label=Star)](https://github.com/imhaojie/PosterMELD)
  [![Website](https://img.shields.io/badge/Website-9cf)](https://imhaojie.github.io/PosterMELD/)  
  Template-capacity-aware writing with editable, print-ready PowerPoint posters across 24 templates.

+ [PostDoc: Generating Poster from a Long Multimodal Document Using Deep Submodular Optimization (AAAI 2025)](https://arxiv.org/abs/2405.20213)  
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2405.20213)  
  Deep submodular content selection for coverage, diversity and text–image alignment, then LLM paraphrasing and template generation.

+ [Learning to Generate Posters of Scientific Papers (AAAI 2016)](https://arxiv.org/abs/1604.01219)  
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/1604.01219)  
  The first data-driven poster generation work: graphical models infer panel layout and attributes; releases the Poster-Paper dataset.

### Benchmarks and Datasets

+ [Paper2Poster Benchmark (NeurIPS 2025 D&B)](https://huggingface.co/datasets/Paper2Poster/Paper2Poster)  
  [![Dataset](https://img.shields.io/badge/Dataset-orange)](https://huggingface.co/datasets/Paper2Poster/Paper2Poster)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2505.21497)  
  Papers paired with author-designed posters; evaluates Visual Quality, Textual Coherence, VLM-as-Judge and PaperQuiz.

+ [P2PEval & P2PInstruct (ICLR 2026)](https://huggingface.co/datasets/ASC8384/P2PEval)  
  [![Dataset](https://img.shields.io/badge/P2PEval-orange)](https://huggingface.co/datasets/ASC8384/P2PEval)
  [![Dataset](https://img.shields.io/badge/P2PInstruct-orange)](https://huggingface.co/datasets/ASC8384/P2PInstruct)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2505.17104)  
  121 paper–poster pairs with 1,738 human-annotated checklist items, plus a 30K+ instruction dataset.

+ [SciPostLayout: A Dataset for Layout Analysis and Layout Generation of Scientific Posters](https://arxiv.org/abs/2407.19787)  
  [![Star](https://img.shields.io/github/stars/omron-sinicx/scipostlayout.svg?style=social&label=Star)](https://github.com/omron-sinicx/scipostlayout)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2407.19787)
  [![Dataset](https://img.shields.io/badge/Dataset-orange)](https://huggingface.co/datasets/omron-sinicx/scipostlayout_v2)  
  7,855 CC-BY posters with manual layout annotations and 100 paper–poster pairs.

+ [PosterSum: A Multimodal Benchmark for Scientific Poster Summarization (IJCNLP-AACL 2025 Findings)](https://arxiv.org/abs/2502.17540)  
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2502.17540)
  [![Dataset](https://img.shields.io/badge/Dataset-orange)](https://huggingface.co/datasets/rohitsaxena/PosterSum)  
  16,305 ICLR / ICML / NeurIPS posters paired with abstracts, for poster understanding and summarization.

### Agent Skills

+ [Paper2Poster SKILL](https://github.com/Paper2Poster/Paper2Poster/tree/main/skills)  
  [![Star](https://img.shields.io/github/stars/Paper2Poster/Paper2Poster.svg?style=social&label=Star)](https://github.com/Paper2Poster/Paper2Poster)  
  Turn a paper into a poster package from Codex or Claude, e.g. `Use $paper2poster-poster to turn this paper into a poster package.`

+ [ResearchStudio — paper2poster skill](https://github.com/microsoft/ResearchStudio/blob/main/ResearchStudio-Reel/skills/paper2poster/README.md)  
  [![Star](https://img.shields.io/github/stars/microsoft/ResearchStudio.svg?style=social&label=Star)](https://github.com/microsoft/ResearchStudio)  
  Rendering stage of Microsoft's ResearchStudio: fits paper assets into a print-ready poster (HTML, PDF, PNG and editable PPTX).

+ [ArcDeck skill](https://github.com/RehgLab/ArcDeck/tree/main/arcdeck-skill)  
  [![Star](https://img.shields.io/github/stars/RehgLab/ArcDeck.svg?style=social&label=Star)](https://github.com/RehgLab/ArcDeck)
  [![Website](https://img.shields.io/badge/Website-9cf)](https://arcdeck.org)  
  ArcDeck's narrative-driven paper-to-slides pipeline packaged as Claude skills.

+ [Anthropic Agent Skills — pptx](https://github.com/anthropics/skills/tree/main/skills/pptx)  
  [![Star](https://img.shields.io/github/stars/anthropics/skills.svg?style=social&label=Star)](https://github.com/anthropics/skills)  
  Reference skill for creating, editing and reading `.pptx` files — a useful base for poster and slide agents.

### Paper-to-Slides

+ [PPTAgent: Generating and Evaluating Presentations Beyond Text-to-Slides (EMNLP 2025)](https://arxiv.org/abs/2501.03936)  
  [![Star](https://img.shields.io/github/stars/icip-cas/PPTAgent.svg?style=social&label=Star)](https://github.com/icip-cas/PPTAgent)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2501.03936)  
  Edit-based generation from reference decks, with the PPTEval framework (Content, Design, Coherence).

+ [ArcDeck: Narrative-Driven Paper-to-Slide Generation (ECCV 2026)](https://arcdeck.org)  
  [![Star](https://img.shields.io/github/stars/RehgLab/ArcDeck.svg?style=social&label=Star)](https://github.com/RehgLab/ArcDeck)
  [![Website](https://img.shields.io/badge/Website-9cf)](https://arcdeck.org)  
  Plans slides around the paper's discourse structure; releases the ArcBench benchmark.

+ [SlideGen: Collaborative Multimodal Agents for Scientific Slide Generation](https://arxiv.org/abs/2512.04529)  
  [![Star](https://img.shields.io/github/stars/Y-Research-SBU/SlideGen.svg?style=social&label=Star)](https://github.com/Y-Research-SBU/SlideGen)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2512.04529)  
  Outliner, Mapper, Formulizer, Arranger, Speaker and Refiner agents produce editable PPTX slides.

+ [AutoPresent: Designing Structured Visuals from Scratch (CVPR 2025)](https://arxiv.org/abs/2501.00912)  
  [![Star](https://img.shields.io/github/stars/para-lost/AutoPresent.svg?style=social&label=Star)](https://github.com/para-lost/AutoPresent)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2501.00912)  
  Program-based slide generation with an 8B model and the SlidesBench benchmark.

### Paper-to-Video

+ [Paper2Video: Automatic Video Generation from Scientific Papers](https://arxiv.org/abs/2510.05096)  
  [![Star](https://img.shields.io/github/stars/showlab/Paper2Video.svg?style=social&label=Star)](https://github.com/showlab/Paper2Video)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2510.05096)
  [![Website](https://img.shields.io/badge/Website-9cf)](https://showlab.github.io/Paper2Video/)  
  PaperTalker agent and the Paper2Video benchmark with Meta Similarity, PresentArena, PresentQuiz and IP Memory.

+ [PresentAgent: Multimodal Agent for Presentation Video Generation (EMNLP 2025 Demo)](https://arxiv.org/abs/2507.04036)  
  [![Star](https://img.shields.io/github/stars/AIGeeksGroup/PresentAgent.svg?style=social&label=Star)](https://github.com/AIGeeksGroup/PresentAgent)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2507.04036)  
  Turns long documents into narrated presentation videos; evaluated with PresentEval.

### Paper-to-Webpage

+ [Paper2Web: Let's Make Your Paper Alive!](https://arxiv.org/abs/2510.15842)  
  [![Star](https://img.shields.io/github/stars/YuhangChen1/Paper2All.svg?style=social&label=Star)](https://github.com/YuhangChen1/Paper2All)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/2510.15842)  
  PWAgent turns papers into interactive project homepages; the Paper2All codebase also covers posters and PR materials.

+ [AutoPage](https://github.com/AutoLab-SAI-SJTU/AutoPage)  
  [![Star](https://img.shields.io/github/stars/AutoLab-SAI-SJTU/AutoPage.svg?style=social&label=Star)](https://github.com/AutoLab-SAI-SJTU/AutoPage)  
  Human-in-the-loop multi-agent generation of project webpages, with the PageBench evaluation.

### Tools and Building Blocks

+ [Docling](https://github.com/docling-project/docling)  
  [![Star](https://img.shields.io/github/stars/docling-project/docling.svg?style=social&label=Star)](https://github.com/docling-project/docling)  
  PDF parsing and document conversion into structured text, figures and tables.

+ [MinerU](https://github.com/opendatalab/MinerU)  
  [![Star](https://img.shields.io/github/stars/opendatalab/MinerU.svg?style=social&label=Star)](https://github.com/opendatalab/MinerU)  
  High-quality PDF extraction of text, figures, tables and formulas.

+ [python-pptx](https://github.com/scanny/python-pptx)  
  [![Star](https://img.shields.io/github/stars/scanny/python-pptx.svg?style=social&label=Star)](https://github.com/scanny/python-pptx)  
  Programmatic PowerPoint generation for editable posters and slides.

---

**Entry format** — add one entry per work:

```markdown
+ [Title (Venue Year)](paper-link)  
  [![Star](https://img.shields.io/github/stars/OWNER/REPO.svg?style=social&label=Star)](https://github.com/OWNER/REPO)
  [![arXiv](https://img.shields.io/badge/arXiv-b31b1b.svg)](https://arxiv.org/abs/XXXX.XXXXX)
  [![Website](https://img.shields.io/badge/Website-9cf)](project-page)  
  One-line description.
```

Back to the [Paper2Poster README](README.md).
