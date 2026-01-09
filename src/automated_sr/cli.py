"""CLI interface for the systematic review automation tool."""

import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from automated_sr.analysis import EffectMeasure, ForestPlot, MetaAnalysis, PoolingMethod, SecondaryFilter
from automated_sr.citations.ris_parser import parse_ris_file
from automated_sr.citations.zotero import ZoteroClient, ZoteroError
from automated_sr.config import get_config
from automated_sr.database import Database
from automated_sr.extraction.extractor import DataExtractor
from automated_sr.models import ExtractionVariable, ReviewProtocol
from automated_sr.openalex import OpenAlexClient, PDFRetriever
from automated_sr.output.exporter import Exporter
from automated_sr.screening.abstract import AbstractScreener
from automated_sr.screening.fulltext import FullTextScreener
from automated_sr.screening.multi_reviewer import MultiReviewerScreener, create_default_reviewers

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


@app.command("search-openalex")
def search_openalex(
    query: Annotated[str | None, typer.Argument(help="Search query (title/abstract keywords)")] = None,
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")] = "",
    year_from: Annotated[int | None, typer.Option("--year-from", help="Minimum publication year")] = None,
    year_to: Annotated[int | None, typer.Option("--year-to", help="Maximum publication year")] = None,
    open_access: Annotated[bool, typer.Option("--oa", help="Only open access works")] = False,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Maximum results to fetch")] = 100,
    doi: Annotated[str | None, typer.Option("--doi", help="Fetch single work by DOI")] = None,
) -> None:
    """Search OpenAlex for articles and import to review."""
    db = get_db()

    # Validate review
    if not review:
        console.print("[red]Error:[/red] --review is required")
        raise typer.Exit(1)

    review_data = db.get_review_by_name(review)
    if not review_data:
        console.print(f"[red]Error:[/red] Review '{review}' not found. Run 'sr init {review}' first.")
        raise typer.Exit(1)
    review_id = review_data["id"]

    # Initialize OpenAlex client
    config = get_config()
    client = OpenAlexClient(email=config.openalex_email)

    if doi:
        # Fetch single work by DOI
        console.print(f"[blue]Looking up DOI: {doi}[/blue]")
        work = client.get_by_doi(doi)
        if not work:
            console.print(f"[red]Error:[/red] Work not found for DOI: {doi}")
            raise typer.Exit(1)
        works = [work]
    else:
        # Search by query
        if not query:
            console.print("[red]Error:[/red] Either --query or --doi is required")
            raise typer.Exit(1)

        filters: dict[str, str | bool] = {}
        if year_from:
            filters["from_publication_date"] = f"{year_from}-01-01"
        if year_to:
            filters["to_publication_date"] = f"{year_to}-12-31"
        if open_access:
            filters["is_oa"] = True

        console.print(f"[blue]Searching OpenAlex for: {query}[/blue]")
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            progress.add_task("Fetching results...", total=None)
            works = client.search(query=query, filters=filters, limit=limit)

    if not works:
        console.print("[yellow]No results found.[/yellow]")
        db.close()
        return

    # Convert to citations and add to database
    citations = [client.to_citation(w) for w in works]
    db.add_citations(citations, review_id)

    console.print(f"[green]Imported {len(citations)} citations from OpenAlex[/green]")

    # Show summary
    with_abstract = sum(1 for c in citations if c.has_abstract())
    with_doi = sum(1 for c in citations if c.doi)
    console.print(f"  - {with_abstract} with abstracts")
    console.print(f"  - {with_doi} with DOIs")

    db.close()


@app.command("fetch-pdfs")
def fetch_pdfs(
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")],
    limit: Annotated[int | None, typer.Option("--limit", "-l", help="Maximum PDFs to fetch")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Overwrite existing PDFs")] = False,
) -> None:
    """Fetch PDFs for citations using OpenAlex open access URLs."""
    db = get_db()
    config = get_config()

    review_data = db.get_review_by_name(review)
    if not review_data:
        console.print(f"[red]Error:[/red] Review '{review}' not found")
        raise typer.Exit(1)

    review_id = review_data["id"]

    # Get citations with DOIs that need PDFs
    all_citations = db.get_citations(review_id)
    citations = [c for c in all_citations if c.doi and (overwrite or not c.has_pdf())]

    if not citations:
        console.print("[green]All citations with DOIs already have PDFs.[/green]")
        db.close()
        return

    if limit:
        citations = citations[:limit]

    console.print(f"[blue]Attempting to fetch PDFs for {len(citations)} citations...[/blue]")

    # Initialize clients
    openalex = OpenAlexClient(email=config.openalex_email)
    config.ensure_pdf_dir()
    retriever = PDFRetriever(config.pdf_download_dir)  # type: ignore[arg-type]

    success_count = 0
    fail_count = 0

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Fetching PDFs...", total=len(citations))

        for citation in citations:
            progress.advance(task)

            # Look up work in OpenAlex
            work = openalex.get_by_doi(citation.doi)  # type: ignore[arg-type]
            if not work:
                fail_count += 1
                continue

            # Get PDF URL
            pdf_url = retriever.get_pdf_url(work)
            if not pdf_url:
                fail_count += 1
                continue

            # Download PDF
            filename = f"{citation.id}_{citation.doi.replace('/', '_')}"  # type: ignore[union-attr]
            pdf_path = retriever.download_pdf(pdf_url, filename)
            if pdf_path:
                # Update citation in database
                db.conn.execute("UPDATE citations SET pdf_path = ? WHERE id = ?", (str(pdf_path), citation.id))
                db.conn.commit()
                success_count += 1
                console.print(f"  [green]Downloaded:[/green] {citation.title[:50]}...")
            else:
                fail_count += 1

    console.print("\n[bold]PDF Fetch Complete[/bold]")
    console.print(f"  Downloaded: {success_count}")
    console.print(f"  Failed/unavailable: {fail_count}")

    db.close()


@app.command("import-pdfs")
def import_pdfs(
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")],
    directory: Annotated[Path, typer.Option("--dir", "-d", help="Directory containing PDF files")],
    use_llm: Annotated[bool, typer.Option("--llm/--no-llm", help="Use LLM for DOI extraction (default: yes)")] = True,
    copy_files: Annotated[bool, typer.Option("--copy/--no-copy", help="Copy files to review PDF dir")] = True,
) -> None:
    """Import manually downloaded PDFs by extracting DOI and matching to citations."""
    from shutil import copy2

    from automated_sr.pdf.doi_extractor import extract_doi_from_pdf, normalize_doi

    db = get_db()
    config = get_config()

    review_data = db.get_review_by_name(review)
    if not review_data:
        console.print(f"[red]Error:[/red] Review '{review}' not found")
        raise typer.Exit(1)

    review_id = review_data["id"]

    # Get all citations with DOIs
    citations = db.get_citations(review_id)
    citations_with_doi = [c for c in citations if c.doi]

    if not citations_with_doi:
        console.print("[yellow]No citations with DOIs found in this review.[/yellow]")
        db.close()
        return

    # Build DOI lookup map
    doi_to_citation: dict[str, int] = {}
    for c in citations_with_doi:
        if c.doi and c.id:
            doi_to_citation[normalize_doi(c.doi)] = c.id

    console.print(f"[blue]Scanning {directory} for PDFs to import...[/blue]")
    console.print(f"Matching against {len(doi_to_citation)} citations with DOIs")
    if use_llm:
        console.print("Using LLM (Claude Haiku) for DOI extraction if regex fails")

    # Find all PDF files
    pdf_files = list(directory.glob("**/*.pdf"))
    if not pdf_files:
        console.print(f"[yellow]No PDF files found in {directory}[/yellow]")
        db.close()
        return

    console.print(f"Found {len(pdf_files)} PDF files\n")

    # Prepare target directory
    pdf_dir = config.data_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    matched = 0
    unmatched = 0
    already_have = 0
    errors = 0

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Extracting DOIs and matching...", total=len(pdf_files))

        for pdf_path in pdf_files:
            progress.update(task, description=f"Processing {pdf_path.name[:40]}...")

            try:
                doi = extract_doi_from_pdf(pdf_path, use_llm=use_llm)

                if not doi:
                    console.print(f"  [yellow]No DOI found:[/yellow] {pdf_path.name}")
                    unmatched += 1
                    progress.advance(task)
                    continue

                normalized = normalize_doi(doi)
                citation_id = doi_to_citation.get(normalized)

                if not citation_id:
                    console.print(f"  [yellow]DOI not in review:[/yellow] {doi} ({pdf_path.name})")
                    unmatched += 1
                    progress.advance(task)
                    continue

                # Check if citation already has a PDF
                existing = db.conn.execute("SELECT pdf_path FROM citations WHERE id = ?", (citation_id,)).fetchone()
                if existing and existing[0]:
                    existing_path = Path(existing[0])
                    if existing_path.exists():
                        console.print(f"  [dim]Already have PDF:[/dim] {doi}")
                        already_have += 1
                        progress.advance(task)
                        continue

                # Copy or reference the file
                if copy_files:
                    safe_doi = doi.replace("/", "_")
                    target_path = pdf_dir / f"{citation_id}_{safe_doi}.pdf"
                    copy2(pdf_path, target_path)
                    final_path = target_path
                else:
                    final_path = pdf_path.resolve()

                # Update database
                db.conn.execute(
                    "UPDATE citations SET pdf_path = ? WHERE id = ?",
                    (str(final_path), citation_id),
                )
                db.conn.commit()

                matched += 1
                console.print(f"  [green]Matched:[/green] {doi} -> citation {citation_id}")

            except Exception as e:
                console.print(f"  [red]Error processing {pdf_path.name}:[/red] {e}")
                errors += 1

            progress.advance(task)

    console.print("\n[bold]PDF Import Complete[/bold]")
    console.print(f"  Matched and imported: {matched}")
    console.print(f"  Already had PDF: {already_have}")
    console.print(f"  No match found: {unmatched}")
    if errors:
        console.print(f"  Errors: {errors}")

    db.close()


@app.command("export-to-zotero")
def export_to_zotero(
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")],
    included_only: Annotated[bool, typer.Option("--included-only", help="Only export included citations")] = False,
    stage: Annotated[str, typer.Option("--stage", "-s", help="Stage to filter by: abstract or fulltext")] = "abstract",
    use_web_api: Annotated[bool, typer.Option("--web-api", help="Use Zotero web API instead of local")] = False,
) -> None:
    """Export citations to Zotero for PDF retrieval.

    By default, uses the local Zotero API (requires Zotero to be running).
    Items are added to the currently selected collection in Zotero.

    You can then use Zotero's 'Find Available PDFs' feature to retrieve PDFs
    using institutional access.
    """
    from automated_sr.citations.zotero import ZoteroLocalClient

    db = get_db()

    review_data = db.get_review_by_name(review)
    if not review_data:
        console.print(f"[red]Error:[/red] Review '{review}' not found")
        raise typer.Exit(1)

    review_id = review_data["id"]

    # Get citations
    if included_only:
        citations = db.get_included_abstracts(review_id) if stage == "abstract" else db.get_included_fulltext(review_id)
        console.print(f"[blue]Exporting {len(citations)} included citations to Zotero...[/blue]")
    else:
        citations = db.get_citations(review_id)
        console.print(f"[blue]Exporting {len(citations)} citations to Zotero...[/blue]")

    if not citations:
        console.print("[yellow]No citations to export.[/yellow]")
        db.close()
        return

    if use_web_api:
        # Use web API (requires API keys)
        from automated_sr.citations.zotero import ZoteroClient, ZoteroError
        from automated_sr.config import get_zotero_config

        try:
            zotero_config = get_zotero_config()
            zotero_client = ZoteroClient(zotero_config)
        except ZoteroError as e:
            console.print(f"[red]Zotero configuration error:[/red] {e}")
            console.print("\nTo configure Zotero web API, set these environment variables:")
            console.print("  ZOTERO_LIBRARY_ID - Your Zotero user ID")
            console.print("  ZOTERO_API_KEY - Your Zotero API key")
            raise typer.Exit(1) from None

        if not zotero_client.test_connection():
            console.print("[red]Failed to connect to Zotero web API.[/red]")
            raise typer.Exit(1)

        target_collection = f"SR: {review}"
        console.print(f"Creating collection: [bold]{target_collection}[/bold]")

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
        ) as progress:
            progress.add_task("Exporting to Zotero...", total=None)
            collection_key, successful, failed = zotero_client.export_citations_to_collection(
                citations, target_collection
            )

        if collection_key:
            console.print("\n[bold green]Export Complete![/bold green]")
            console.print(f"  Collection: {target_collection}")
            console.print(f"  Items created: {successful}")
            if failed:
                console.print(f"  [yellow]Failed: {failed}[/yellow]")
    else:
        # Use local API (no auth needed, Zotero must be running)
        local_client = ZoteroLocalClient()

        if not local_client.is_running():
            console.print("[red]Zotero is not running.[/red]")
            console.print("\nPlease start Zotero and try again.")
            console.print("Or use --web-api flag to use the Zotero web API instead.")
            raise typer.Exit(1)

        console.print("[green]Connected to local Zotero instance[/green]")
        console.print("[dim]Items will be added to the currently selected collection in Zotero[/dim]")
        console.print()

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
        ) as progress:
            progress.add_task("Exporting to Zotero...", total=None)
            successful, failed = local_client.save_citations(citations)

        local_client.close()

        if successful > 0:
            console.print("\n[bold green]Export Complete![/bold green]")
            console.print(f"  Items created: {successful}")
            if failed:
                console.print(f"  [yellow]Failed: {failed}[/yellow]")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. In Zotero, select all items (Ctrl/Cmd+A)")
    console.print("  2. Right-click > Find Available PDFs")
    console.print("  3. After PDFs are downloaded, run:")
    console.print(f"     [dim]sr import-pdfs --review {review} --dir ~/Zotero/storage[/dim]")

    db.close()


@app.command("screen-multi")
def screen_multi(
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")],
    stage: Annotated[str, typer.Option("--stage", "-s", help="Screening stage: abstract or fulltext")] = "abstract",
    limit: Annotated[int | None, typer.Option("--limit", "-l", help="Maximum citations to screen")] = None,
) -> None:
    """Screen citations with multiple reviewers (requires reviewers in protocol)."""
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

    # Check if multi-reviewer is configured
    if not protocol.has_multi_reviewer():
        console.print("[yellow]No multi-reviewer configuration in protocol.[/yellow]")
        console.print("Add reviewers to your protocol YAML or use default configuration.")

        # Offer to use defaults
        use_defaults = typer.confirm("Use default reviewers (2x Haiku + Sonnet tiebreaker)?")
        if use_defaults:
            protocol.reviewers = create_default_reviewers()
        else:
            raise typer.Exit(0)

    # Get unscreened citations
    citations = db.get_unscreened_abstracts(review_id) if stage == "abstract" else db.get_unscreened_fulltext(review_id)

    if not citations:
        console.print(f"[green]All citations have been {stage} screened.[/green]")
        db.close()
        return

    if limit:
        citations = citations[:limit]

    console.print(f"[blue]Multi-reviewer screening {len(citations)} citations at {stage} stage...[/blue]")
    console.print(f"Primary reviewers: {[r.name for r in protocol.get_primary_reviewers()]}")
    tiebreaker = protocol.get_tiebreaker()
    if tiebreaker:
        console.print(f"Tiebreaker: {tiebreaker.name} ({tiebreaker.model})")

    screener = MultiReviewerScreener(protocol, stage=stage)

    tiebreaker_count = 0

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Screening...", total=len(citations))

        for citation in citations:
            result = screener.screen(citation)

            # Save individual reviewer results
            for reviewer_result in result.reviewer_results:
                if stage == "abstract":
                    db.save_abstract_screening(reviewer_result)
                else:
                    db.save_fulltext_screening(reviewer_result)

            # Save tiebreaker if used
            if result.tiebreaker_result:
                if stage == "abstract":
                    db.save_abstract_screening(result.tiebreaker_result)
                else:
                    db.save_fulltext_screening(result.tiebreaker_result)
                tiebreaker_count += 1

            # Save consensus
            db.save_consensus(citation.id or 0, stage, result.consensus_decision, result.required_tiebreaker)

            progress.advance(task)

            # Show result
            decision_colors = {"include": "green", "exclude": "red", "uncertain": "yellow"}
            color = decision_colors[result.consensus_decision.value]
            tb_marker = " [tiebreaker]" if result.required_tiebreaker else ""
            decision_text = result.consensus_decision.value.upper()
            console.print(f"  [{color}]{decision_text}{tb_marker}[/{color}]: {citation.title[:50]}...")

    # Show summary
    stats = db.get_stats(review_id)
    console.print(f"\n[bold]Multi-Reviewer {stage.title()} Screening Complete[/bold]")
    if stage == "abstract":
        console.print(f"  Included: {stats.abstract_included}")
        console.print(f"  Excluded: {stats.abstract_excluded}")
        console.print(f"  Uncertain: {stats.abstract_uncertain}")
    else:
        console.print(f"  Included: {stats.fulltext_included}")
        console.print(f"  Excluded: {stats.fulltext_excluded}")
        console.print(f"  Uncertain: {stats.fulltext_uncertain}")
    console.print(f"  Tiebreaker needed: {tiebreaker_count}")

    db.close()


@app.command("filter")
def apply_filter(
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")],
    required_fields: Annotated[
        list[str] | None, typer.Option("--required", help="Required extraction fields (comma-separated)")
    ] = None,
    interventions: Annotated[
        list[str] | None, typer.Option("--interventions", help="Eligible interventions (comma-separated)")
    ] = None,
    comparators: Annotated[
        list[str] | None, typer.Option("--comparators", help="Eligible comparators (comma-separated)")
    ] = None,
) -> None:
    """Apply secondary filters to extracted data."""
    db = get_db()

    review_data = db.get_review_by_name(review)
    if not review_data:
        console.print(f"[red]Error:[/red] Review '{review}' not found")
        raise typer.Exit(1)

    review_id = review_data["id"]

    # Get extracted citations
    citations = db.get_extracted_citations(review_id)
    if not citations:
        console.print("[yellow]No extracted citations to filter.[/yellow]")
        db.close()
        return

    # Build citations with extractions list
    citations_with_extractions = []
    for citation in citations:
        extraction = db.get_extraction(citation.id or 0)
        if extraction:
            citations_with_extractions.append((citation, extraction))

    if not citations_with_extractions:
        console.print("[yellow]No extractions found.[/yellow]")
        db.close()
        return

    console.print(f"[blue]Applying filters to {len(citations_with_extractions)} citations...[/blue]")

    # Create filter
    secondary_filter = SecondaryFilter(
        required_outcome_fields=required_fields,
        eligible_interventions=interventions,
        eligible_comparators=comparators,
    )

    # Apply filters (includes duplicate checking)
    passed, filter_results = secondary_filter.apply_all(citations_with_extractions)

    # Save filter results (only failures for tracking)
    for result in filter_results:
        if not result.passed:
            db.save_filter_result(
                result.citation_id,
                result.passed,
                result.reason.value if result.reason else None,
                result.details,
            )

    # Summary
    failed = len(citations_with_extractions) - len(passed)
    console.print("\n[bold]Secondary Filtering Complete[/bold]")
    console.print(f"  Passed: {len(passed)}")
    console.print(f"  Filtered out: {failed}")

    # Show filter breakdown
    from collections import Counter

    reasons = Counter(r.reason.value for r in filter_results if not r.passed and r.reason is not None)
    if reasons:
        console.print("\n[yellow]Filter reasons:[/yellow]")
        for reason, count in reasons.most_common():
            console.print(f"  - {reason}: {count}")

    db.close()


@app.command("analyze")
def analyze(
    review: Annotated[str, typer.Option("--review", "-r", help="Review name")],
    effect: Annotated[str, typer.Option("--effect", "-e", help="Effect measure: MD, SMD, OR, RR")] = "MD",
    model: Annotated[str, typer.Option("--model", "-m", help="Pooling model: fixed or random")] = "random",
    output: Annotated[Path, typer.Option("--output", "-o", help="Output directory")] = Path("./analysis"),
    effect_field: Annotated[
        str, typer.Option("--effect-field", help="Extraction field for effect size")
    ] = "effect_size",
    se_field: Annotated[str, typer.Option("--se-field", help="Extraction field for standard error")] = "standard_error",
) -> None:
    """Run meta-analysis and generate forest plot."""
    db = get_db()

    review_data = db.get_review_by_name(review)
    if not review_data:
        console.print(f"[red]Error:[/red] Review '{review}' not found")
        raise typer.Exit(1)

    review_id = review_data["id"]

    # Get extracted citations that passed filtering
    citations = db.get_extracted_citations(review_id)
    if not citations:
        console.print("[yellow]No extracted citations for analysis.[/yellow]")
        db.close()
        return

    # Parse effect measure and pooling model
    try:
        effect_measure = EffectMeasure(effect.upper())
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid effect measure: {effect}. Use MD, SMD, OR, or RR.")
        raise typer.Exit(1) from None

    try:
        pooling_method = PoolingMethod(model.lower())
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid pooling model: {model}. Use 'fixed' or 'random'.")
        raise typer.Exit(1) from None

    # Build effect sizes from extractions
    from automated_sr.analysis import EffectSize

    effects: list[EffectSize] = []
    for citation in citations:
        extraction = db.get_extraction(citation.id or 0)
        if not extraction:
            continue

        effect_val = extraction.extracted_data.get(effect_field)
        se_val = extraction.extracted_data.get(se_field)

        if effect_val is None or se_val is None:
            console.print(f"[yellow]Skipping {citation.title[:40]}... (missing effect/SE)[/yellow]")
            continue

        try:
            effect_float = float(effect_val)
            se_float = float(se_val)
        except (ValueError, TypeError):
            console.print(f"[yellow]Skipping {citation.title[:40]}... (invalid effect/SE values)[/yellow]")
            continue

        # Calculate CI
        ci_lower = effect_float - 1.96 * se_float
        ci_upper = effect_float + 1.96 * se_float

        study_name = f"{citation.authors[0] if citation.authors else 'Unknown'} {citation.year or ''}"
        effects.append(
            EffectSize(
                study_id=citation.id or 0,
                study_name=study_name,
                effect=effect_float,
                se=se_float,
                ci_lower=ci_lower,
                ci_upper=ci_upper,
            )
        )

    if len(effects) < 2:
        console.print("[red]Error:[/red] Need at least 2 studies with effect sizes for meta-analysis.")
        db.close()
        return

    console.print(f"[blue]Running {pooling_method.value} effects meta-analysis with {len(effects)} studies...[/blue]")

    # Run meta-analysis (use log scale for ratio measures)
    log_scale = effect_measure in (EffectMeasure.OR, EffectMeasure.RR)

    if pooling_method == PoolingMethod.FIXED:
        pooled = MetaAnalysis.fixed_effects(effects, log_scale=log_scale)
    else:
        pooled = MetaAnalysis.random_effects(effects, log_scale=log_scale)

    # Display results
    console.print(f"\n[bold]Meta-Analysis Results ({effect_measure.value})[/bold]")
    console.print(f"  Pooled effect: {pooled.effect:.3f} (95% CI: {pooled.ci_lower:.3f} to {pooled.ci_upper:.3f})")
    console.print(f"  Z-score: {pooled.z_score:.3f}, p-value: {pooled.p_value:.4f}")
    console.print(f"  Heterogeneity: I² = {pooled.i_squared:.1f}%, Q = {pooled.q_statistic:.2f}")
    if pooled.tau_squared is not None:
        console.print(f"  Between-study variance: τ² = {pooled.tau_squared:.4f}")

    # Generate forest plot
    output.mkdir(parents=True, exist_ok=True)

    forest = ForestPlot(effect_measure=effect_measure)
    fig = forest.create(
        effects=effects,
        pooled=pooled,
        title=f"Forest Plot - {review}",
    )

    plot_path = output / f"{review}_forest_plot.png"
    forest.save(fig, plot_path)
    console.print(f"\n[green]Forest plot saved:[/green] {plot_path}")

    # Export results
    import json

    results_path = output / f"{review}_meta_analysis.json"
    results_data = {
        "effect_measure": effect_measure.value,
        "pooling_method": pooling_method.value,
        "n_studies": len(effects),
        "pooled_effect": pooled.effect,
        "pooled_se": pooled.se,
        "ci_lower": pooled.ci_lower,
        "ci_upper": pooled.ci_upper,
        "z_score": pooled.z_score,
        "p_value": pooled.p_value,
        "i_squared": pooled.i_squared,
        "q_statistic": pooled.q_statistic,
        "tau_squared": pooled.tau_squared,
        "studies": [
            {
                "study_id": e.study_id,
                "study_name": e.study_name,
                "effect": e.effect,
                "se": e.se,
                "ci_lower": e.ci_lower,
                "ci_upper": e.ci_upper,
                "weight": e.weight,
            }
            for e in effects
        ],
    }
    with open(results_path, "w") as f:
        json.dump(results_data, f, indent=2)
    console.print(f"[green]Results saved:[/green] {results_path}")

    db.close()


if __name__ == "__main__":
    app()
