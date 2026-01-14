"""SQLite database persistence layer for systematic reviews."""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from automated_sr.models import (
    Citation,
    ExtractionResult,
    ReviewProtocol,
    ReviewStats,
    ScreeningDecision,
    ScreeningResult,
)

logger = logging.getLogger(__name__)

SCHEMA = """
-- Reviews table
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    protocol_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Citations table
CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY,
    review_id INTEGER REFERENCES reviews(id),
    source TEXT,
    source_key TEXT,
    title TEXT,
    authors TEXT,
    abstract TEXT,
    year INTEGER,
    doi TEXT,
    journal TEXT,
    pdf_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(review_id, title)
);

-- Abstract screening results (with reviewer_name for multi-reviewer support)
CREATE TABLE IF NOT EXISTS abstract_screening (
    id INTEGER PRIMARY KEY,
    citation_id INTEGER REFERENCES citations(id),
    decision TEXT CHECK(decision IN ('include', 'exclude', 'uncertain')),
    reasoning TEXT,
    model TEXT,
    reviewer_name TEXT,
    screened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(citation_id, reviewer_name)
);

-- Full-text screening results (with reviewer_name for multi-reviewer support)
CREATE TABLE IF NOT EXISTS fulltext_screening (
    id INTEGER PRIMARY KEY,
    citation_id INTEGER REFERENCES citations(id),
    decision TEXT CHECK(decision IN ('include', 'exclude', 'uncertain')),
    reasoning TEXT,
    pdf_error TEXT,
    model TEXT,
    reviewer_name TEXT,
    screened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(citation_id, reviewer_name)
);

-- Extraction results
CREATE TABLE IF NOT EXISTS extractions (
    id INTEGER PRIMARY KEY,
    citation_id INTEGER UNIQUE REFERENCES citations(id),
    extracted_data TEXT,
    model TEXT,
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Screening consensus (for multi-reviewer mode)
CREATE TABLE IF NOT EXISTS screening_consensus (
    id INTEGER PRIMARY KEY,
    citation_id INTEGER REFERENCES citations(id),
    stage TEXT CHECK(stage IN ('abstract', 'fulltext')),
    consensus_decision TEXT CHECK(consensus_decision IN ('include', 'exclude', 'uncertain')),
    required_tiebreaker BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(citation_id, stage)
);

-- Secondary filtering results
CREATE TABLE IF NOT EXISTS secondary_filters (
    id INTEGER PRIMARY KEY,
    citation_id INTEGER REFERENCES citations(id),
    passed BOOLEAN,
    reason TEXT,
    details TEXT,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_citations_review ON citations(review_id);
CREATE INDEX IF NOT EXISTS idx_abstract_screening_citation ON abstract_screening(citation_id);
CREATE INDEX IF NOT EXISTS idx_fulltext_screening_citation ON fulltext_screening(citation_id);
CREATE INDEX IF NOT EXISTS idx_extractions_citation ON extractions(citation_id);
CREATE INDEX IF NOT EXISTS idx_screening_consensus_citation ON screening_consensus(citation_id);
CREATE INDEX IF NOT EXISTS idx_secondary_filters_citation ON secondary_filters(citation_id);
"""

MIGRATIONS = """
-- Add reviewer_name column if it doesn't exist (for backward compatibility)
-- Note: SQLite doesn't support IF NOT EXISTS for ALTER TABLE, so we handle this in code
"""


class Database:
    """SQLite database manager for systematic reviews."""

    def __init__(self, db_path: Path) -> None:
        """Initialize the database connection."""
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the database connection, creating it if necessary."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        """Initialize the database schema."""
        self.conn.executescript(SCHEMA)
        self._run_migrations()
        self.conn.commit()

    def _run_migrations(self) -> None:
        """Run database migrations for backward compatibility."""
        # Add reviewer_name column to abstract_screening if missing
        self._add_column_if_missing("abstract_screening", "reviewer_name", "TEXT")
        # Add reviewer_name column to fulltext_screening if missing
        self._add_column_if_missing("fulltext_screening", "reviewer_name", "TEXT")
        # Add unique indexes to prevent duplicates (for existing databases)
        self._add_unique_indexes()

    def _add_column_if_missing(self, table: str, column: str, col_type: str) -> None:
        """Add a column to a table if it doesn't exist."""
        cursor = self.conn.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cursor.fetchall()]
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            logger.info("Added column %s to table %s", column, table)

    def _add_unique_indexes(self) -> None:
        """Add unique indexes to prevent duplicates (for existing databases without constraints)."""
        # Remove duplicates first, keeping the most recent record
        self._remove_duplicates("citations", ["review_id", "title"])
        self._remove_duplicates("abstract_screening", ["citation_id", "reviewer_name"])
        self._remove_duplicates("fulltext_screening", ["citation_id", "reviewer_name"])
        self._remove_duplicates("extractions", ["citation_id"])
        self._remove_duplicates("screening_consensus", ["citation_id", "stage"])

        # Create unique indexes if they don't exist
        indexes = [
            ("idx_citations_unique", "citations", "review_id, title"),
            ("idx_abstract_screening_unique", "abstract_screening", "citation_id, reviewer_name"),
            ("idx_fulltext_screening_unique", "fulltext_screening", "citation_id, reviewer_name"),
            ("idx_extractions_unique", "extractions", "citation_id"),
            ("idx_screening_consensus_unique", "screening_consensus", "citation_id, stage"),
        ]
        for idx_name, table, columns in indexes:
            try:
                self.conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} ON {table}({columns})")
            except sqlite3.IntegrityError:
                # Index might already exist or duplicates remain
                logger.warning("Could not create unique index %s - duplicates may exist", idx_name)

    def _remove_duplicates(self, table: str, unique_columns: list[str]) -> None:
        """Remove duplicate rows from a table, keeping the most recent."""
        import contextlib

        cols = ", ".join(unique_columns)
        with contextlib.suppress(sqlite3.OperationalError):
            self.conn.execute(f"""
                DELETE FROM {table} WHERE rowid NOT IN (
                    SELECT MAX(rowid) FROM {table} GROUP BY {cols}
                )
            """)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # Review operations
    def create_review(self, name: str, protocol_path: Path | None = None) -> int:
        """Create a new review and return its ID."""
        cursor = self.conn.execute(
            "INSERT INTO reviews (name, protocol_path) VALUES (?, ?)",
            (name, str(protocol_path) if protocol_path else None),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_review(self, review_id: int) -> dict | None:
        """Get a review by ID."""
        cursor = self.conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_review_by_name(self, name: str) -> dict | None:
        """Get a review by name."""
        cursor = self.conn.execute("SELECT * FROM reviews WHERE name = ?", (name,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_reviews(self) -> list[dict]:
        """List all reviews."""
        cursor = self.conn.execute("SELECT * FROM reviews ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]

    def get_protocol(self, review_id: int) -> ReviewProtocol | None:
        """Get the protocol for a review."""
        review = self.get_review(review_id)
        if review and review.get("protocol_path"):
            protocol_path = Path(review["protocol_path"])
            if protocol_path.exists():
                return ReviewProtocol.from_yaml(protocol_path)
        return None

    # Citation operations
    def add_citation(self, citation: Citation, review_id: int) -> int:
        """Add a citation to a review and return its ID.

        If a citation with the same title already exists in the review,
        returns the existing citation's ID instead of creating a duplicate.
        """
        # Use INSERT OR IGNORE to skip duplicates (based on UNIQUE(review_id, title))
        cursor = self.conn.execute(
            """INSERT OR IGNORE INTO citations
               (review_id, source, source_key, title, authors, abstract, year, doi, journal, pdf_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                review_id,
                citation.source,
                citation.source_key,
                citation.title,
                json.dumps(citation.authors),
                citation.abstract,
                citation.year,
                citation.doi,
                citation.journal,
                str(citation.pdf_path) if citation.pdf_path else None,
            ),
        )
        self.conn.commit()

        # If INSERT was ignored (duplicate), fetch the existing ID
        if cursor.lastrowid == 0 or cursor.rowcount == 0:
            existing = self.conn.execute(
                "SELECT id FROM citations WHERE review_id = ? AND title = ?",
                (review_id, citation.title),
            ).fetchone()
            if existing:
                return existing["id"]

        return cursor.lastrowid  # type: ignore[return-value]

    def add_citations(self, citations: list[Citation], review_id: int) -> list[int]:
        """Add multiple citations and return their IDs."""
        ids = []
        for citation in citations:
            cid = self.add_citation(citation, review_id)
            ids.append(cid)
        return ids

    def get_citation(self, citation_id: int) -> Citation | None:
        """Get a citation by ID."""
        cursor = self.conn.execute("SELECT * FROM citations WHERE id = ?", (citation_id,))
        row = cursor.fetchone()
        return self._row_to_citation(row) if row else None

    def get_citations(self, review_id: int) -> list[Citation]:
        """Get all citations for a review."""
        cursor = self.conn.execute("SELECT * FROM citations WHERE review_id = ?", (review_id,))
        return [self._row_to_citation(row) for row in cursor.fetchall()]

    def update_citation_pdf_path(self, citation_id: int, pdf_path: Path) -> None:
        """Update the PDF path for a citation."""
        self.conn.execute("UPDATE citations SET pdf_path = ? WHERE id = ?", (str(pdf_path), citation_id))
        self.conn.commit()

    def _row_to_citation(self, row: sqlite3.Row) -> Citation:
        """Convert a database row to a Citation object."""
        data = dict(row)
        data["authors"] = json.loads(data["authors"]) if data["authors"] else []
        data["pdf_path"] = Path(data["pdf_path"]) if data["pdf_path"] else None
        return Citation(**data)

    # Abstract screening operations
    def get_unscreened_abstracts(self, review_id: int) -> list[Citation]:
        """Get citations that haven't been abstract screened."""
        cursor = self.conn.execute(
            """SELECT c.* FROM citations c
               LEFT JOIN abstract_screening a ON c.id = a.citation_id
               WHERE c.review_id = ? AND a.id IS NULL""",
            (review_id,),
        )
        return [self._row_to_citation(row) for row in cursor.fetchall()]

    def get_included_abstracts(self, review_id: int) -> list[Citation]:
        """Get citations included after abstract screening (via consensus or single reviewer)."""
        cursor = self.conn.execute(
            """SELECT DISTINCT c.* FROM citations c
               INNER JOIN screening_consensus sc ON c.id = sc.citation_id
               WHERE c.review_id = ? AND sc.stage = 'abstract' AND sc.consensus_decision = 'include'
               UNION
               SELECT DISTINCT c.* FROM citations c
               INNER JOIN abstract_screening a ON c.id = a.citation_id
               LEFT JOIN screening_consensus sc ON c.id = sc.citation_id AND sc.stage = 'abstract'
               WHERE c.review_id = ? AND a.decision = 'include' AND sc.id IS NULL""",
            (review_id, review_id),
        )
        return [self._row_to_citation(row) for row in cursor.fetchall()]

    def get_included_fulltext(self, review_id: int) -> list[Citation]:
        """Get citations included after full-text screening (via consensus or single reviewer)."""
        cursor = self.conn.execute(
            """SELECT DISTINCT c.* FROM citations c
               INNER JOIN screening_consensus sc ON c.id = sc.citation_id
               WHERE c.review_id = ? AND sc.stage = 'fulltext' AND sc.consensus_decision = 'include'
               UNION
               SELECT DISTINCT c.* FROM citations c
               INNER JOIN fulltext_screening f ON c.id = f.citation_id
               LEFT JOIN screening_consensus sc ON c.id = sc.citation_id AND sc.stage = 'fulltext'
               WHERE c.review_id = ? AND f.decision = 'include' AND sc.id IS NULL""",
            (review_id, review_id),
        )
        return [self._row_to_citation(row) for row in cursor.fetchall()]

    def save_abstract_screening(self, result: ScreeningResult) -> None:
        """Save an abstract screening result (updates if already exists)."""
        self.conn.execute(
            """INSERT OR REPLACE INTO abstract_screening
               (citation_id, decision, reasoning, model, reviewer_name, screened_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                result.citation_id,
                result.decision.value,
                result.reasoning,
                result.model,
                result.reviewer_name,
                result.screened_at,
            ),
        )
        self.conn.commit()

    def get_abstract_screening(self, citation_id: int) -> ScreeningResult | None:
        """Get the abstract screening result for a citation."""
        cursor = self.conn.execute("SELECT * FROM abstract_screening WHERE citation_id = ?", (citation_id,))
        row = cursor.fetchone()
        if row:
            data = dict(row)
            return ScreeningResult(
                citation_id=data["citation_id"],
                decision=ScreeningDecision(data["decision"]),
                reasoning=data["reasoning"],
                model=data["model"],
                screened_at=datetime.fromisoformat(data["screened_at"]) if data["screened_at"] else datetime.now(),
            )
        return None

    def get_abstract_included(self, review_id: int) -> list[Citation]:
        """Get citations that passed abstract screening."""
        cursor = self.conn.execute(
            """SELECT c.* FROM citations c
               JOIN abstract_screening a ON c.id = a.citation_id
               WHERE c.review_id = ? AND a.decision = 'include'""",
            (review_id,),
        )
        return [self._row_to_citation(row) for row in cursor.fetchall()]

    # Full-text screening operations
    def get_unscreened_fulltext(self, review_id: int) -> list[Citation]:
        """Get citations that passed abstract screening but haven't been full-text screened.

        Checks screening_consensus table first (for multi-reviewer mode),
        falls back to abstract_screening (for single-reviewer mode).
        """
        # First try screening_consensus (multi-reviewer mode)
        cursor = self.conn.execute(
            """SELECT c.* FROM citations c
               JOIN screening_consensus sc ON c.id = sc.citation_id
               LEFT JOIN screening_consensus ft ON c.id = ft.citation_id AND ft.stage = 'fulltext'
               WHERE c.review_id = ? AND sc.stage = 'abstract' AND sc.consensus_decision = 'include'
               AND ft.id IS NULL""",
            (review_id,),
        )
        results = [self._row_to_citation(row) for row in cursor.fetchall()]

        # If no consensus records, fall back to abstract_screening (single-reviewer mode)
        if not results:
            cursor = self.conn.execute(
                """SELECT c.* FROM citations c
                   JOIN abstract_screening a ON c.id = a.citation_id
                   LEFT JOIN fulltext_screening f ON c.id = f.citation_id
                   WHERE c.review_id = ? AND a.decision = 'include' AND f.id IS NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM screening_consensus
                       WHERE citation_id = c.id AND stage = 'abstract'
                   )""",
                (review_id,),
            )
            results = [self._row_to_citation(row) for row in cursor.fetchall()]

        return results

    def save_fulltext_screening(self, result: ScreeningResult) -> None:
        """Save a full-text screening result (updates if already exists)."""
        self.conn.execute(
            """INSERT OR REPLACE INTO fulltext_screening
               (citation_id, decision, reasoning, pdf_error, model, reviewer_name, screened_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                result.citation_id,
                result.decision.value,
                result.reasoning,
                result.pdf_error,
                result.model,
                result.reviewer_name,
                result.screened_at,
            ),
        )
        self.conn.commit()

    def get_fulltext_screening(self, citation_id: int) -> ScreeningResult | None:
        """Get the full-text screening result for a citation."""
        cursor = self.conn.execute("SELECT * FROM fulltext_screening WHERE citation_id = ?", (citation_id,))
        row = cursor.fetchone()
        if row:
            data = dict(row)
            return ScreeningResult(
                citation_id=data["citation_id"],
                decision=ScreeningDecision(data["decision"]),
                reasoning=data["reasoning"],
                model=data["model"],
                screened_at=datetime.fromisoformat(data["screened_at"]) if data["screened_at"] else datetime.now(),
                pdf_error=data.get("pdf_error"),
            )
        return None

    def get_fulltext_included(self, review_id: int) -> list[Citation]:
        """Get citations that passed full-text screening."""
        cursor = self.conn.execute(
            """SELECT c.* FROM citations c
               JOIN fulltext_screening f ON c.id = f.citation_id
               WHERE c.review_id = ? AND f.decision = 'include'""",
            (review_id,),
        )
        return [self._row_to_citation(row) for row in cursor.fetchall()]

    # Extraction operations
    def get_unextracted(self, review_id: int) -> list[Citation]:
        """Get citations that passed full-text screening but haven't been extracted."""
        # First try screening_consensus (multi-reviewer mode)
        cursor = self.conn.execute(
            """SELECT DISTINCT c.* FROM citations c
               JOIN screening_consensus sc ON c.id = sc.citation_id
               LEFT JOIN extractions e ON c.id = e.citation_id
               WHERE c.review_id = ? AND sc.stage = 'fulltext'
               AND sc.consensus_decision = 'include' AND e.id IS NULL""",
            (review_id,),
        )
        results = [self._row_to_citation(row) for row in cursor.fetchall()]

        # If no consensus records, fall back to fulltext_screening (single-reviewer mode)
        if not results:
            cursor = self.conn.execute(
                """SELECT DISTINCT c.* FROM citations c
                   JOIN fulltext_screening f ON c.id = f.citation_id
                   LEFT JOIN extractions e ON c.id = e.citation_id
                   WHERE c.review_id = ? AND f.decision = 'include' AND e.id IS NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM screening_consensus
                       WHERE citation_id = c.id AND stage = 'fulltext'
                   )""",
                (review_id,),
            )
            results = [self._row_to_citation(row) for row in cursor.fetchall()]

        return results

    def save_extraction(self, result: ExtractionResult) -> None:
        """Save an extraction result (updates if already exists)."""
        self.conn.execute(
            """INSERT OR REPLACE INTO extractions (citation_id, extracted_data, model, extracted_at)
               VALUES (?, ?, ?, ?)""",
            (result.citation_id, json.dumps(result.extracted_data), result.model, result.extracted_at),
        )
        self.conn.commit()

    def get_extraction(self, citation_id: int) -> ExtractionResult | None:
        """Get the extraction result for a citation."""
        cursor = self.conn.execute("SELECT * FROM extractions WHERE citation_id = ?", (citation_id,))
        row = cursor.fetchone()
        if row:
            data = dict(row)
            return ExtractionResult(
                citation_id=data["citation_id"],
                extracted_data=json.loads(data["extracted_data"]),
                model=data["model"],
                extracted_at=datetime.fromisoformat(data["extracted_at"]) if data["extracted_at"] else datetime.now(),
            )
        return None

    def get_all_extractions(self, review_id: int) -> list[tuple[Citation, ExtractionResult]]:
        """Get all citations with their extraction results."""
        cursor = self.conn.execute(
            """SELECT c.*, e.extracted_data, e.model as extract_model, e.extracted_at
               FROM citations c
               JOIN extractions e ON c.id = e.citation_id
               WHERE c.review_id = ?""",
            (review_id,),
        )
        results = []
        for row in cursor.fetchall():
            data = dict(row)
            citation = self._row_to_citation(row)
            extraction = ExtractionResult(
                citation_id=data["id"],
                extracted_data=json.loads(data["extracted_data"]),
                model=data["extract_model"],
                extracted_at=(datetime.fromisoformat(data["extracted_at"]) if data["extracted_at"] else datetime.now()),
            )
            results.append((citation, extraction))
        return results

    # Statistics
    def get_stats(self, review_id: int) -> ReviewStats:
        """Get statistics for a review."""
        stats = ReviewStats()

        # Total citations
        cursor = self.conn.execute("SELECT COUNT(*) FROM citations WHERE review_id = ?", (review_id,))
        stats.total_citations = cursor.fetchone()[0]

        # Abstract screening
        cursor = self.conn.execute(
            """SELECT decision, COUNT(*) FROM abstract_screening a
               JOIN citations c ON a.citation_id = c.id
               WHERE c.review_id = ? GROUP BY decision""",
            (review_id,),
        )
        for row in cursor.fetchall():
            stats.abstract_screened += row[1]
            if row[0] == "include":
                stats.abstract_included = row[1]
            elif row[0] == "exclude":
                stats.abstract_excluded = row[1]
            else:
                stats.abstract_uncertain = row[1]

        # Full-text screening
        cursor = self.conn.execute(
            """SELECT decision, COUNT(*) FROM fulltext_screening f
               JOIN citations c ON f.citation_id = c.id
               WHERE c.review_id = ? GROUP BY decision""",
            (review_id,),
        )
        for row in cursor.fetchall():
            stats.fulltext_screened += row[1]
            if row[0] == "include":
                stats.fulltext_included = row[1]
            elif row[0] == "exclude":
                stats.fulltext_excluded = row[1]
            else:
                stats.fulltext_uncertain = row[1]

        # PDF errors
        cursor = self.conn.execute(
            """SELECT COUNT(*) FROM fulltext_screening f
               JOIN citations c ON f.citation_id = c.id
               WHERE c.review_id = ? AND f.pdf_error IS NOT NULL""",
            (review_id,),
        )
        stats.fulltext_pdf_errors = cursor.fetchone()[0]

        # Extractions
        cursor = self.conn.execute(
            """SELECT COUNT(*) FROM extractions e
               JOIN citations c ON e.citation_id = c.id
               WHERE c.review_id = ?""",
            (review_id,),
        )
        stats.extracted = cursor.fetchone()[0]

        return stats

    # Multi-reviewer consensus operations
    def save_consensus(
        self,
        citation_id: int,
        stage: str,
        consensus_decision: ScreeningDecision,
        required_tiebreaker: bool = False,
    ) -> int:
        """Save a screening consensus result (updates if already exists)."""
        cursor = self.conn.execute(
            """INSERT OR REPLACE INTO screening_consensus
               (citation_id, stage, consensus_decision, required_tiebreaker)
               VALUES (?, ?, ?, ?)""",
            (citation_id, stage, consensus_decision.value, required_tiebreaker),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_consensus(self, citation_id: int, stage: str) -> dict | None:
        """Get the consensus for a citation at a specific stage."""
        cursor = self.conn.execute(
            "SELECT * FROM screening_consensus WHERE citation_id = ? AND stage = ?",
            (citation_id, stage),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_reviewer_results(self, citation_id: int, stage: str) -> list[ScreeningResult]:
        """Get all reviewer results for a citation at a specific stage."""
        table = "abstract_screening" if stage == "abstract" else "fulltext_screening"
        cursor = self.conn.execute(
            f"SELECT * FROM {table} WHERE citation_id = ?",
            (citation_id,),
        )
        results = []
        for row in cursor.fetchall():
            data = dict(row)
            results.append(
                ScreeningResult(
                    citation_id=data["citation_id"],
                    decision=ScreeningDecision(data["decision"]),
                    reasoning=data["reasoning"],
                    model=data["model"],
                    reviewer_name=data.get("reviewer_name"),
                    screened_at=(
                        datetime.fromisoformat(data["screened_at"]) if data["screened_at"] else datetime.now()
                    ),
                    pdf_error=data.get("pdf_error"),
                )
            )
        return results

    # Secondary filtering operations
    def save_filter_result(
        self,
        citation_id: int,
        passed: bool,
        reason: str | None = None,
        details: str | None = None,
    ) -> None:
        """Save a secondary filter result."""
        self.conn.execute(
            """INSERT INTO secondary_filters (citation_id, passed, reason, details)
               VALUES (?, ?, ?, ?)""",
            (citation_id, passed, reason, details),
        )
        self.conn.commit()

    def get_filter_results(self, citation_id: int) -> list[dict]:
        """Get all filter results for a citation."""
        cursor = self.conn.execute(
            "SELECT * FROM secondary_filters WHERE citation_id = ?",
            (citation_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_filtered_citations(self, review_id: int, passed: bool = True) -> list[Citation]:
        """Get citations that passed or failed secondary filtering."""
        cursor = self.conn.execute(
            """SELECT DISTINCT c.* FROM citations c
               JOIN secondary_filters sf ON c.id = sf.citation_id
               WHERE c.review_id = ? AND sf.passed = ?""",
            (review_id, passed),
        )
        return [self._row_to_citation(row) for row in cursor.fetchall()]

    def get_extracted_citations(self, review_id: int) -> list[Citation]:
        """Get citations that have been extracted."""
        cursor = self.conn.execute(
            """SELECT c.* FROM citations c
               JOIN extractions e ON c.id = e.citation_id
               WHERE c.review_id = ?""",
            (review_id,),
        )
        return [self._row_to_citation(row) for row in cursor.fetchall()]
