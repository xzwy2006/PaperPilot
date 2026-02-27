# PaperPilot

> Desktop systematic review tool with AI-assisted data extraction

## Features

- **Import**: CSV and RIS (with PaperPilot enhanced fields for round-trip continuity)
- **Deduplication**: Three-tier algorithm (exact ID / title+year+author / fuzzy) with evidence tracking
- **Screening**: Rule-based auto-screening + manual decision with reason codes (TA001–TA010)
- **PDF Management**: Link/copy PDFs, full-text extraction with section detection
- **AI Extraction**: Structured data extraction via OpenAI / Ollama / compatible APIs
- **AI Standardization**: Normalize extracted values to consistent units and formats
- **Export**: RIS (with screening history embedded) and Excel (4 sheets with color coding)
- **Meta-Analysis**: Random-effects model via R/metafor with subgroup support

## Requirements

- Python 3.10+
- PySide6 6.6+
- R + metafor package (optional, for meta-analysis)

## Installation

```bash
pip install -e ".[all]"
```

## Usage

```bash
paperpilot
# or
python -m paperpilot.app
```

## Development

```bash
pip install -e ".[dev]"
make test
make lint
```

## Architecture

```
paperpilot/
├── core/
│   ├── db.py           # SQLite connection + WAL mode
│   ├── models.py       # Pydantic models
│   ├── repositories.py # Data access layer
│   ├── project.py      # Project open/create
│   ├── importers/      # CSV + RIS importers
│   ├── dedup/          # D1/D2/D3 dedup algorithm
│   ├── screening/      # Protocol + rules engine + scorer
│   ├── exporters/      # RIS + Excel exporters
│   ├── pdf/            # PDF manager + text extractor
│   ├── ai/             # AI providers + extraction + standardization
│   └── meta/           # Meta-analysis data prep + R runner
└── ui/
    ├── main_window.py  # Navigation + record table
    └── pages/          # One page per workflow step
```

## License

MIT
