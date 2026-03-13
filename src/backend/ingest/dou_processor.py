import logging
import zipfile
import io
import re
import hashlib
import html
import os
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from lxml import etree
import requests

from src.backend.data.models.document import (
    DouDocument, Metadata, Usage, StructuredData, Reference, Image, Enrichment
)

logger = logging.getLogger(__name__)

class DouProcessor:
    def __init__(self):
        self.parser = etree.XMLParser(recover=True, encoding='utf-8')

    def parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string DD/MM/YYYY to datetime."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str.strip(), "%d/%m/%Y")
        except ValueError:
            logger.warning(f"Failed to parse date: {date_str}")
            return None

    def extract_text(self, element) -> str:
        """Extract text content from XML element, handling None."""
        if element is None:
            return ""
        # itertext() handles nested tags (like <b>, <i>) better than .text
        return "".join(element.itertext()).strip()
    
    def sanitize_html(self, html_content: str) -> str:
        """Basic sanitization of HTML content for full-text search."""
        if not html_content:
            return ""
        # Unescape HTML entities properly (handles &lt;, &nbsp;, etc.)
        text = html.unescape(html_content)
        # Remove HTML tags using regex for a quick cleanup
        text = re.sub(r'<[^>]+>', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()

    def generate_id(self, date: datetime, section: str, identifica: str, texto: str = "") -> str:
        """Generate deterministic ID based on full content."""
        date_str = date.strftime("%Y-%m-%d")
        content_str = f"{date_str}{section}{identifica}{texto}"
        content_hash = hashlib.md5(content_str.encode('utf-8')).hexdigest()[:16]
        return f"{date_str}_{section}_{content_hash}"

    def extract_references(self, text: str) -> List[Reference]:
        """Extract legal references using regex."""
        references = []
        # Enhanced Pattern from user feedback: Type + Number + Year (optional)
        # Covers: Lei nº 8.112, Decreto 3.035, MP 2.216-37
        pattern = r'(?P<type>Lei|Decreto|Medida Provisória|MP|Instrução Normativa|IN|Portaria|Resolução)\s+(?:n[ºo°]\s*)?(?P<target>[\d\.\-/]+(?:\/\d{2,4})?)'
        
        seen_targets = set()
        
        for match in re.finditer(pattern, text, re.IGNORECASE):
            ref_type_raw = match.group('type').lower()
            target = match.group('target').rstrip('.') # Remove trailing dot if picked up by regex
            full_ref = f"{match.group('type')} {target}"
            
            if full_ref in seen_targets:
                continue
            seen_targets.add(full_ref)
            
            # Normalize type
            ref_type = "outro"
            context = text[max(0, match.start()-30):match.start()].lower()
            if "lei" in ref_type_raw: ref_type = "cita" # Generic citation
            elif "decreto" in ref_type_raw: ref_type = "cita"
            
            if "revoga" in context:
                ref_type = "revoga"
            elif "altera" in context:
                ref_type = "altera"
                
            references.append(Reference(type=ref_type, target=full_ref))
            
        return references

    def extract_structured_data(self, identifica: str, texto: str, html_content: str = "", pub_date: datetime = None) -> Optional[StructuredData]:
        """Extract structured data like Act Number and Year."""
        act_number = None
        act_year = None
        signer = None
        
        # Act Number
        match_num = re.search(r'N[ºo°]\s*([\d\.\-]+)', identifica, re.IGNORECASE)
        if match_num:
            act_number = match_num.group(1)
            
        # Year (simple heuristic from pub_date usually, but let's check Identifica)
        match_year = re.search(r'\b(19|20)\d{2}\b', identifica)
        if match_year:
            act_year = int(match_year.group(1))
        elif pub_date:
            act_year = pub_date.year

        # Signer extraction: Check HTML for class='assina' or centered text at end
        if html_content:
            try:
                # Basic parsing of the HTML fragment to find <p class="assina">
                # We use regex here to avoid full lxml overhead if not needed, or lxml.html.fragment_fromstring
                # But simple regex is robust enough for class="assina"
                match_signer = re.search(r'<p[^>]*class=["\']assina["\'][^>]*>(.*?)</p>', html_content, re.IGNORECASE | re.DOTALL)
                if match_signer:
                    signer_raw = match_signer.group(1)
                    # Clean up HTML tags inside signer if any
                    signer = re.sub(r'<[^>]+>', '', signer_raw).strip()
            except Exception:
                pass

        # Fallback to text heuristic if not found in HTML
        if not signer:
            lines = texto.splitlines()
            if lines:
                last_lines = lines[-10:] # Check last 10 lines
                for line in reversed(last_lines):
                    clean_line = line.strip()
                    if len(clean_line) > 5 and clean_line.isupper() and "MINISTRO" not in clean_line and "PRESIDENTE" not in clean_line:
                        # Avoid lines that are just titles
                        signer = clean_line
                        break
        
        return StructuredData(act_number=act_number, act_year=act_year, signer=signer)

    def extract_entities(self, text: str) -> List[str]:
        """Extract affected entities (heuristic)."""
        entities = []
        # Expanded list based on user feedback
        potential_orgs = [
            "Receita Federal", "PGFN", "Banco Central", "Tesouro Nacional", 
            "Polícia Federal", "INSS", "Ibama", "Incra", "Funai",
            "Casa Civil", "Presidência da República", 
            "Secretaria de Estado", "Ministério da Fazenda", "Ministério da Justiça",
            "Advocacia-Geral da União", "Controladoria-Geral da União"
        ]
        
        text_lower = text.lower()
        for org in potential_orgs:
            if org.lower() in text_lower:
                entities.append(org)
                
        return sorted(list(set(entities)))

    def process_xml(self, xml_content: bytes, filename: str, zip_filename: str) -> Optional[DouDocument]:
        """Process a single XML file content into a DouDocument."""
        try:
            root = etree.fromstring(xml_content, parser=self.parser)
            
            # Navigate to the article body
            # Structure: <xml><article><body>...</body></article></xml>
            article = root.find(".//article")
            if article is None:
                # Fallback for simpler structures if any
                return None

            body = article.find("body")
            if body is None:
                return None

            # Extract Metadata from attributes
            attribs = article.attrib
            pub_date_str = attribs.get("pubDate")
            pub_date = self.parse_date(pub_date_str)
            
            if not pub_date:
                logger.error(f"Missing or invalid pubDate in {filename}: {pub_date_str}")
                return None

            section = attribs.get("pubName", "Unknown")
            art_type = attribs.get("artType")
            art_category = attribs.get("artCategory")
            edition = attribs.get("editionNumber")
            page_str = attribs.get("numberPage")
            page = int(page_str) if page_str and page_str.isdigit() else None
            
            # 5. Fix: Orgao vs Category swap
            # art_category often contains the full path "Presidência da República/Casa Civil"
            # We want the root orgao.
            orgao = None
            if art_category:
                parts = art_category.split('/')
                orgao = parts[0].strip() # "Presidência da República"
            
            # If Orgao looks like "Atos do Poder Executivo", that's a category, check if we can dig deeper
            if orgao == "Atos do Poder Executivo" and len(parts) > 1:
                orgao = parts[1].strip()

            # Extract Content
            identifica_elem = body.find("Identifica")
            identifica = self.extract_text(identifica_elem)
            
            ementa_elem = body.find("Ementa")
            ementa = self.extract_text(ementa_elem)
            
            texto_elem = body.find("Texto")
            texto_html = ""
            if texto_elem is not None:
                # tostring returns bytes, decode to string
                # Unescape to handle both real XML tags and escaped HTML content
                raw_html = etree.tostring(texto_elem, encoding="unicode", method="html")
                texto_html = html.unescape(raw_html)
                # Strip wrapper <Texto> tags to get just the content
                texto_html = re.sub(r'^<Texto[^>]*>', '', texto_html).strip()
                texto_html = re.sub(r'</Texto>$', '', texto_html).strip()
            
            data_text_elem = body.find("Data")
            data_text = self.extract_text(data_text_elem)

            # 7. Fix: Sanitize content (HTML entities)
            texto_plain = self.sanitize_html(texto_html)
            
            # 8. Fix: Fallback for data_text
            if not data_text and pub_date:
                # Attempt to extract from text end
                # "Brasília, 3 de janeiro de 2002"
                match_date = re.search(r'(Brasília|Rio de Janeiro)[^,]*,\s*\d+\s+de\s+\w+\s+de\s+\d{4}', texto_plain)
                if match_date:
                    data_text = match_date.group(0)

            # 1. Fix: Deterministic ID (full content hash to avoid collisions)
            doc_id = self.generate_id(pub_date, section, identifica, texto_plain)
            
            # 3. & 10. Extract Structured Data & References
            structured = self.extract_structured_data(identifica, texto_plain, html_content=texto_html, pub_date=pub_date)
            references = self.extract_references(texto_plain)
            
            # 4. Affected Entities
            affected_entities = self.extract_entities(texto_plain)

            # 9. Enrichment (Heuristic)
            enrichment = None
            if art_type and art_type.upper() in ["DECRETO", "LEI", "EMENDA CONSTITUCIONAL", "MEDIDA PROVISÓRIA"]:
                enrichment = Enrichment(
                    relevance_score=0.9,
                    category="Legislação Principal"
                )
            elif art_type and art_type.upper() in ["PORTARIA", "RESOLUÇÃO"]:
                 enrichment = Enrichment(
                    relevance_score=0.7,
                    category="Atos Administrativos"
                )
            else:
                 enrichment = Enrichment(
                    relevance_score=0.5,
                    category="Outros"
                )

            # Create Document
            doc = DouDocument(
                _id=doc_id,
                source_id=filename,
                source_zip=zip_filename,
                source_type="liferay", # 2. Fix: Correct source type
                pub_date=pub_date,
                section=section,
                edition=edition,
                page=page,
                art_type=art_type,
                art_category=art_category,
                orgao=orgao,
                identifica=identifica,
                ementa=ementa,
                texto=texto_plain, # Searchable text (cleaned)
                content_html=texto_html, # Display HTML (preserved)
                data_text=data_text,
                structured=structured,
                references=references,
                affected_entities=affected_entities,
                enrichment=enrichment,
                metadata=Metadata(
                    origin_file=filename,
                    processing_version="v2.2" # Bump version
                )
            )
            
            return doc

        except Exception as e:
            logger.error(f"Error processing {filename}: {e}")
            return None

    def process_zip(self, zip_bytes: bytes, zip_filename: str, extract_to: Optional[str] = None) -> List[DouDocument]:
        """Process a ZIP file containing multiple XMLs."""
        import os
        documents = []
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                # If extract path provided, extract all contents first
                if extract_to:
                    # Create subfolder for this zip
                    zip_name_no_ext = os.path.splitext(zip_filename)[0]
                    target_dir = os.path.join(extract_to, zip_name_no_ext)
                    os.makedirs(target_dir, exist_ok=True)
                    z.extractall(target_dir)
                    logger.info(f"Extracted {zip_filename} to {target_dir}")

                for filename in z.namelist():
                    if filename.lower().endswith(".xml"):
                        with z.open(filename) as f:
                            xml_content = f.read()
                            doc = self.process_xml(xml_content, filename, zip_filename)
                            if doc:
                                documents.append(doc)
        except zipfile.BadZipFile:
            logger.error(f"Bad ZIP file: {zip_filename}")
        except Exception as e:
            logger.error(f"Error processing ZIP {zip_filename}: {e}")
        
        return documents
