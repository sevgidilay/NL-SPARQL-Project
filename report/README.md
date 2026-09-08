# Report

LaTeX source for the KOS course project report.

## Structure

```
report/
  main.tex              — entry point (title page, TOC, section inputs, bibliography)
  references.bib        — BibTeX references
  sections/             — one .tex file per section
  *.pdf                 — compiled output (stays in this folder)
```

## Compile

```bash
cd report
latexmk -pdf main.tex
```

Or manually:

```bash
pdflatex main.tex
biber main
pdflatex main.tex
pdflatex main.tex
```

Clean auxiliary files:

```bash
latexmk -c
```
