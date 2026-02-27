# PaperPilot

Desktop systematic review tool built with Python + PySide6.

## Stack
- **UI**: PySide6
- **DB**: SQLite
- **PDF**: pdfplumber
- **Dedup**: rapidfuzz
- **Export**: openpyxl (Excel), RIS
- **Meta-analysis**: R (metafor)
- **AI**: OpenAI-compat / Anthropic (pluggable providers)

## Phases
- Phase 0: Scaffold + Templates + Tooling ✅
- Phase 1: SQLite DB + Migrations + Repositories
- Phase 2: Project System + Main Window + Record Table
- Phase 3: Importers (CSV + RIS)
- Phase 4: Local Dedup + AI Dedup Validation
- Phase 5: Local Screening + AI Screening Validation
- Phase 6: Exporters (RIS + Excel)
- Phase 7: AI Provider Manager
- Phase 8: PDF Manager + AI Extraction
- Phase 9: AI Text Standardization
- Phase 10: Meta Analysis CSV + R Runner
- Phase 11: End-to-End Tests

## Install

```bash
pip install -e .
```

## Run

```bash
python -m paperpilot.app
# or
paperpilot
```
