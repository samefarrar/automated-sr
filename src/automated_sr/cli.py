"""CLI interface for the systematic review automation tool."""

import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from automated_sr.citations.ris_parser import parse_ris_file
from automated_sr.citations.zotero import ZoteroClient, ZoteroError
from automated_sr.config import get_config
from automated_sr.database import Database
from automated_sr.extraction.extractor import DataExtractor
from automated_sr.models import ExtractionVariable, ReviewProtocol
from automated_sr.output.exporter import Exporter
from automated_sr.screening.abstract import AbstractScreener
from automated_sr.screening.fulltext import FullTextScreener

app = typer.Typer(
    name="sr",
    help="Automated systematic review tool using Claude AI",
    no_args_is_help=True,
)
console = Console()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def get_db() -> Database:
    """Get the database instance."""
    config = get_config()
    config.ensure_data_dir()
    return Database(config.database_path)  # type: ignore[arg-type]


@app.command()
def init(
    name: Annotated[str, typer.Argument(help="Name for the new review")],
    protocol: Annotated[Path | None, typer.Option("--protocol", "-p", help="Path to protocol YAML file")] = None,
) -> None:
    """Initialize a new systematic review project."""
    db = get_db()

    # Check if review already exists
    existing = db.get_review_by_name(name)
    if existing:
        console.print(f"[red]Error:[/red] Review '{name}' already exists (ID: {existing['id']})")
        raise typer.Exit(1)

    # Create review
    review_id = db.create_review(name, protocol)
    console.print(f"[green]Created review:[/green] {name} (ID: {review_id})")

    # If no protocol provided, create a template
    if not protocol:
        config = get_config()
        template_path = config.data_dir / f"{name}_protocol.yaml"

        default_protocol = ReviewProtocol(
            name=name,
            objective="Define your review objective here",
            inclusion_criteria=["Criterion 1", "Criterion 2"],
            exclusion_criteria=["Exclusion 1", "Exclusion 2"],
            extraction_variables=[
                ExtractionVariable(name="sample_size", description="Number of participants", type="integer"),
                ExtractionVariable(name="intervention", description="Description of intervention", type="string"),
            ],
        )
        default_protocol.to_yaml(template_path)
        console.print(f"[blue]Created protocol template:[/blue] {template_path}")
        console.print("[yellow]Edit this file to define your review criteria, then run:[/yellow]")
        console.print(f"  sr import --review {name} --protocol {template_path} <citations>")

    db.close()


@app.command("import")
def import_citations(
    source: Annotated[Path, typer.Argument(help="Path to RIS file or 'zotero' for Zotero import")],
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")] = "",
    protocol: Annotated[Path | None, typer.Option("--protocol", "-p", help="Path to protocol YAML file")] = None,
    collection: Annotated[str | None, typer.Option("--collection", "-c", help="Zotero collection key")] = None,
    limit: Annotated[int | None, typer.Option("--limit", "-l", help="Maximum citations to import")] = None,
) -> None:
    """Import citations from RIS file or Zotero."""
    db = get_db()

    # Get or create review
    if review:
        review_data = db.get_review_by_name(review)
        if not review_data:
            console.print(f"[red]Error:[/red] Review '{review}' not found. Run 'sr init {review}' first.")
            raise typer.Exit(1)
        review_id = review_data["id"]
    else:
        console.print("[red]Error:[/red] --review is required")
        raise typer.Exit(1)

    # Update protocol if provided
    if protocol:
        if not protocol.exists():
            console.print(f"[red]Error:[/red] Protocol file not found: {protocol}")
            raise typer.Exit(1)
        db.conn.execute("UPDATE reviews SET protocol_path = ? WHERE id = ?", (str(protocol), review_id))
        db.conn.commit()
        console.print(f"[blue]Updated protocol:[/blue] {protocol}")

    # Import from source
    source_str = str(source).lower()

    if source_str == "zotero":
        # Zotero import
        config = get_config()
        try:
            zotero_client = ZoteroClient(config.zotero)
        except ZoteroError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None

        console.print("[blue]Connecting to Zotero...[/blue]")

        if not zotero_client.test_connection():
            console.print("[red]Error:[/red] Could not connect to Zotero.")
            console.print(
                "Make sure Zotero is running and 'Allow other applications' is enabled in Settings > Advanced."
            )
            raise typer.Exit(1)

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            progress.add_task("Fetching citations from Zotero...", total=None)
            citations_with_pdfs, citations_without_pdfs = zotero_client.get_citations_with_pdfs(collection, limit)

        all_citations = citations_with_pdfs + citations_without_pdfs
        if not all_citations:
            console.print("[yellow]No citations found in Zotero.[/yellow]")
            raise typer.Exit(0)

        # Add to database
        db.add_citations(all_citations, review_id)
        console.print(f"[green]Imported {len(all_citations)} citations from Zotero[/green]")
        console.print(f"  - {len(citations_with_pdfs)} with PDFs")
        console.print(f"  - {len(citations_without_pdfs)} without PDFs")

        if citations_without_pdfs:
            console.print("\n[yellow]Citations missing PDFs:[/yellow]")
            for c in citations_without_pdfs[:5]:
                console.print(f"  - {c.title[:60]}...")
            if len(citations_without_pdfs) > 5:
                console.print(f"  ... and {len(citations_without_pdfs) - 5} more")

    else:
        # RIS import
        if not source.exists():
            console.print(f"[red]Error:[/red] File not found: {source}")
            raise typer.Exit(1)

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            progress.add_task("Parsing RIS file...", total=None)
            citations = parse_ris_file(source)

        if limit:
            citations = citations[:limit]

        db.add_citations(citations, review_id)
        console.print(f"[green]Imported {len(citations)} citations from {source}[/green]")

    db.close()


@app.command("screen-abstracts")
def screen_abstracts(
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")],
    limit: Annotated[int | None, typer.Option("--limit", "-l", help="Maximum citations to screen")] = None,
) -> None:
    """Screen citations at the abstract level."""
    db = get_db()

    review_data = db.get_review_by_name(review)
    if not review_data:
        console.print(f"[red]Error:[/red] Review '{review}' not found")
        raise typer.Exit(1)

    review_id = review_data["id"]
    protocol = db.get_protocol(review_id)
    if not protocol:
        console.print("[red]Error:[/red] No protocol found for this review. Import with --protocol option.")
        raise typer.Exit(1)

    # Get unscreened citations
    citations = db.get_unscreened_abstracts(review_id)
    if not citations:
        console.print("[green]All citations have been screened.[/green]")
        db.close()
        return

    if limit:
        citations = citations[:limit]

    console.print(f"[blue]Screening {len(citations)} citations...[/blue]")

    screener = AbstractScreener(protocol)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Screening abstracts...", total=len(citations))

        for citation in citations:
            result = screener.screen(citation)
            db.save_abstract_screening(result)
            progress.advance(task)

            # Show result
            color = {"include": "green", "exclude": "red", "uncertain": "yellow"}[result.decision.value]
            console.print(f"  [{color}]{result.decision.value.upper()}[/{color}]: {citation.title[:60]}...")

    # Show summary
    stats = db.get_stats(review_id)
    console.print("\n[bold]Abstract Screening Complete[/bold]")
    console.print(f"  Included: {stats.abstract_included}")
    console.print(f"  Excluded: {stats.abstract_excluded}")
    console.print(f"  Uncertain: {stats.abstract_uncertain}")

    db.close()


@app.command("screen-fulltext")
def screen_fulltext(
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")],
    limit: Annotated[int | None, typer.Option("--limit", "-l", help="Maximum citations to screen")] = None,
) -> None:
    """Screen citations at the full-text level."""
    db = get_db()

    review_data = db.get_review_by_name(review)
    if not review_data:
        console.print(f"[red]Error:[/red] Review '{review}' not found")
        raise typer.Exit(1)

    review_id = review_data["id"]
    protocol = db.get_protocol(review_id)
    if not protocol:
        console.print("[red]Error:[/red] No protocol found for this review.")
        raise typer.Exit(1)

    # Get citations needing full-text screening
    citations = db.get_unscreened_fulltext(review_id)
    if not citations:
        console.print("[green]All eligible citations have been full-text screened.[/green]")
        db.close()
        return

    if limit:
        citations = citations[:limit]

    # Check PDF availability
    with_pdf = [c for c in citations if c.has_pdf()]
    without_pdf = [c for c in citations if not c.has_pdf()]

    if without_pdf:
        console.print(f"[yellow]Warning: {len(without_pdf)} citations missing PDFs[/yellow]")
        for c in without_pdf[:3]:
            console.print(f"  - {c.title[:60]}...")

    console.print(f"[blue]Full-text screening {len(citations)} citations ({len(with_pdf)} with PDFs)...[/blue]")

    screener = FullTextScreener(protocol)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Screening full-text...", total=len(citations))

        for citation in citations:
            result = screener.screen(citation)
            db.save_fulltext_screening(result)
            progress.advance(task)

            color = {"include": "green", "exclude": "red", "uncertain": "yellow"}[result.decision.value]
            status = f" (PDF error: {result.pdf_error})" if result.pdf_error else ""
            console.print(f"  [{color}]{result.decision.value.upper()}[/{color}]: {citation.title[:50]}...{status}")

    stats = db.get_stats(review_id)
    console.print("\n[bold]Full-Text Screening Complete[/bold]")
    console.print(f"  Included: {stats.fulltext_included}")
    console.print(f"  Excluded: {stats.fulltext_excluded}")
    console.print(f"  Uncertain: {stats.fulltext_uncertain}")
    console.print(f"  PDF errors: {stats.fulltext_pdf_errors}")

    db.close()


@app.command()
def extract(
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")],
    limit: Annotated[int | None, typer.Option("--limit", "-l", help="Maximum citations to extract")] = None,
) -> None:
    """Extract data from included articles."""
    db = get_db()

    review_data = db.get_review_by_name(review)
    if not review_data:
        console.print(f"[red]Error:[/red] Review '{review}' not found")
        raise typer.Exit(1)

    review_id = review_data["id"]
    protocol = db.get_protocol(review_id)
    if not protocol:
        console.print("[red]Error:[/red] No protocol found for this review.")
        raise typer.Exit(1)

    if not protocol.extraction_variables:
        console.print("[red]Error:[/red] No extraction variables defined in protocol.")
        raise typer.Exit(1)

    # Get citations needing extraction
    citations = db.get_unextracted(review_id)
    if not citations:
        console.print("[green]All included citations have been extracted.[/green]")
        db.close()
        return

    if limit:
        citations = citations[:limit]

    console.print(f"[blue]Extracting data from {len(citations)} citations...[/blue]")
    console.print(f"Variables: {', '.join(v.name for v in protocol.extraction_variables)}")

    extractor = DataExtractor(protocol)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Extracting data...", total=len(citations))

        for citation in citations:
            result = extractor.extract(citation)
            db.save_extraction(result)
            progress.advance(task)

            extracted_count = sum(1 for v in result.extracted_data.values() if v is not None)
            console.print(f"  Extracted {extracted_count} values: {citation.title[:50]}...")

    stats = db.get_stats(review_id)
    console.print("\n[bold]Extraction Complete[/bold]")
    console.print(f"  Citations extracted: {stats.extracted}")

    db.close()


@app.command()
def export(
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Output directory")] = Path("./output"),
    format: Annotated[str, typer.Option("--format", "-f", help="Output format: json, csv, or all")] = "all",
) -> None:
    """Export review results."""
    db = get_db()

    review_data = db.get_review_by_name(review)
    if not review_data:
        console.print(f"[red]Error:[/red] Review '{review}' not found")
        raise typer.Exit(1)

    review_id = review_data["id"]
    exporter = Exporter(db)

    output.mkdir(parents=True, exist_ok=True)

    if format in ("json", "all"):
        json_path = output / f"{review}_full.json"
        exporter.export_json(review_id, json_path)
        console.print(f"[green]Exported:[/green] {json_path}")

    if format in ("csv", "all"):
        csv_path = output / f"{review}_extractions.csv"
        exporter.export_csv(review_id, csv_path)
        console.print(f"[green]Exported:[/green] {csv_path}")

        abstract_csv = output / f"{review}_abstract_screening.csv"
        exporter.export_screening_csv(review_id, abstract_csv, "abstract")
        console.print(f"[green]Exported:[/green] {abstract_csv}")

        fulltext_csv = output / f"{review}_fulltext_screening.csv"
        exporter.export_screening_csv(review_id, fulltext_csv, "fulltext")
        console.print(f"[green]Exported:[/green] {fulltext_csv}")

    db.close()


@app.command()
def status(
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")],
) -> None:
    """Show review status and statistics."""
    db = get_db()

    review_data = db.get_review_by_name(review)
    if not review_data:
        console.print(f"[red]Error:[/red] Review '{review}' not found")
        raise typer.Exit(1)

    review_id = review_data["id"]
    stats = db.get_stats(review_id)
    exporter = Exporter(db)

    # Summary
    console.print(exporter.generate_summary(review_id))

    # Progress table
    table = Table(title="Review Progress")
    table.add_column("Stage", style="cyan")
    table.add_column("Complete", justify="right")
    table.add_column("Remaining", justify="right")
    table.add_column("Status")

    # Abstract screening
    abstract_remaining = stats.total_citations - stats.abstract_screened
    if abstract_remaining == 0:
        abstract_status = "[green]Done[/green]"
    else:
        abstract_status = f"[yellow]{abstract_remaining} left[/yellow]"
    table.add_row("Abstract Screening", str(stats.abstract_screened), str(abstract_remaining), abstract_status)

    # Full-text screening
    fulltext_remaining = stats.abstract_included - stats.fulltext_screened
    if fulltext_remaining == 0:
        fulltext_status = "[green]Done[/green]"
    else:
        fulltext_status = f"[yellow]{fulltext_remaining} left[/yellow]"
    table.add_row("Full-text Screening", str(stats.fulltext_screened), str(fulltext_remaining), fulltext_status)

    # Extraction
    extract_remaining = stats.fulltext_included - stats.extracted
    extract_status = "[green]Done[/green]" if extract_remaining == 0 else f"[yellow]{extract_remaining} left[/yellow]"
    table.add_row("Data Extraction", str(stats.extracted), str(extract_remaining), extract_status)

    console.print(table)

    db.close()


@app.command("list")
def list_reviews() -> None:
    """List all reviews."""
    db = get_db()
    reviews = db.list_reviews()

    if not reviews:
        console.print("[yellow]No reviews found. Run 'sr init <name>' to create one.[/yellow]")
        db.close()
        return

    table = Table(title="Systematic Reviews")
    table.add_column("ID", justify="right")
    table.add_column("Name")
    table.add_column("Created")
    table.add_column("Citations")

    for r in reviews:
        stats = db.get_stats(r["id"])
        created = r["created_at"][:10] if r["created_at"] else "Unknown"
        table.add_row(str(r["id"]), r["name"], created, str(stats.total_citations))

    console.print(table)
    db.close()


@app.command("zotero-collections")
def zotero_collections() -> None:
    """List Zotero collections."""
    config = get_config()
    try:
        zotero_client = ZoteroClient(config.zotero)
    except ZoteroError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    if not zotero_client.test_connection():
        console.print("[red]Error:[/red] Could not connect to Zotero.")
        console.print("Make sure Zotero is running and 'Allow other applications' is enabled in Settings > Advanced.")
        raise typer.Exit(1)

    collections = zotero_client.list_collections()

    if not collections:
        console.print("[yellow]No collections found.[/yellow]")
        return

    table = Table(title="Zotero Collections")
    table.add_column("Key")
    table.add_column("Name")

    for c in collections:
        table.add_row(c["key"], c["name"])

    console.print(table)


if __name__ == "__main__":
    app()
