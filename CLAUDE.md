# Development Guidelines

This document contains critical information about working with this codebase. Follow these guidelines precisely.

## Core Development Rules

1. Package Management
   - ONLY use uv, NEVER pip
   - Installation: `uv add package`
   - Running tools: `uv run tool`
   - Upgrading: `uv add --dev package --upgrade-package package`
   - FORBIDDEN: `uv pip install`, `@latest` syntax

2. Code Quality
   - Type hints required for all code
   - Public APIs must have docstrings
   - Functions must be focused and small
   - Follow existing patterns exactly
   - Line length: 120 chars maximum

3. Testing Requirements
   - Framework: `uv run --frozen pytest`
   - Async testing: use anyio, not asyncio
   - Coverage: test edge cases and errors
   - New features require tests
   - Bug fixes require regression tests

- For commits fixing bugs or adding features based on user reports add:

  ```bash
  git commit --trailer "Reported-by:<name>"
  ```

  Where `<name>` is the name of the user.

- For commits related to a Github issue, add

  ```bash
  git commit --trailer "Github-Issue:#<number>"
  ```

- NEVER ever mention a `co-authored-by` or similar aspects. In particular, never
  mention the tool used to create the commit message or PR.

## Pull Requests

- Create a detailed message of what changed. Focus on the high level description of
  the problem it tries to solve, and how it is solved. Don't go into the specifics of the
  code unless it adds clarity.

- NEVER ever mention a `co-authored-by` or similar aspects. In particular, never
  mention the tool used to create the commit message or PR.

## Python Tools

## Code Formatting

1. Ruff
   - Format: `uv run --frozen ruff format .`
   - Check: `uv run --frozen ruff check .`
   - Fix: `uv run --frozen ruff check . --fix`
   - Critical issues:
     - Line length (88 chars)
     - Import sorting (I001)
     - Unused imports
   - Line wrapping:
     - Strings: use parentheses
     - Function calls: multi-line with proper indent
     - Imports: split into multiple lines

2. Type Checking
   - Tool: `uv run --frozen pyright`
   - Requirements:
     - Explicit None checks for Optional
     - Type narrowing for strings
     - Version warnings can be ignored if checks pass

3. Pre-commit
   - Config: `.pre-commit-config.yaml`
   - Runs: on git commit
   - Tools: Prettier (YAML/JSON), Ruff (Python)
   - Ruff updates:
     - Check PyPI versions
     - Update config rev
     - Commit config first

## Error Resolution

1. CI Failures
   - Fix order:
     1. Formatting
     2. Type errors
     3. Linting
   - Type errors:
     - Get full line context
     - Check Optional types
     - Add type narrowing
     - Verify function signatures

2. Common Issues
   - Line length:
     - Break strings with parentheses
     - Multi-line function calls
     - Split imports
   - Types:
     - Add None checks
     - Narrow string types
     - Match existing patterns
   - Pytest:
     - If the tests aren't finding the anyio pytest mark, try adding PYTEST_DISABLE_PLUGIN_AUTOLOAD=""
       to the start of the pytest run command eg:
       `PYTEST_DISABLE_PLUGIN_AUTOLOAD="" uv run --frozen pytest`

3. Best Practices
   - Check git status before commits
   - Run formatters before type checks
   - Keep changes minimal
   - Follow existing patterns
   - Document public APIs
   - Test thoroughly

## Data Architecture

- **Citation metadata** (authors, year, journal, DOI) comes from the import source
  (RIS file, Zotero, OpenAlex) and is authoritative. The exporter auto-populates
  `first_author` and `publication_year` CSV columns from this metadata.
- **Extraction variables** are for data that requires reading the full text (e.g.,
  sample sizes, methods, findings). Don't duplicate metadata fields as extraction
  variables — the LLM will guess wrong (e.g., picking ahead-of-print dates or
  authors from cited references).
- If citation metadata is missing (e.g., empty authors list), the exporter falls
  back to LLM-extracted values.

## Protocol YAML Gotchas

- **YAML auto-casts bare `yes`/`no`/`true`/`false` to booleans.** In option lists, always
  quote values that start with these words:
  ```yaml
  options:
    - "yes (IAIHG or equivalent)"   # Quoted — stays a string
    - no/unclear                     # OK — the slash prevents auto-cast
    - yes                            # BAD — becomes boolean True
  ```
  The parser coerces these back to strings, but quoting in the YAML is cleaner.
- Unknown fields in `extraction_variables` (e.g. `required`) are silently stripped
  during parsing. Only `name`, `description`, `type`, and `options` are used.
- Unknown top-level YAML keys are silently ignored. Extra metadata sections won't
  break parsing but won't be used by the tool either.

## Exception Handling

- **Always use `logger.exception()` instead of `logger.error()` when catching exceptions**
  - Don't include the exception in the message: `logger.exception("Failed")` not `logger.exception(f"Failed: {e}")`
- **Catch specific exceptions** where possible:
  - File ops: `except (OSError, PermissionError):`
  - JSON: `except json.JSONDecodeError:`
  - Network: `except (ConnectionError, TimeoutError):`
- **Only catch `Exception` for**:
  - Top-level handlers that must not crash
  - Cleanup blocks (log at debug level)
