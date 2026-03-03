"""INLabs DOU XML Parser - Reference Implementation.

This module provides robust parsing for INLabs DOU XML files with proper
handling of encoding, CDATA sections, and edge cases.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DOUArticle:
    """Parsed DOU article from INLabs XML."""
    
    # Core identifiers
    id: str
    id_materia: str
    id_oficio: str
    name: str
    
    # Publication info
    pub_name: str  # DO1, DO1E, DO2, DO3
    pub_date: str  # DD/MM/YYYY
    edition_number: str
    number_page: str
    pdf_page: str
    
    # Content classification
    art_type: str  # Portaria, Resolução, etc.
    art_category: str  # Full organizational path
    art_class: str  # 12-level hierarchy code
    art_size: str  # Font size
    art_notes: str  # Extra edition markers
    
    # Highlight flags (usually empty)
    highlight_type: str
    highlight_priority: str
    highlight: str
    highlight_image: str
    highlight_image_name: str
    
    # Body content
    identifica: str  # Title
    data: str  # Date field (usually empty)
    ementa: str  # Summary/abstract
    titulo: str  # Title
    sub_titulo: str  # Subtitle
    texto: str  # HTML content
    
    @property
    def is_extra_edition(self) -> bool:
        """Check if article is from an extraordinary edition."""
        return bool(self.art_notes and self.art_notes.upper() == "EXTRA")
    
    @property
    def html_content(self) -> str:
        """Get HTML content from Texto element."""
        return self.texto
    
    @property
    def organization_path(self) -> list[str]:
        """Get artCategory as list of organization levels."""
        return self.art_category.split("/") if self.art_category else []
    
    @property
    def art_class_hierarchy(self) -> list[str]:
        """Get non-zero artClass levels."""
        if not self.art_class:
            return []
        parts = self.art_class.split(":")
        return [p for p in parts if p != "00000"]


class INLabsXMLParser:
    """Parser for INLabs DOU XML files."""
    
    def __init__(self, encoding: str = "utf-8-sig") -> None:
        """Initialize parser.
        
        Args:
            encoding: File encoding. Default utf-8-sig handles BOM.
        """
        self.encoding = encoding
    
    def parse_file(self, filepath: Path | str) -> DOUArticle:
        """Parse a single XML file.
        
        Args:
            filepath: Path to XML file
            
        Returns:
            Parsed DOUArticle
            
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If XML is invalid or missing required elements
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"XML file not found: {filepath}")
        
        content = filepath.read_text(encoding=self.encoding)
        return self.parse_string(content)
    
    def parse_string(self, xml_content: str) -> DOUArticle:
        """Parse XML content from string.
        
        Args:
            xml_content: XML string content
            
        Returns:
            Parsed DOUArticle
            
        Raises:
            ValueError: If XML is invalid
        """
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}") from e
        
        # Find article element
        article = root.find(".//article")
        if article is None and root.tag == "article":
            article = root
        
        if article is None:
            raise ValueError("No <article> element found in XML")
        
        # Extract body content
        body = article.find("body")
        if body is None:
            raise ValueError("No <body> element found in article")
        
        body_content = self._extract_body_content(body)
        
        return DOUArticle(
            id=article.get("id", ""),
            id_materia=article.get("idMateria", ""),
            id_oficio=article.get("idOficio", ""),
            name=article.get("name", ""),
            pub_name=article.get("pubName", ""),
            pub_date=article.get("pubDate", ""),
            edition_number=article.get("editionNumber", ""),
            number_page=article.get("numberPage", ""),
            pdf_page=article.get("pdfPage", ""),
            art_type=article.get("artType", ""),
            art_category=article.get("artCategory", ""),
            art_class=article.get("artClass", ""),
            art_size=article.get("artSize", ""),
            art_notes=article.get("artNotes", ""),
            highlight_type=article.get("highlightType", ""),
            highlight_priority=article.get("highlightPriority", ""),
            highlight=article.get("highlight", ""),
            highlight_image=article.get("highlightimage", ""),
            highlight_image_name=article.get("highlightimagename", ""),
            **body_content
        )
    
    def _extract_body_content(self, body: ET.Element) -> dict[str, str]:
        """Extract content from body element children.
        
        Args:
            body: The body Element
            
        Returns:
            Dict with Identifica, Data, Ementa, Titulo, SubTitulo, Texto content
        """
        def get_text(elem: ET.Element | None) -> str:
            """Extract text content including CDATA."""
            if elem is None:
                return ""
            # ElementTree preserves CDATA in .text
            return elem.text or ""
        
        return {
            "identifica": get_text(body.find("Identifica")),
            "data": get_text(body.find("Data")),
            "ementa": get_text(body.find("Ementa")),
            "titulo": get_text(body.find("Titulo")),
            "sub_titulo": get_text(body.find("SubTitulo")),
            "texto": get_text(body.find("Texto")),
        }
    
    def validate(self, article: DOUArticle) -> list[str]:
        """Validate parsed article for completeness.
        
        Args:
            article: Parsed article to validate
            
        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        
        # Required fields
        required = {
            "id": article.id,
            "id_materia": article.id_materia,
            "art_type": article.art_type,
            "pub_date": article.pub_date,
            "art_category": article.art_category,
        }
        
        for field, value in required.items():
            if not value:
                errors.append(f"Missing required field: {field}")
        
        # Validate idMateria format (8 digits)
        if article.id_materia:
            if not (len(article.id_materia) == 8 and article.id_materia.isdigit()):
                errors.append(f"Invalid idMateria format: {article.id_materia}")
        
        # Validate pubName
        valid_pub_names = {"DO1", "DO1E", "DO2", "DO2E", "DO3", "DO3E"}
        if article.pub_name and article.pub_name not in valid_pub_names:
            errors.append(f"Unknown pubName: {article.pub_name}")
        
        return errors


def parse_inlabs_directory(directory: Path | str) -> list[DOUArticle]:
    """Parse all XML files in a directory.
    
    Args:
        directory: Directory containing XML files
        
    Returns:
        List of parsed articles
    """
    directory = Path(directory)
    parser = INLabsXMLParser()
    
    articles = []
    for xml_file in sorted(directory.glob("*.xml")):
        try:
            article = parser.parse_file(xml_file)
            articles.append(article)
        except Exception as e:
            print(f"Error parsing {xml_file}: {e}")
    
    return articles


def article_to_dict(article: DOUArticle) -> dict[str, Any]:
    """Convert DOUArticle to dictionary.
    
    Args:
        article: Article to convert
        
    Returns:
        Dictionary representation
    """
    return {
        "id": article.id,
        "id_materia": article.id_materia,
        "id_oficio": article.id_oficio,
        "name": article.name,
        "pub_name": article.pub_name,
        "pub_date": article.pub_date,
        "edition_number": article.edition_number,
        "number_page": article.number_page,
        "pdf_page": article.pdf_page,
        "art_type": article.art_type,
        "art_category": article.art_category,
        "art_class": article.art_class,
        "art_size": article.art_size,
        "art_notes": article.art_notes,
        "is_extra_edition": article.is_extra_edition,
        "organization_path": article.organization_path,
        "art_class_hierarchy": article.art_class_hierarchy,
        "body": {
            "identifica": article.identifica,
            "data": article.data,
            "ementa": article.ementa,
            "titulo": article.titulo,
            "sub_titulo": article.sub_titulo,
            "texto": article.texto,
        }
    }


# Example usage
if __name__ == "__main__":
    import json
    
    # Example: Parse a single file
    sample_file = Path("/tmp/inlabs_analysis/2026-02-27-DO1/515_20260227_23615168.xml")
    
    if sample_file.exists():
        parser = INLabsXMLParser()
        article = parser.parse_file(sample_file)
        
        print("Parsed Article:")
        print(f"  Type: {article.art_type}")
        print(f"  Category: {article.art_category}")
        print(f"  Title: {article.identifica}")
        print(f"  Is Extra: {article.is_extra_edition}")
        
        # Validate
        errors = parser.validate(article)
        if errors:
            print("\nValidation Errors:")
            for e in errors:
                print(f"  - {e}")
        else:
            print("\nValidation: PASSED")
        
        # Convert to dict
        data = article_to_dict(article)
        print("\nJSON Representation:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
