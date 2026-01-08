"""PDF processing for full-text screening and extraction."""

import base64
import logging
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)

# Maximum size for PDF content sent to Claude (in bytes)
MAX_PDF_SIZE = 32 * 1024 * 1024  # 32 MB

# Maximum pages to process for text extraction
MAX_PAGES_TEXT = 100


class PDFError(Exception):
    """Error processing a PDF."""


class PDFProcessor:
    """Processes PDFs for use with Claude API."""

    def read_pdf_as_base64(self, path: Path) -> str:
        """
        Read a PDF file and return it as base64.

        Args:
            path: Path to the PDF file

        Returns:
            Base64-encoded PDF content

        Raises:
            PDFError: If the file cannot be read or is too large
        """
        if not path.exists():
            raise PDFError(f"PDF file not found: {path}")

        file_size = path.stat().st_size
        if file_size > MAX_PDF_SIZE:
            raise PDFError(f"PDF file too large ({file_size} bytes > {MAX_PDF_SIZE} bytes): {path}")

        try:
            with open(path, "rb") as f:
                content = f.read()
            return base64.standard_b64encode(content).decode("utf-8")
        except Exception as e:
            raise PDFError(f"Failed to read PDF: {e}") from e

    def read_pdf_bytes(self, path: Path) -> bytes:
        """
        Read a PDF file and return raw bytes.

        Args:
            path: Path to the PDF file

        Returns:
            PDF content as bytes

        Raises:
            PDFError: If the file cannot be read
        """
        if not path.exists():
            raise PDFError(f"PDF file not found: {path}")

        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception as e:
            raise PDFError(f"Failed to read PDF: {e}") from e

    def extract_text(self, path: Path, max_pages: int | None = None) -> str:
        """
        Extract text content from a PDF using PyMuPDF.

        This is a fallback for when the PDF is too large for Claude's
        document processing or when text extraction is preferred.

        Args:
            path: Path to the PDF file
            max_pages: Maximum number of pages to extract (default: MAX_PAGES_TEXT)

        Returns:
            Extracted text content

        Raises:
            PDFError: If text extraction fails
        """
        if not path.exists():
            raise PDFError(f"PDF file not found: {path}")

        max_pages = max_pages or MAX_PAGES_TEXT

        try:
            doc = pymupdf.open(path)
            text_parts = []

            page_count = min(len(doc), max_pages)
            for page_num in range(page_count):
                page = doc[page_num]
                text = str(page.get_text())
                if text.strip():
                    text_parts.append(f"--- Page {page_num + 1} ---\n{text}")

            if len(doc) > max_pages:
                text_parts.append(f"\n[... Truncated after {max_pages} pages ...]")

            doc.close()

            full_text = "\n\n".join(text_parts)

            if not full_text.strip():
                logger.warning("No text extracted from PDF (may be scanned/image-based): %s", path)
                raise PDFError("PDF appears to be image-based with no extractable text")

            return full_text

        except pymupdf.FileDataError as e:
            raise PDFError(f"Invalid or corrupted PDF: {e}") from e
        except Exception as e:
            if isinstance(e, PDFError):
                raise
            raise PDFError(f"Failed to extract text from PDF: {e}") from e

    def get_page_count(self, path: Path) -> int:
        """
        Get the number of pages in a PDF.

        Args:
            path: Path to the PDF file

        Returns:
            Number of pages

        Raises:
            PDFError: If the PDF cannot be opened
        """
        if not path.exists():
            raise PDFError(f"PDF file not found: {path}")

        try:
            doc = pymupdf.open(path)
            count = len(doc)
            doc.close()
            return count
        except Exception as e:
            raise PDFError(f"Failed to open PDF: {e}") from e

    def get_pdf_info(self, path: Path) -> dict:
        """
        Get metadata and info about a PDF.

        Args:
            path: Path to the PDF file

        Returns:
            Dictionary with PDF information

        Raises:
            PDFError: If the PDF cannot be opened
        """
        if not path.exists():
            raise PDFError(f"PDF file not found: {path}")

        try:
            doc = pymupdf.open(path)
            info = {
                "path": str(path),
                "page_count": len(doc),
                "file_size": path.stat().st_size,
                "metadata": doc.metadata,
            }
            doc.close()
            return info
        except Exception as e:
            raise PDFError(f"Failed to get PDF info: {e}") from e

    def prepare_for_claude(self, path: Path) -> tuple[str, str]:
        """
        Prepare a PDF for sending to Claude.

        Returns either base64-encoded PDF for document processing,
        or extracted text as a fallback.

        Args:
            path: Path to the PDF file

        Returns:
            Tuple of (content, content_type) where content_type is
            either "document" (base64 PDF) or "text" (extracted text)

        Raises:
            PDFError: If the PDF cannot be processed
        """
        if not path.exists():
            raise PDFError(f"PDF file not found: {path}")

        file_size = path.stat().st_size

        # If file is small enough, use document processing
        if file_size <= MAX_PDF_SIZE:
            try:
                base64_content = self.read_pdf_as_base64(path)
                return base64_content, "document"
            except PDFError:
                logger.warning("Failed to read PDF as base64, falling back to text extraction")

        # Fall back to text extraction
        text = self.extract_text(path)
        return text, "text"
