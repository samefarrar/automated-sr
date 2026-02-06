# Automated Systematic Review Tool

An end-to-end systematic review automation tool using Large Language Models (LLMs) for screening and data extraction. Inspired by [Otto-SR](https://doi.org/10.1101/2025.06.13.25329541).

## Features

- **Multi-reviewer screening** - Configure multiple LLM reviewers with automatic tiebreaker resolution
- **Multi-provider support** - Use Anthropic, OpenAI, or OpenRouter via LiteLLM
- **OpenAlex integration** - Search scholarly works and retrieve open access PDFs
- **Zotero integration** - Import from Zotero, export for PDF retrieval, link downloaded PDFs
- **Full-text screening** - Screen articles using PDF content with document processing
- **Data extraction** - Extract structured data from included studies
- **Secondary filtering** - Filter extracted data by required fields, interventions, comparators
- **Meta-analysis** - Calculate pooled effects and generate forest plots
- **PRISMA flow tracking** - Automatic tracking of review progress

## Installation

Requires Python 3.13+.

```bash
# Clone the repository
git clone https://github.com/samefarrar/automated-sr.git
cd automated-sr

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

## Quick Start

### 1. Set up API keys

```bash
export ANTHROPIC_API_KEY="your-key-here"
# Optional: for OpenAI models
export OPENAI_API_KEY="your-key-here"
# Optional: for better OpenAlex rate limits
export OPENALEX_EMAIL="your-email@example.com"
```

### 2. Initialize a review

```bash
sr init my-review
```

### 3. Create a protocol

Create a YAML file defining your review protocol:

```yaml
# my-protocol.yaml
name: my-review
objective: |
  Evaluate the effectiveness of intervention X compared to control Y
  for outcome Z in population P.

inclusion_criteria:
  - Randomized controlled trials
  - Adult participants (18+ years)
  - Published in English

exclusion_criteria:
  - Conference abstracts only
  - Animal studies
  - Review articles

# Default model for single-reviewer screening
model: anthropic/claude-sonnet-4-5-20250929

# Data extraction variables (supported types: string, integer, float, boolean, list)
extraction_variables:
  - name: sample_size
    description: Total number of participants
    type: integer
  - name: effect_size
    description: Primary outcome effect size
    type: float
  - name: intervention
    description: Name of the intervention
    type: string
  - name: study_design
    description: Study design type
    type: string
    options:
      - RCT
      - cohort
      - case-control
      - cross-sectional
  - name: outcomes_measured
    description: Outcomes measured in the study
    type: list
  - name: blinded
    description: Whether the study was blinded
    type: boolean

# Multi-reviewer configuration (optional)
reviewers:
  - name: screener-1
    model: anthropic/claude-3-5-haiku-20241022
    api: anthropic
    prompt_template: rigorous
  - name: screener-2
    model: anthropic/claude-3-5-haiku-20241022
    api: anthropic
    prompt_template: sensitive
  - name: tiebreaker
    model: anthropic/claude-sonnet-4-5-20250929
    api: anthropic
    prompt_template: rigorous
    role: tiebreaker
```

Load the protocol:
```bash
sr init my-review --protocol my-protocol.yaml
```

### 4. Import citations

**From RIS file:**
```bash
sr import references.ris --review my-review
```

**From OpenAlex search:**
```bash
sr search-openalex "machine learning diagnosis" --review my-review --limit 500
```

**From Zotero:**
```bash
# List available collections first
sr zotero-collections

# Import from a collection
sr import zotero --review my-review --collection "My Collection"
```

### 5. Screen citations

**Single-reviewer abstract screening:**
```bash
sr screen-abstracts --review my-review
```

**Multi-reviewer abstract screening** (requires `reviewers` in protocol):
```bash
sr screen-multi --review my-review --stage abstract
```

### 6. Get PDFs for included citations

**Option A: Automatic download via OpenAlex (open access only):**
```bash
sr fetch-pdfs --review my-review
```

**Option B: Use Zotero for institutional access:**
```bash
# Export included citations to Zotero
sr export-to-zotero --review my-review --collection "SR Downloads" --included-only

# In Zotero: Right-click collection → "Find Available PDFs"
# Then link the PDFs back:
sr link-zotero-pdfs --review my-review --collection "SR Downloads"
```

**Option C: Import manually downloaded PDFs:**
```bash
# PDFs can have any filename - DOI is extracted automatically
sr import-pdfs --review my-review --dir ~/Downloads/pdfs
```

### 7. Full-text screening

**Single-reviewer:**
```bash
sr screen-fulltext --review my-review
```

**Multi-reviewer:**
```bash
sr screen-multi --review my-review --stage fulltext
```

### 8. Extract data

```bash
sr extract --review my-review
```

### 9. Apply secondary filters (optional)

Filter out extractions with missing required fields or ineligible interventions:
```bash
sr filter --review my-review --required "effect_size,sample_size"
sr filter --review my-review --interventions "drug_a,drug_b" --comparators "placebo"
```

### 10. Run meta-analysis

```bash
sr analyze --review my-review --effect SMD --model random --output ./results
```

### 11. Export results

```bash
# Export all results (screening decisions, extractions) to CSV and JSON
sr export --review my-review --output ./output

# Export specific format
sr export --review my-review --format csv
```

### 12. Check progress

```bash
sr status --review my-review
```

## Command Reference

| Command | Description |
|---------|-------------|
| `sr init` | Initialize a new review |
| `sr list` | List all reviews |
| `sr import` | Import citations from RIS file or Zotero |
| `sr search-openalex` | Search OpenAlex and import results |
| `sr screen-abstracts` | Single-reviewer abstract screening |
| `sr screen-fulltext` | Single-reviewer full-text screening |
| `sr screen-multi` | Multi-reviewer screening with tiebreaker |
| `sr fetch-pdfs` | Download open access PDFs via OpenAlex |
| `sr import-pdfs` | Import manually downloaded PDFs by DOI |
| `sr export-to-zotero` | Export citations to Zotero for PDF retrieval |
| `sr link-zotero-pdfs` | Link PDFs from Zotero collection to citations |
| `sr extract` | Extract data from included articles |
| `sr filter` | Apply secondary filters to extracted data |
| `sr analyze` | Run meta-analysis and generate forest plot |
| `sr export` | Export results to CSV/JSON |
| `sr status` | Show review progress and statistics |
| `sr zotero-collections` | List Zotero collections |
| `sr suggest-search` | Generate database-specific search strategies |

## Protocol YAML Reference

### Top-level fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Review name (must match the initialized review) |
| `objective` | Yes | Research question or objective (supports multi-line `\|`) |
| `inclusion_criteria` | Yes | List of inclusion criteria |
| `exclusion_criteria` | Yes | List of exclusion criteria |
| `model` | No | Default LLM model for single-reviewer screening |
| `extraction_variables` | No | List of variables to extract from included articles |
| `reviewers` | No | Multi-reviewer configuration (see below) |

### Extraction variables

Each variable supports:

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Variable name (used as the JSON key in extracted data) |
| `description` | Yes | What to extract — shown to the LLM in the prompt |
| `type` | No | `string` (default), `integer`, `float`, `boolean`, or `list` |
| `options` | No | Constrained list of valid values — shown to the LLM as guidance |

> **Note:** YAML auto-casts bare `yes`, `no`, `true`, `false` to booleans. Quote option values that start with these words: `"yes (confirmed)"`.

### Reviewer configuration

Each reviewer supports:

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | Yes | — | Reviewer identifier |
| `model` | Yes | — | LiteLLM model name (e.g. `anthropic/claude-3-5-haiku-20241022`) |
| `api` | Yes | — | Provider: `anthropic`, `openai`, or `openrouter` |
| `prompt_template` | No | `rigorous` | `rigorous`, `sensitive`, `specific`, or `custom` |
| `custom_prompt` | No | — | Custom prompt text (when template is `custom`) |
| `role` | No | `primary` | `primary` or `tiebreaker` |

## Multi-Reviewer Screening

The tool supports configurable multi-reviewer screening to improve accuracy:

- **Primary reviewers**: Screen independently using different prompt templates
- **Tiebreaker**: Automatically invoked when primary reviewers disagree
- **Prompt templates**:
  - `rigorous` - Strict interpretation, excludes when uncertain
  - `sensitive` - Lenient interpretation, includes when uncertain

Example output:
```
Citation: "Deep Learning for Cancer Diagnosis..."
  screener-1 (rigorous): EXCLUDE
  screener-2 (sensitive): INCLUDE
  tiebreaker: EXCLUDE (final decision)
```

## Search Strategy Generation

Generate database-specific search strategies using AI:

```bash
# From a research question
sr suggest-search "What is the effectiveness of exercise for chronic back pain?"

# From an existing review's objective
sr suggest-search --review my-review

# Target specific databases
sr suggest-search "..." -d pubmed -d scopus

# Save to JSON file
sr suggest-search "..." --output strategies.json
```

The command generates:
- **Concept decomposition** (Population, Intervention, Comparator, Outcome)
- **Database-specific syntax** for PubMed (MeSH), Scopus, Web of Science, OpenAlex
- **Multiple strategies** per database with sensitivity/specificity trade-offs

## Zotero Integration

The tool integrates with Zotero for PDF management:

1. **Import citations from Zotero**: Use existing Zotero libraries
2. **Export to Zotero**: Send included citations to Zotero for PDF retrieval
3. **Link PDFs**: Match Zotero PDFs back to review citations by DOI

This workflow is ideal for accessing paywalled articles via institutional access:

```bash
# After abstract screening, export included citations
sr export-to-zotero -r my-review -c "SR Full Texts" --included-only

# Use Zotero's "Find Available PDFs" with institutional login
# Then link the downloaded PDFs back
sr link-zotero-pdfs -r my-review -c "SR Full Texts"

# Now run full-text screening
sr screen-fulltext -r my-review
```

## Configuration

Configuration is stored in `~/.config/automated-sr/config.yaml`:

```yaml
anthropic_api_key: ${ANTHROPIC_API_KEY}
openai_api_key: ${OPENAI_API_KEY}
openalex_email: ${OPENALEX_EMAIL}
data_dir: ~/.local/share/automated-sr
default_model: anthropic/claude-sonnet-4-5-20250929
```

The database is stored at `.sr_data/reviews.db` in your current working directory.

## Model Names

This tool uses [LiteLLM](https://docs.litellm.ai/) for multi-provider support. Model names follow LiteLLM conventions:

| Provider | Model Name Example |
|----------|-------------------|
| Anthropic | `anthropic/claude-sonnet-4-5-20250929` |
| OpenAI | `openai/gpt-4.1` |
| OpenRouter | `openrouter/anthropic/claude-3.5-sonnet` |

## Project Structure

```
src/automated_sr/
├── analysis/          # Meta-analysis and forest plots
├── citations/         # RIS parsing and Zotero integration
├── extraction/        # Data extraction
├── llm/              # Multi-provider LLM abstraction (LiteLLM)
├── openalex/         # OpenAlex search and PDF retrieval
├── pdf/              # PDF processing and DOI extraction
├── prompts/          # Screening prompt templates
├── screening/        # Abstract and full-text screening
├── search/           # Search strategy generation
├── cli.py            # Command-line interface
├── config.py         # Configuration management
├── database.py       # SQLite database operations
└── models.py         # Pydantic data models
```

## Development

```bash
# Install dev dependencies
uv sync --group dev

# Run tests
uv run pytest

# Run linter
uv run ruff check .

# Run type checker
uv run pyright

# Format code
uv run ruff format .
```

## License

MIT License

## Acknowledgments

- Inspired by [Otto-SR](https://doi.org/10.1101/2025.06.13.25329541) by Cao et al.
- Uses [LiteLLM](https://github.com/BerriAI/litellm) for multi-provider LLM support
- Uses [OpenAlex](https://openalex.org/) for scholarly article metadata
