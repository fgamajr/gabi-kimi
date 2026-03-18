"""PDF generation using weasyprint."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def generate_pdf(html_content: str) -> bytes:
    """Convert HTML string to PDF bytes via weasyprint."""
    from weasyprint import HTML  # lazy import — weasyprint is heavy

    doc = HTML(string=html_content)
    return doc.write_pdf()
