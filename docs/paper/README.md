# Neovarch Agent — technical report

**[Read the PDF](neovarch-agent.pdf)** · LaTeX source: [`neovarch-agent.tex`](neovarch-agent.tex) · references: [`references.bib`](references.bib)

*Neovarch Agent: A Local-First, Phone-Controlled Coding Agent with a Lean, Verification-Gated Harness* —
Muhammad Maftuh (NeovarchLabs), October 2026. English, with an Indonesian abstract.

The report describes `main` at commit `88a67fc` (v1.4.8 plus the unreleased Tempest lean turns, PR #59):
architecture (core, desktop, Android remote, LAN/Tailscale/relay pairing), lineage and licensing (see also
[`NOTICE`](../../NOTICE)), the Tempest harness, codemode and lean turns, safety and approvals, and the benchmarks
that were actually run, with their limits.

## Contents

| Path | What |
|---|---|
| `neovarch-agent.tex` | LaTeX source |
| `neovarch-agent.pdf` | compiled report |
| `references.bib` | BibTeX references |
| `figures/make_figures.py` | regenerates every chart (matplotlib) from `data/` |
| `figures/*.pdf` | the charts |
| `data/bench10_combined.csv` | 10-task set, both rounds combined, per arm |
| `data/hard_r1.csv` | harder set, round 1 (partial), per run |

## Build

```bash
cd docs/paper
python3 figures/make_figures.py      # needs matplotlib
pdflatex neovarch-agent && bibtex neovarch-agent && pdflatex neovarch-agent && pdflatex neovarch-agent
```

Needs a TeX Live with `tikz`, `booktabs`, `natbib`, `microtype`, `lmodern`.
