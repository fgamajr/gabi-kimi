"""Extração de metadados de páginas web.

Extrai metadados estruturados de HTML: OpenGraph, Twitter Cards,
schema.org, metadados padrão e metadados específicos.
Baseado em CRAWLER.md §3.5.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class PageMetadata:
    """Metadados extraídos de uma página web.
    
    Attributes:
        url: URL da página
        title: Título da página
        description: Descrição/meta description
        author: Autor do conteúdo
        published_date: Data de publicação
        modified_date: Data de modificação
        language: Idioma detectado
        keywords: Palavras-chave
        canonical_url: URL canônica
        og_title: OpenGraph title
        og_description: OpenGraph description
        og_image: OpenGraph image
        og_type: OpenGraph type
        twitter_card: Twitter card type
        twitter_title: Twitter title
        twitter_description: Twitter description
        twitter_image: Twitter image
        schema_org: Dados schema.org extraídos
        headings: Hierarquia de headings (h1-h6)
        links_count: Número de links na página
        images_count: Número de imagens
        word_count: Contagem aproximada de palavras
        reading_time_minutes: Tempo estimado de leitura
        extracted_at: Timestamp de extração
    """
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    published_date: Optional[datetime] = None
    modified_date: Optional[datetime] = None
    language: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    canonical_url: Optional[str] = None
    
    # OpenGraph
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image: Optional[str] = None
    og_type: Optional[str] = None
    og_site_name: Optional[str] = None
    og_locale: Optional[str] = None
    
    # Twitter Cards
    twitter_card: Optional[str] = None
    twitter_title: Optional[str] = None
    twitter_description: Optional[str] = None
    twitter_image: Optional[str] = None
    twitter_site: Optional[str] = None
    twitter_creator: Optional[str] = None
    
    # Schema.org
    schema_org: Dict[str, Any] = field(default_factory=dict)
    
    # Estrutura
    headings: Dict[str, List[str]] = field(default_factory=dict)
    links_count: int = 0
    images_count: int = 0
    word_count: int = 0
    reading_time_minutes: int = 0
    
    # Metadados adicionais
    extra: Dict[str, Any] = field(default_factory=dict)
    extracted_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário."""
        return {
            "url": self.url,
            "title": self.title,
            "description": self.description,
            "author": self.author,
            "published_date": self.published_date.isoformat() if self.published_date else None,
            "modified_date": self.modified_date.isoformat() if self.modified_date else None,
            "language": self.language,
            "keywords": self.keywords,
            "canonical_url": self.canonical_url,
            "opengraph": {
                "title": self.og_title,
                "description": self.og_description,
                "image": self.og_image,
                "type": self.og_type,
                "site_name": self.og_site_name,
                "locale": self.og_locale,
            },
            "twitter_card": {
                "card": self.twitter_card,
                "title": self.twitter_title,
                "description": self.twitter_description,
                "image": self.twitter_image,
                "site": self.twitter_site,
                "creator": self.twitter_creator,
            },
            "schema_org": self.schema_org,
            "structure": {
                "headings": self.headings,
                "links_count": self.links_count,
                "images_count": self.images_count,
                "word_count": self.word_count,
                "reading_time_minutes": self.reading_time_minutes,
            },
            "extra": self.extra,
            "extracted_at": self.extracted_at.isoformat(),
        }


class MetadataExtractor:
    """Extrator de metadados de HTML.
    
    Extrai informações estruturadas de páginas web usando
    múltiplas fontes: meta tags, OpenGraph, Twitter Cards,
    schema.org (JSON-LD e microdata).
    
    Attributes:
        include_raw: Se deve incluir HTML raw nos resultados
        max_description_length: Tamanho máximo da descrição
    """
    
    # Mapeamento de meta tags para atributos
    META_MAPPINGS = {
        "description": ["description", "og:description", "twitter:description"],
        "title": ["title", "og:title", "twitter:title"],
        "author": ["author", "article:author", "og:article:author"],
        "keywords": ["keywords", "news_keywords"],
        "language": ["language", "og:locale"],
        "published_date": [
            "article:published_time",
            "article:published",
            "published_date",
            "datePublished",
            "date",
        ],
        "modified_date": [
            "article:modified_time",
            "article:modified",
            "modified_date",
            "dateModified",
        ],
    }
    
    def __init__(
        self,
        include_raw: bool = False,
        max_description_length: int = 500,
    ):
        self.include_raw = include_raw
        self.max_description_length = max_description_length
    
    def extract(self, html: str, url: str) -> PageMetadata:
        """Extrai metadados de HTML.
        
        Args:
            html: Conteúdo HTML
            url: URL da página (para resolver URLs relativas)
            
        Returns:
            Metadados extraídos
        """
        soup = BeautifulSoup(html, 'html.parser')
        metadata = PageMetadata(url=url)
        
        # Extrai informações básicas
        self._extract_basic(soup, metadata, url)
        
        # Extrai OpenGraph
        self._extract_opengraph(soup, metadata)
        
        # Extrai Twitter Cards
        self._extract_twitter_cards(soup, metadata)
        
        # Extrai Schema.org
        self._extract_schema_org(soup, metadata)
        
        # Extrai headings
        self._extract_headings(soup, metadata)
        
        # Conta elementos
        self._count_elements(soup, metadata)
        
        # Estima tempo de leitura
        self._estimate_reading_time(soup, metadata)
        
        # Resolve URLs relativas
        self._resolve_urls(metadata, url)
        
        return metadata
    
    def _extract_basic(self, soup: BeautifulSoup, metadata: PageMetadata, url: str) -> None:
        """Extrai metadados básicos."""
        # Title
        title_tag = soup.find('title')
        if title_tag:
            metadata.title = self._clean_text(title_tag.get_text())
        
        # Meta tags
        meta_tags = soup.find_all('meta')
        for meta in meta_tags:
            name = meta.get('name', '').lower()
            prop = meta.get('property', '').lower()
            content = meta.get('content', '')
            
            if not content:
                continue
            
            # Description
            if name in ('description',) or prop in ('og:description',):
                if not metadata.description:
                    metadata.description = self._truncate(content, self.max_description_length)
            
            # Author
            if name in ('author', 'article:author') or prop in ('article:author',):
                if not metadata.author:
                    metadata.author = content
            
            # Keywords
            if name == 'keywords':
                metadata.keywords = [k.strip() for k in content.split(',')]
            
            # Language
            if name == 'language':
                metadata.language = content
            
            # Canonical
            if name == 'canonical':
                metadata.canonical_url = content
        
        # HTML lang attribute
        html_tag = soup.find('html')
        if html_tag and not metadata.language:
            metadata.language = html_tag.get('lang')
        
        # Canonical link
        canonical_link = soup.find('link', rel='canonical')
        if canonical_link:
            metadata.canonical_url = canonical_link.get('href')
        
        # Dublincore
        dc_date = soup.find('meta', {'name': 'DC.Date'})
        if dc_date:
            date_str = dc_date.get('content', '')
            metadata.published_date = self._parse_date(date_str)
    
    def _extract_opengraph(self, soup: BeautifulSoup, metadata: PageMetadata) -> None:
        """Extrai OpenGraph tags."""
        og_properties = {
            'og:title': 'og_title',
            'og:description': 'og_description',
            'og:image': 'og_image',
            'og:type': 'og_type',
            'og:site_name': 'og_site_name',
            'og:locale': 'og_locale',
            'og:url': None,  # Tratado separadamente
            'og:article:published_time': 'published_date',
            'og:article:modified_time': 'modified_date',
            'og:article:author': 'author',
        }
        
        for prop_name, attr_name in og_properties.items():
            tag = soup.find('meta', property=prop_name)
            if tag:
                content = tag.get('content', '')
                
                if attr_name == 'published_date' or attr_name == 'modified_date':
                    date_val = self._parse_date(content)
                    if date_val:
                        setattr(metadata, attr_name, date_val)
                elif attr_name:
                    setattr(metadata, attr_name, content)
        
        # Fallback para title/description
        if not metadata.title and metadata.og_title:
            metadata.title = metadata.og_title
        if not metadata.description and metadata.og_description:
            metadata.description = metadata.og_description
    
    def _extract_twitter_cards(self, soup: BeautifulSoup, metadata: PageMetadata) -> None:
        """Extrai Twitter Card tags."""
        twitter_properties = {
            'twitter:card': 'twitter_card',
            'twitter:title': 'twitter_title',
            'twitter:description': 'twitter_description',
            'twitter:image': 'twitter_image',
            'twitter:image:src': 'twitter_image',
            'twitter:site': 'twitter_site',
            'twitter:creator': 'twitter_creator',
        }
        
        for prop_name, attr_name in twitter_properties.items():
            tag = soup.find('meta', attrs={'name': prop_name})
            if not tag:
                tag = soup.find('meta', property=prop_name)
            if tag:
                content = tag.get('content', '')
                setattr(metadata, attr_name, content)
        
        # Fallback
        if not metadata.title and metadata.twitter_title:
            metadata.title = metadata.twitter_title
        if not metadata.description and metadata.twitter_description:
            metadata.description = metadata.twitter_description
    
    def _extract_schema_org(self, soup: BeautifulSoup, metadata: PageMetadata) -> None:
        """Extrai Schema.org (JSON-LD e microdata)."""
        # JSON-LD
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string or '{}')
                self._process_schema_org(data, metadata)
            except json.JSONDecodeError:
                continue
        
        # Microdata (simplificado)
        # Extrai apenas items de alto nível
        microdata_items = soup.find_all(attrs={'itemscope': True})
        for item in microdata_items[:5]:  # Limita a 5 items
            item_type = item.get('itemtype', '')
            if 'schema.org' in item_type:
                props = item.find_all(attrs={'itemprop': True})
                item_data = {'@type': item_type.split('/')[-1] if '/' in item_type else item_type}
                for prop in props:
                    prop_name = prop.get('itemprop')
                    if prop_name:
                        item_data[prop_name] = prop.get_text(strip=True)
                
                if 'schema_org' not in metadata.extra:
                    metadata.extra['microdata'] = []
                metadata.extra['microdata'].append(item_data)
    
    def _process_schema_org(self, data: Dict[str, Any], metadata: PageMetadata) -> None:
        """Processa dados Schema.org."""
        if not isinstance(data, dict):
            return
        
        schema_type = data.get('@type', '').lower()
        metadata.schema_org['type'] = data.get('@type')
        metadata.schema_org['context'] = data.get('@context')
        
        # Artigos/NewsArticle
        if schema_type in ('article', 'newsarticle', 'blogposting', 'scholarlyarticle'):
            if 'headline' in data and not metadata.title:
                metadata.title = data['headline']
            if 'description' in data and not metadata.description:
                metadata.description = data['description']
            if 'author' in data:
                author = data['author']
                if isinstance(author, dict):
                    metadata.author = author.get('name')
                elif isinstance(author, str):
                    metadata.author = author
            if 'datePublished' in data and not metadata.published_date:
                metadata.published_date = self._parse_date(data['datePublished'])
            if 'dateModified' in data and not metadata.modified_date:
                metadata.modified_date = self._parse_date(data['dateModified'])
            if 'keywords' in data:
                if isinstance(data['keywords'], str):
                    metadata.keywords = [k.strip() for k in data['keywords'].split(',')]
                elif isinstance(data['keywords'], list):
                    metadata.keywords = data['keywords']
            if 'inLanguage' in data and not metadata.language:
                metadata.language = data['inLanguage']
        
        # WebPage
        elif schema_type == 'webpage':
            if 'name' in data and not metadata.title:
                metadata.title = data['name']
            if 'description' in data and not metadata.description:
                metadata.description = data['description']
        
        # Armazena dados brutos
        metadata.schema_org['raw'] = data
    
    def _extract_headings(self, soup: BeautifulSoup, metadata: PageMetadata) -> None:
        """Extrai hierarquia de headings."""
        for level in range(1, 7):
            headings = soup.find_all(f'h{level}')
            if headings:
                metadata.headings[f'h{level}'] = [
                    self._clean_text(h.get_text()) 
                    for h in headings
                ]
    
    def _count_elements(self, soup: BeautifulSoup, metadata: PageMetadata) -> None:
        """Conta elementos na página."""
        # Links
        metadata.links_count = len(soup.find_all('a', href=True))
        
        # Imagens
        metadata.images_count = len(soup.find_all('img'))
        
        # Palavras (aproximação)
        text = soup.get_text(separator=' ', strip=True)
        metadata.word_count = len(text.split())
    
    def _estimate_reading_time(self, soup: BeautifulSoup, metadata: PageMetadata) -> None:
        """Estima tempo de leitura em minutos.
        
        Usa média de 200 palavras por minuto.
        """
        if metadata.word_count > 0:
            # Média de 200 palavras por minuto
            metadata.reading_time_minutes = max(1, metadata.word_count // 200)
    
    def _resolve_urls(self, metadata: PageMetadata, base_url: str) -> None:
        """Resolve URLs relativas para absolutas."""
        url_fields = [
            'canonical_url', 'og_image', 'twitter_image'
        ]
        
        for field_name in url_fields:
            value = getattr(metadata, field_name)
            if value:
                resolved = urljoin(base_url, value)
                setattr(metadata, field_name, resolved)
    
    def _clean_text(self, text: str) -> str:
        """Limpa texto extraído."""
        if not text:
            return ""
        # Remove whitespace excessivo
        text = ' '.join(text.split())
        return text.strip()
    
    def _truncate(self, text: str, max_length: int) -> str:
        """Trunca texto para tamanho máximo."""
        if len(text) <= max_length:
            return text
        return text[:max_length-3] + "..."
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parseia string de data em múltiplos formatos."""
        if not date_str:
            return None
        
        # Limpa a string
        date_str = date_str.strip()
        
        # Formatos comuns
        formats = [
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d',
            '%d/%m/%Y',
            '%d/%m/%Y %H:%M:%S',
            '%B %d, %Y',
            '%b %d, %Y',
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        # Tenta ISO format
        try:
            from datetime import timezone
            # Remove Z no final se presente
            if date_str.endswith('Z'):
                date_str = date_str[:-1] + '+00:00'
            return datetime.fromisoformat(date_str)
        except ValueError:
            pass
        
        logger.debug(f"Não foi possível parsear data: {date_str}")
        return None


class LegalDocumentExtractor:
    """Extrator especializado para documentos jurídicos.
    
    Extrai metadados específicos de documentos jurídicos:
    - Número de processo
    - Data da decisão
    - Órgão/Relator
    - Ementa
    - Partes
    """
    
    # Padrões regex para documentos jurídicos brasileiros
    PROCESSO_PATTERN = re.compile(
        r'(?:processo|proc\.?)\s*n?[°º]?\s*(\d{5,}[\-\./]?\d*)',
        re.IGNORECASE
    )
    
    ACORDAO_PATTERN = re.compile(
        r'(?:acórdão|acordao)\s*n?[°º]?\s*(\d+)[\s/]*(\d{4})?',
        re.IGNORECASE
    )
    
    DATA_SESSAO_PATTERN = re.compile(
        r'(?:sessão|sessao|data\s*da\s*sessão)\s*[\w\s,]*?(\d{1,2})\s*de\s*(\w+)\s*de\s*(\d{4})',
        re.IGNORECASE
    )
    
    RELATOR_PATTERN = re.compile(
        r'(?:relator|relatoria)[\s:]+\w+\.?\s*(?:min\.?|des\.)?\s*([\w\s]+?)(?:,|\n|$)',
        re.IGNORECASE
    )
    
    def extract(self, html: str, url: str) -> Dict[str, Any]:
        """Extrai metadados jurídicos.
        
        Args:
            html: Conteúdo HTML
            url: URL da página
            
        Returns:
            Dicionário com metadados jurídicos
        """
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)
        
        result = {
            "url": url,
            "processo_numero": None,
            "acordao_numero": None,
            "acordao_ano": None,
            "data_sessao": None,
            "relator": None,
            "ementa": None,
            "partes": [],
            "dispositivo": None,
        }
        
        # Extrai número de processo
        proc_match = self.PROCESSO_PATTERN.search(text)
        if proc_match:
            result["processo_numero"] = proc_match.group(1)
        
        # Extrai número do acórdão
        acordao_match = self.ACORDAO_PATTERN.search(text)
        if acordao_match:
            result["acordao_numero"] = acordao_match.group(1)
            result["acordao_ano"] = acordao_match.group(2)
        
        # Extrai data da sessão
        data_match = self.DATA_SESSAO_PATTERN.search(text)
        if data_match:
            try:
                dia, mes, ano = data_match.groups()
                meses = {
                    'janeiro': 1, 'fevereiro': 2, 'março': 3, 'abril': 4,
                    'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8,
                    'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12
                }
                mes_num = meses.get(mes.lower(), 1)
                result["data_sessao"] = f"{ano}-{mes_num:02d}-{int(dia):02d}"
            except (ValueError, AttributeError):
                pass
        
        # Extrai relator
        rel_match = self.RELATOR_PATTERN.search(text)
        if rel_match:
            result["relator"] = rel_match.group(1).strip()
        
        # Tenta extrair ementa (texto entre "EMENTA" e próxima seção)
        ementa_match = re.search(
            r'(?:EMENTA|E\s*M\s*E\s*N\s*T\s*A)[\s:]+(.+?)(?:ACÓRDÃO|RELATÓRIO|VOTO|$)',
            text,
            re.IGNORECASE | re.DOTALL
        )
        if ementa_match:
            result["ementa"] = self._clean_ementa(ementa_match.group(1))
        
        # Tenta extrair dispositivo
        dispo_match = re.search(
            r'(?:DISPOSITIVO|D\s*I\s*S\s*P\s*O\s*S\s*I\s*T\s*I\s*V\s*O)[\s:]+(.+?)(?:VOTO|EMENTA|$)',
            text,
            re.IGNORECASE | re.DOTALL
        )
        if dispo_match:
            result["dispositivo"] = self._clean_ementa(dispo_match.group(1))
        
        return result
    
    def _clean_ementa(self, text: str) -> str:
        """Limpa texto de ementa."""
        # Remove espaços excessivos
        text = ' '.join(text.split())
        # Remove quebras de linha
        text = text.replace('\n', ' ')
        return text.strip()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "PageMetadata",
    "MetadataExtractor",
    "LegalDocumentExtractor",
]
