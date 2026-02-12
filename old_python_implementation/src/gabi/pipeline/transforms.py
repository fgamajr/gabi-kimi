"""Transforms de dados para o pipeline de ingestão.

Fornece funções de transformação idempotentes para processamento
de dados durante o pipeline de ingestão.
Baseado em CONTRACTS.md §2.4.
"""

import html
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Pattern, Union


# =============================================================================
# Registry de Transforms
# =============================================================================

class TransformRegistry:
    """Registro de transforms disponíveis.
    
    Mantém um registro de todas as funções de transformação
    disponíveis no sistema.
    """
    
    def __init__(self):
        """Inicializa o registro vazio."""
        self._transforms: Dict[str, Callable[[Any], Any]] = {}
    
    def register(self, name: str, func: Callable[[Any], Any]) -> None:
        """Registra uma função de transformação.
        
        Args:
            name: Nome único da transformação
            func: Função de transformação
        """
        self._transforms[name] = func
    
    def get(self, name: str) -> Optional[Callable[[Any], Any]]:
        """Retorna uma transformação pelo nome.
        
        Args:
            name: Nome da transformação
            
        Returns:
            Função de transformação ou None
        """
        return self._transforms.get(name)
    
    def list_transforms(self) -> List[str]:
        """Lista todas as transformações registradas.
        
        Returns:
            Lista de nomes de transformações
        """
        return list(self._transforms.keys())
    
    def has_transform(self, name: str) -> bool:
        """Verifica se uma transformação existe.
        
        Args:
            name: Nome da transformação
            
        Returns:
            True se a transformação existe
        """
        return name in self._transforms


# Instância global do registro
_transform_registry = TransformRegistry()


def register_transform(name: str) -> Callable:
    """Decorador para registrar uma transformação.
    
    Args:
        name: Nome da transformação
        
    Returns:
        Decorador que registra a função
    """
    def decorator(func: Callable[[Any], Any]) -> Callable[[Any], Any]:
        _transform_registry.register(name, func)
        return func
    return decorator


def get_transform(name: str) -> Optional[Callable[[Any], Any]]:
    """Retorna uma transformação pelo nome.
    
    Args:
        name: Nome da transformação
        
    Returns:
        Função de transformação ou None
    """
    return _transform_registry.get(name)


def list_transforms() -> List[str]:
    """Lista todas as transformações registradas.
    
    Returns:
        Lista de nomes de transformações
    """
    return _transform_registry.list_transforms()


def apply_transform(transform_name: str, value: Any) -> Any:
    """Aplica uma transformação a um valor.
    
    Args:
        transform_name: Nome da transformação
        value: Valor a ser transformado
        
    Returns:
        Valor transformado
        
    Raises:
        ValueError: Se a transformação não existir
    """
    transform = _transform_registry.get(transform_name)
    if transform is None:
        raise ValueError(f"Transform '{transform_name}' not found")
    return transform(value)


# =============================================================================
# String Transforms
# =============================================================================

@register_transform("strip_quotes")
def strip_quotes(value: str) -> str:
    """Remove aspas do início e fim da string.
    
    Args:
        value: String com possíveis aspas
        
    Returns:
        String sem aspas nas extremidades
    """
    if not isinstance(value, str):
        value = str(value)
    return value.strip('"\'')


@register_transform("normalize_whitespace")
def normalize_whitespace(value: str) -> str:
    """Normaliza espaços em branco (múltiplos espaços viram um).
    
    Args:
        value: String com espaços irregulares
        
    Returns:
        String com espaços normalizados
    """
    if not isinstance(value, str):
        value = str(value)
    return ' '.join(value.split())


@register_transform("uppercase")
def uppercase(value: str) -> str:
    """Converte para maiúsculas.
    
    Args:
        value: String a converter
        
    Returns:
        String em maiúsculas
    """
    if not isinstance(value, str):
        value = str(value)
    return value.upper()


@register_transform("lowercase")
def lowercase(value: str) -> str:
    """Converte para minúsculas.
    
    Args:
        value: String a converter
        
    Returns:
        String em minúsculas
    """
    if not isinstance(value, str):
        value = str(value)
    return value.lower()


@register_transform("strip_html")
def strip_html(value: str) -> str:
    """Remove tags HTML da string.
    
    Args:
        value: String com tags HTML
        
    Returns:
        String sem tags HTML
    """
    if not isinstance(value, str):
        value = str(value)
    # Remove tags HTML
    pattern: Pattern = re.compile(r'<[^>]+>')
    return pattern.sub('', value)


@register_transform("unescape_html")
def unescape_html_entities(value: str) -> str:
    """Converte entidades HTML para caracteres.
    
    Args:
        value: String com entidades HTML
        
    Returns:
        String com caracteres decodificados
    """
    if not isinstance(value, str):
        value = str(value)
    return html.unescape(value)


@register_transform("strip_accents")
def strip_accents(value: str) -> str:
    """Remove acentos de caracteres.
    
    Args:
        value: String com acentos
        
    Returns:
        String sem acentos
    """
    if not isinstance(value, str):
        value = str(value)
    normalized = unicodedata.normalize('NFD', value)
    return ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')


@register_transform("normalize_unicode")
def normalize_unicode(value: str, form: str = 'NFC') -> str:
    """Normaliza Unicode para a forma especificada.
    
    Args:
        value: String a normalizar
        form: Forma de normalização (NFC, NFD, NFKC, NFKD)
        
    Returns:
        String normalizada
    """
    if not isinstance(value, str):
        value = str(value)
    return unicodedata.normalize(form, value)


@register_transform("trim")
def trim(value: str) -> str:
    """Remove espaços em branco das extremidades.
    
    Args:
        value: String a trimar
        
    Returns:
        String sem espaços nas extremidades
    """
    if not isinstance(value, str):
        value = str(value)
    return value.strip()


@register_transform("collapse_newlines")
def collapse_newlines(value: str) -> str:
    """Colapsa múltiplas quebras de linha em uma.
    
    Args:
        value: String com múltiplas quebras
        
    Returns:
        String com quebras normalizadas
    """
    if not isinstance(value, str):
        value = str(value)
    return re.sub(r'\n+', '\n', value)


@register_transform("remove_extra_spaces")
def remove_extra_spaces(value: str) -> str:
    """Remove espaços duplicados no meio do texto.
    
    Args:
        value: String com espaços extras
        
    Returns:
        String sem espaços duplicados
    """
    if not isinstance(value, str):
        value = str(value)
    return re.sub(r' +', ' ', value)


@register_transform("remove_non_printable")
def remove_non_printable(value: str) -> str:
    """Remove caracteres não imprimíveis.
    
    Args:
        value: String com caracteres não imprimíveis
        
    Returns:
        String limpa
    """
    if not isinstance(value, str):
        value = str(value)
    return ''.join(char for char in value if char.isprintable() or char in '\n\r\t')


# =============================================================================
# Number Transforms
# =============================================================================

@register_transform("to_int")
def to_int(value: Any) -> int:
    """Converte valor para inteiro.
    
    Args:
        value: Valor a converter
        
    Returns:
        Valor como inteiro
        
    Raises:
        ValueError: Se não puder converter
    """
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        # Contexto brasileiro:
        # - 1.234,56 -> 1234.56 (formato BR com vírgula decimal)
        # - 1,234.56 -> 1234.56 (formato US misto)
        # - 1.234 -> 1234 (milhar BR)
        # - 1,234 -> 1234 (milhar US)
        # - 1,5 -> 1.5 (decimal com vírgula)
        value = value.strip()
        if ',' in value and '.' in value:
            # Tem ambos: verificar posição
            last_comma = value.rfind(',')
            last_dot = value.rfind('.')
            if last_comma > last_dot:
                # Vírgula vem depois: formato BR (1.234,56)
                cleaned = value.replace('.', '').replace(',', '.')
            else:
                # Ponto vem depois: formato US (1,234.56)
                cleaned = value.replace(',', '')
            return int(float(cleaned))
        elif ',' in value:
            # Só vírgula: separador de milhar se 3 dígitos depois
            parts = value.split(',')
            if len(parts) == 2 and len(parts[1]) == 3:
                # Separador de milhar: 1,234
                cleaned = value.replace(',', '')
            else:
                # Decimal: 1,5 -> 1.5
                cleaned = value.replace(',', '.')
            return int(float(cleaned))
        elif '.' in value:
            # Só ponto: separador de milhar se 3 dígitos depois
            parts = value.split('.')
            if len(parts) == 2 and len(parts[1]) == 3:
                # Separador de milhar: 1.234
                cleaned = value.replace('.', '')
            else:
                # Decimal: já está correto
                cleaned = value
            return int(float(cleaned))
        else:
            return int(value)
    return int(value)


@register_transform("to_float")
def to_float(value: Any) -> float:
    """Converte valor para float.
    
    Args:
        value: Valor a converter
        
    Returns:
        Valor como float
        
    Raises:
        ValueError: Se não puder converter
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Contexto brasileiro (mesma lógica de to_int)
        value = value.strip()
        if ',' in value and '.' in value:
            last_comma = value.rfind(',')
            last_dot = value.rfind('.')
            if last_comma > last_dot:
                # Formato BR: 1.234,56
                cleaned = value.replace('.', '').replace(',', '.')
            else:
                # Formato US: 1,234.56
                cleaned = value.replace(',', '')
            return float(cleaned)
        elif ',' in value:
            parts = value.split(',')
            if len(parts) == 2 and len(parts[1]) == 3:
                # Separador de milhar: 1,234
                cleaned = value.replace(',', '')
            else:
                # Decimal: 1,5 -> 1.5
                cleaned = value.replace(',', '.')
            return float(cleaned)
        elif '.' in value:
            parts = value.split('.')
            if len(parts) == 2 and len(parts[1]) == 3:
                # Separador de milhar: 1.234
                cleaned = value.replace('.', '')
            else:
                cleaned = value
            return float(cleaned)
        else:
            return float(value)
    return float(value)


@register_transform("format_currency_br")
def format_currency_br(value: Any) -> str:
    """Formata valor como moeda brasileira.
    
    Args:
        value: Valor numérico
        
    Returns:
        String formatada como R$ X.XXX,XX
    """
    try:
        num = float(value)
        return f"R$ {num:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except (ValueError, TypeError):
        return str(value)


# =============================================================================
# Date Transforms
# =============================================================================

@register_transform("parse_date_br")
def parse_date_br(value: str) -> Optional[str]:
    """Converte data brasileira (DD/MM/YYYY) para ISO (YYYY-MM-DD).
    
    Args:
        value: Data no formato brasileiro
        
    Returns:
        Data no formato ISO ou None
    """
    if not isinstance(value, str):
        value = str(value)
    
    value = value.strip()
    patterns = [
        (r'(\d{2})/(\d{2})/(\d{4})', '{2}-{1}-{0}'),  # DD/MM/YYYY
        (r'(\d{2})-(\d{2})-(\d{4})', '{2}-{1}-{0}'),  # DD-MM-YYYY
        (r'(\d{2})\.(\d{2})\.(\d{4})', '{2}-{1}-{0}'),  # DD.MM.YYYY
    ]
    
    for pattern, fmt in patterns:
        match = re.match(pattern, value)
        if match:
            day, month, year = match.groups()
            return f"{year}-{month}-{day}"
    
    return None


@register_transform("parse_datetime_iso")
def parse_datetime_iso(value: str) -> Optional[str]:
    """Normaliza datetime para formato ISO.
    
    Args:
        value: String de datetime
        
    Returns:
        Datetime no formato ISO ou None
    """
    if not isinstance(value, str):
        value = str(value)
    
    value = value.strip()
    
    # Se já está em ISO, retorna
    if re.match(r'\d{4}-\d{2}-\d{2}', value):
        return value
    
    return None


# =============================================================================
# Boolean Transforms
# =============================================================================

@register_transform("to_bool")
def to_bool(value: Any) -> bool:
    """Converte valor para booleano.
    
    Args:
        value: Valor a converter
        
    Returns:
        Valor como booleano
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'sim', 'verdadeiro', 's', 'y')
    return bool(value)


# =============================================================================
# Document Transforms
# =============================================================================

@register_transform("extract_process_number")
def extract_process_number(value: str) -> Optional[str]:
    """Extrai número de processo do formato TCU.
    
    Args:
        value: Texto contendo número de processo
        
    Returns:
        Número de processo normalizado ou None
    """
    if not isinstance(value, str):
        value = str(value)
    
    # Padrão: 12345.678901/2024-00
    pattern = r'(\d{5})\.?(\d{6})/(\d{4})-?(\d{2})'
    match = re.search(pattern, value)
    
    if match:
        return f"{match.group(1)}.{match.group(2)}/{match.group(3)}-{match.group(4)}"
    
    return None


@register_transform("extract_acordao_number")
def extract_acordao_number(value: str) -> Optional[str]:
    """Extrai número de acórdão do TCU.
    
    Args:
        value: Texto contendo número de acórdão
        
    Returns:
        Número de acórdão normalizado ou None
    """
    if not isinstance(value, str):
        value = str(value)
    
    # Padrões comuns: 1234/2024, AC 1234/2024, Acórdão 1234/2024
    pattern = r'(?:AC|Ac[óo]rd[aã]o)?\s*(\d{1,4})/(\d{4})'
    match = re.search(pattern, value, re.IGNORECASE)
    
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    
    return None


@register_transform("normalize_cpf_cnpj")
def normalize_cpf_cnpj(value: str) -> Optional[str]:
    """Normaliza CPF ou CNPJ (remove formatação).
    
    Args:
        value: CPF ou CNPJ formatado
        
    Returns:
        Apenas dígitos ou None
    """
    if not isinstance(value, str):
        value = str(value)
    
    digits = re.sub(r'\D', '', value)
    
    # Valida tamanho (CPF=11, CNPJ=14)
    if len(digits) in (11, 14):
        return digits
    
    return None


@register_transform("extract_year_from_text")
def extract_year_from_text(value: str) -> Optional[int]:
    """Extrai ano de um texto (1900-2099).
    
    Args:
        value: Texto contendo ano
        
    Returns:
        Ano como inteiro ou None
    """
    if not isinstance(value, str):
        value = str(value)
    
    pattern = r'\b(19|20)\d{2}\b'
    match = re.search(pattern, value)
    
    if match:
        return int(match.group(0))
    
    return None


# =============================================================================
# Pipeline Transforms
# =============================================================================

def apply_transforms(value: Any, transforms: List[str]) -> Any:
    """Aplica múltiplas transformações em sequência.
    
    Args:
        value: Valor inicial
        transforms: Lista de nomes de transformações
        
    Returns:
        Valor após todas as transformações
        
    Raises:
        ValueError: Se alguma transformação não existir
    """
    result = value
    for transform_name in transforms:
        result = apply_transform(transform_name, result)
    return result


@register_transform("truncate")
def truncate(value: str, max_length: int = 255) -> str:
    """Trunca string para tamanho máximo.
    
    Args:
        value: String a truncar
        max_length: Tamanho máximo (padrão: 255)
        
    Returns:
        String truncada
    """
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= max_length:
        return value
    return value[:max_length - 3] + "..."


@register_transform("slugify")
def slugify(value: str) -> str:
    """Converte string para formato slug (URL-friendly).
    
    Args:
        value: String a converter
        
    Returns:
        String em formato slug
    """
    if not isinstance(value, str):
        value = str(value)
    
    # Remove acentos
    value = strip_accents(value)
    # Converte para minúsculo
    value = value.lower()
    # Substitui espaços e underscores por hífen
    value = re.sub(r'[\s_]+', '-', value)
    # Remove caracteres não alfanuméricos (exceto hífen)
    value = re.sub(r'[^a-z0-9-]', '', value)
    # Remove hífens duplicados
    value = re.sub(r'-+', '-', value)
    # Remove hífens das extremidades
    return value.strip('-')


@register_transform("mask_pii")
def mask_pii(value: str) -> str:
    """Mascara informações pessoais (PII) no texto.
    
    Args:
        value: Texto com possível PII
        
    Returns:
        Texto com PII mascarado
    """
    if not isinstance(value, str):
        value = str(value)
    
    # Mascara CPF: 123.456.789-00 -> ***.***.789-00
    value = re.sub(
        r'(\d{3})\.(\d{3})\.(\d{3})-(\d{2})',
        r'***.***.\3-\4',
        value
    )
    
    # Mascara CNPJ: 12.345.678/0001-00 -> **.***.***/0001-00
    value = re.sub(
        r'(\d{2})\.(\d{3})\.(\d{3})/(\d{4})-(\d{2})',
        r'**.***.\3/\4-\5',
        value
    )
    
    # Mascara emails: user@domain.com -> u***@domain.com
    # Apenas para emails isolados (não parte de outras palavras)
    value = re.sub(
        r'\b([a-zA-Z])([a-zA-Z0-9._-]*)@([a-zA-Z0-9._-]+\.[a-zA-Z]{2,})',
        r'\1***@\3',
        value
    )
    
    return value


# Exporta funções principais
__all__ = [
    # Registry
    "TransformRegistry",
    "register_transform",
    "get_transform",
    "list_transforms",
    "apply_transform",
    "apply_transforms",
    # String transforms
    "strip_quotes",
    "normalize_whitespace",
    "uppercase",
    "lowercase",
    "strip_html",
    "unescape_html_entities",
    "strip_accents",
    "normalize_unicode",
    "trim",
    "collapse_newlines",
    "remove_extra_spaces",
    "remove_non_printable",
    # Number transforms
    "to_int",
    "to_float",
    "format_currency_br",
    # Date transforms
    "parse_date_br",
    "parse_datetime_iso",
    # Boolean transforms
    "to_bool",
    # Document transforms
    "extract_process_number",
    "extract_acordao_number",
    "normalize_cpf_cnpj",
    "extract_year_from_text",
    # Pipeline transforms
    "truncate",
    "slugify",
    "mask_pii",
]
