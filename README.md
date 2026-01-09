# Automated Systematic Review Tool

An end-to-end systematic review automation tool using Large Language Models (LLMs) for screening and data extraction. Inspired by [Otto-SR](https://doi.org/10.1101/2025.06.13.25329541).

## Features

- **Multi-reviewer screening** - Configure multiple LLM reviewers with automatic tiebreaker resolution
- **Multi-provider support** - Use Anthropic, OpenAI, or OpenRouter via LiteLLM
- **OpenAlex integration** - Search scholarly works and retrieve open access PDFs
- **PDF import with DOI extraction** - Import manually downloaded PDFs by extracting DOIs
- **Full-text screening** - Screen articles using PDF content with Claude's document processing
- **Data extraction** - Extract structured data from included studies
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

extraction_variables:
  - name: sample_size
    description: Total number of participants
    type: integer
  - name: effect_size
    description: Primary outcome effect size
    type: float

# Multi-reviewer configuration
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

```bash
sr set-protocol my-review -p my-protocol.yaml
```

### 4. Import citations

From OpenAlex:
```bash
sr search-openalex "machine learning diagnosis" --review my-review --limit 500
```

From RIS file:
```bash
sr import-ris references.ris --review my-review
```

From Zotero:
```bash
sr import-zotero --review my-review --collection "My Collection"
```

### 5. Screen citations

Abstract screening with multiple reviewers:
```bash
sr screen-multi --review my-review --stage abstract
```

Fetch PDFs for included articles:
```bash
sr fetch-pdfs --review my-review
```

Import manually downloaded PDFs:
```bash
sr import-pdfs --review my-review --dir ~/Downloads/pdfs
```

Full-text screening:
```bash
sr screen-fulltext --review my-review
```

### 6. Extract data

```bash
sr extract --review my-review
```

### 7. Run meta-analysis

```bash
sr analyze --review my-review --effect SMD --model random --output ./results
```

### 8. Check progress

```bash
sr status --review my-review
```

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

## PDF Import

For articles not available as open access, you can manually download PDFs and import them:

```bash
# PDFs can have any filename - DOI is extracted automatically
sr import-pdfs --review my-review --dir ~/Downloads/

# Uses regex first, falls back to Claude Haiku for DOI extraction
# Matches extracted DOIs against citations in the review
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
