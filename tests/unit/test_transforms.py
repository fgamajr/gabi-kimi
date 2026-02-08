"""Testes unitários para o módulo transforms.

Testa as funcionalidades de transformação de dados incluindo:
- String transforms
- Number transforms
- Date transforms
- Boolean transforms
- Document transforms
- Pipeline transforms
- Registry
"""

import pytest
from datetime import datetime
from typing import Any

from gabi.pipeline.transforms import (
    # Registry
    TransformRegistry,
    register_transform,
    get_transform,
    list_transforms,
    apply_transform,
    apply_transforms,
    # String transforms
    strip_quotes,
    normalize_whitespace,
    uppercase,
    lowercase,
    strip_html,
    unescape_html_entities,
    strip_accents,
    normalize_unicode,
    trim,
    collapse_newlines,
    remove_extra_spaces,
    remove_non_printable,
    # Number transforms
    to_int,
    to_float,
    format_currency_br,
    # Date transforms
    parse_date_br,
    parse_datetime_iso,
    # Boolean transforms
    to_bool,
    # Document transforms
    extract_process_number,
    extract_acordao_number,
    normalize_cpf_cnpj,
    extract_year_from_text,
    # Pipeline transforms
    truncate,
    slugify,
    mask_pii,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def clean_registry():
    """Cria um registro limpo para testes."""
    registry = TransformRegistry()
    return registry


# =============================================================================
# Testes do TransformRegistry
# =============================================================================

class TestTransformRegistry:
    """Testes do registro de transforms."""
    
    def test_registry_initialization(self, clean_registry):
        """Deve inicializar com registro vazio."""
        assert clean_registry.list_transforms() == []
    
    def test_register_transform(self, clean_registry):
        """Deve registrar uma transformação."""
        def dummy_transform(x):
            return x
        
        clean_registry.register("dummy", dummy_transform)
        
        assert "dummy" in clean_registry.list_transforms()
        assert clean_registry.get("dummy") is dummy_transform
    
    def test_has_transform(self, clean_registry):
        """Deve verificar se transformação existe."""
        def dummy(x):
            return x
        
        clean_registry.register("dummy", dummy)
        
        assert clean_registry.has_transform("dummy") is True
        assert clean_registry.has_transform("nonexistent") is False
    
    def test_get_nonexistent_transform(self, clean_registry):
        """Deve retornar None para transformação inexistente."""
        assert clean_registry.get("nonexistent") is None


# =============================================================================
# Testes de String Transforms
# =============================================================================

class TestStringTransforms:
    """Testes de transformações de string."""
    
    # strip_quotes
    def test_strip_quotes_double(self):
        """Deve remover aspas duplas."""
        assert strip_quotes('"hello"') == "hello"
    
    def test_strip_quotes_single(self):
        """Deve remover aspas simples."""
        assert strip_quotes("'hello'") == "hello"
    
    def test_strip_quotes_mixed(self):
        """Deve remover aspas mistas."""
        assert strip_quotes('"hello\'') == "hello"
    
    def test_strip_quotes_none(self):
        """Deve retornar string sem aspas."""
        assert strip_quotes("hello") == "hello"
    
    def test_strip_quotes_non_string(self):
        """Deve converter para string."""
        assert strip_quotes(123) == "123"
    
    # normalize_whitespace
    def test_normalize_whitespace_multiple(self):
        """Deve normalizar espaços múltiplos."""
        assert normalize_whitespace("hello   world") == "hello world"
    
    def test_normalize_whitespace_tabs(self):
        """Deve normalizar tabs."""
        assert normalize_whitespace("hello\t\tworld") == "hello world"
    
    def test_normalize_whitespace_newlines(self):
        """Deve normalizar quebras de linha."""
        assert normalize_whitespace("hello\n\nworld") == "hello world"
    
    def test_normalize_whitespace_mixed(self):
        """Deve normalizar espaços mistos."""
        assert normalize_whitespace("hello \t \n world") == "hello world"
    
    # uppercase
    def test_uppercase_basic(self):
        """Deve converter para maiúsculas."""
        assert uppercase("hello") == "HELLO"
    
    def test_uppercase_with_accents(self):
        """Deve converter com acentos."""
        assert uppercase("ação") == "AÇÃO"
    
    def test_uppercase_non_string(self):
        """Deve converter não-string."""
        assert uppercase(123) == "123"
    
    # lowercase
    def test_lowercase_basic(self):
        """Deve converter para minúsculas."""
        assert lowercase("HELLO") == "hello"
    
    def test_lowercase_with_accents(self):
        """Deve converter com acentos."""
        assert lowercase("AÇÃO") == "ação"
    
    # strip_html
    def test_strip_html_basic(self):
        """Deve remover tags HTML."""
        assert strip_html("<p>hello</p>") == "hello"
    
    def test_strip_html_nested(self):
        """Deve remover tags aninhadas."""
        assert strip_html("<div><p>hello</p></div>") == "hello"
    
    def test_strip_html_with_attributes(self):
        """Deve remover tags com atributos."""
        assert strip_html('<p class="test">hello</p>') == "hello"
    
    def test_strip_html_empty(self):
        """Deve lidar com HTML vazio."""
        assert strip_html("") == ""
    
    def test_strip_html_no_tags(self):
        """Deve retornar texto sem tags."""
        assert strip_html("hello") == "hello"
    
    # unescape_html_entities
    def test_unescape_html_basic(self):
        """Deve decodificar entidades HTML."""
        assert unescape_html_entities("&lt;p&gt;") == "<p>"
    
    def test_unescape_html_ampersand(self):
        """Deve decodificar &."""
        assert unescape_html_entities("&amp;") == "&"
    
    def test_unescape_html_quote(self):
        """Deve decodificar aspas."""
        assert unescape_html_entities("&quot;") == '"'
    
    # strip_accents
    def test_strip_accents_basic(self):
        """Deve remover acentos."""
        assert strip_accents("ação") == "acao"
    
    def test_strip_accents_multiple(self):
        """Deve remover múltiplos acentos."""
        assert strip_accents("é à ñ ü") == "e a n u"
    
    def test_strip_accents_no_accents(self):
        """Deve retornar string sem acentos."""
        assert strip_accents("hello") == "hello"
    
    # normalize_unicode
    def test_normalize_unicode_nfc(self):
        """Deve normalizar para NFC."""
        result = normalize_unicode("café", "NFC")
        assert isinstance(result, str)
    
    def test_normalize_unicode_nfd(self):
        """Deve normalizar para NFD."""
        result = normalize_unicode("café", "NFD")
        assert isinstance(result, str)
    
    # trim
    def test_trim_spaces(self):
        """Deve remover espaços das extremidades."""
        assert trim("  hello  ") == "hello"
    
    def test_trim_tabs(self):
        """Deve remover tabs das extremidades."""
        assert trim("\thello\t") == "hello"
    
    def test_trim_newlines(self):
        """Deve remover quebras de linha das extremidades."""
        assert trim("\nhello\n") == "hello"
    
    # collapse_newlines
    def test_collapse_newlines_multiple(self):
        """Deve colapsar quebras múltiplas."""
        assert collapse_newlines("line1\n\n\nline2") == "line1\nline2"
    
    def test_collapse_newlines_single(self):
        """Deve manter quebra única."""
        assert collapse_newlines("line1\nline2") == "line1\nline2"
    
    # remove_extra_spaces
    def test_remove_extra_spaces_middle(self):
        """Deve remover espaços extras no meio."""
        assert remove_extra_spaces("hello   world") == "hello world"
    
    # remove_non_printable
    def test_remove_non_printable_null(self):
        """Deve remover caracteres null."""
        assert remove_non_printable("hello\x00world") == "helloworld"
    
    def test_remove_non_printable_keep_newline(self):
        """Deve manter quebras de linha."""
        assert remove_non_printable("hello\nworld") == "hello\nworld"


# =============================================================================
# Testes de Number Transforms
# =============================================================================

class TestNumberTransforms:
    """Testes de transformações numéricas."""
    
    # to_int
    def test_to_int_from_int(self):
        """Deve manter inteiro."""
        assert to_int(42) == 42
    
    def test_to_int_from_float(self):
        """Deve converter float para int."""
        assert to_int(42.7) == 42
    
    def test_to_int_from_string(self):
        """Deve converter string para int."""
        assert to_int("42") == 42
    
    def test_to_int_from_string_with_thousands(self):
        """Deve converter string com separadores."""
        assert to_int("1,234") == 1234
        assert to_int("1.234") == 1234
    
    def test_to_int_from_string_br_format(self):
        """Deve converter formato brasileiro."""
        assert to_int("1.234,56") == 1234
    
    # to_float
    def test_to_float_from_float(self):
        """Deve manter float."""
        assert to_float(3.14) == 3.14
    
    def test_to_float_from_int(self):
        """Deve converter int para float."""
        assert to_float(42) == 42.0
    
    def test_to_float_from_string(self):
        """Deve converter string para float."""
        assert to_float("3.14") == 3.14
    
    def test_to_float_from_br_format(self):
        """Deve converter formato brasileiro."""
        assert to_float("1.234,56") == 1234.56
    
    def test_to_float_from_us_format(self):
        """Deve converter formato americano."""
        assert to_float("1,234.56") == 1234.56
    
    # format_currency_br
    def test_format_currency_br_basic(self):
        """Deve formatar moeda brasileira."""
        assert format_currency_br(1234.56) == "R$ 1.234,56"
    
    def test_format_currency_br_whole(self):
        """Deve formatar valor inteiro."""
        assert format_currency_br(1000) == "R$ 1.000,00"
    
    def test_format_currency_br_zero(self):
        """Deve formatar zero."""
        assert format_currency_br(0) == "R$ 0,00"
    
    def test_format_currency_br_invalid(self):
        """Deve lidar com valor inválido."""
        assert format_currency_br("invalid") == "invalid"


# =============================================================================
# Testes de Date Transforms
# =============================================================================

class TestDateTransforms:
    """Testes de transformações de data."""
    
    # parse_date_br
    def test_parse_date_br_slash(self):
        """Deve converter DD/MM/YYYY."""
        assert parse_date_br("15/01/2024") == "2024-01-15"
    
    def test_parse_date_br_dash(self):
        """Deve converter DD-MM-YYYY."""
        assert parse_date_br("15-01-2024") == "2024-01-15"
    
    def test_parse_date_br_dot(self):
        """Deve converter DD.MM.YYYY."""
        assert parse_date_br("15.01.2024") == "2024-01-15"
    
    def test_parse_date_br_invalid(self):
        """Deve retornar None para data inválida."""
        assert parse_date_br("invalid") is None
    
    def test_parse_date_br_empty(self):
        """Deve retornar None para string vazia."""
        assert parse_date_br("") is None
    
    # parse_datetime_iso
    def test_parse_datetime_iso_already_iso(self):
        """Deve manter formato ISO."""
        assert parse_datetime_iso("2024-01-15") == "2024-01-15"
    
    def test_parse_datetime_iso_invalid(self):
        """Deve retornar None para formato inválido."""
        assert parse_datetime_iso("invalid") is None


# =============================================================================
# Testes de Boolean Transforms
# =============================================================================

class TestBooleanTransforms:
    """Testes de transformações booleanas."""
    
    # to_bool
    def test_to_bool_true_values(self):
        """Deve converter valores verdadeiros."""
        assert to_bool(True) is True
        assert to_bool("true") is True
        assert to_bool("True") is True
        assert to_bool("1") is True
        assert to_bool("yes") is True
        assert to_bool("sim") is True
        assert to_bool("verdadeiro") is True
        assert to_bool("s") is True
        assert to_bool("y") is True
    
    def test_to_bool_false_values(self):
        """Deve converter valores falsos."""
        assert to_bool(False) is False
        assert to_bool("false") is False
        assert to_bool("False") is False
        assert to_bool("0") is False
        assert to_bool("no") is False
        assert to_bool("nao") is False
        assert to_bool("") is False
    
    def test_to_bool_non_zero(self):
        """Deve converter número não-zero."""
        assert to_bool(1) is True
        assert to_bool(42) is True
    
    def test_to_bool_zero(self):
        """Deve converter zero."""
        assert to_bool(0) is False


# =============================================================================
# Testes de Document Transforms
# =============================================================================

class TestDocumentTransforms:
    """Testes de transformações de documentos."""
    
    # extract_process_number
    def test_extract_process_number_full(self):
        """Deve extrair número completo."""
        assert extract_process_number("Processo 12345.678901/2024-00") == "12345.678901/2024-00"
    
    def test_extract_process_number_no_dots(self):
        """Deve extrair sem pontos."""
        assert extract_process_number("Processo 12345678901/2024-00") == "12345.678901/2024-00"
    
    def test_extract_process_number_not_found(self):
        """Deve retornar None se não encontrar."""
        assert extract_process_number("Sem processo aqui") is None
    
    # extract_acordao_number
    def test_extract_acordao_number_simple(self):
        """Deve extrair número simples."""
        assert extract_acordao_number("Acórdão 1234/2024") == "1234/2024"
    
    def test_extract_acordao_number_with_ac(self):
        """Deve extrair com prefixo AC."""
        assert extract_acordao_number("AC 1234/2024") == "1234/2024"
    
    def test_extract_acordao_number_lowercase(self):
        """Deve extrair em minúsculo."""
        assert extract_acordao_number("acórdão 1234/2024") == "1234/2024"
    
    def test_extract_acordao_number_not_found(self):
        """Deve retornar None se não encontrar."""
        assert extract_acordao_number("Sem acórdão") is None
    
    # normalize_cpf_cnpj
    def test_normalize_cpf(self):
        """Deve normalizar CPF."""
        assert normalize_cpf_cnpj("123.456.789-00") == "12345678900"
    
    def test_normalize_cnpj(self):
        """Deve normalizar CNPJ."""
        assert normalize_cpf_cnpj("12.345.678/0001-00") == "12345678000100"
    
    def test_normalize_cpf_cnpj_invalid_size(self):
        """Deve retornar None para tamanho inválido."""
        assert normalize_cpf_cnpj("123456") is None
    
    def test_normalize_cpf_cnpj_only_digits(self):
        """Deve manter se já sem formatação."""
        assert normalize_cpf_cnpj("12345678900") == "12345678900"
    
    # extract_year_from_text
    def test_extract_year_from_text_basic(self):
        """Deve extrair ano."""
        assert extract_year_from_text("Em 2024 ocorreu...") == 2024
    
    def test_extract_year_from_text_1900s(self):
        """Deve extrair ano 1900."""
        assert extract_year_from_text("Em 1999...") == 1999
    
    def test_extract_year_from_text_not_found(self):
        """Deve retornar None se não encontrar."""
        assert extract_year_from_text("Sem ano") is None
    
    def test_extract_year_from_text_invalid(self):
        """Não deve extrair ano inválido."""
        assert extract_year_from_text("Ano 1800") is None


# =============================================================================
# Testes de Pipeline Transforms
# =============================================================================

class TestPipelineTransforms:
    """Testes de transformações de pipeline."""
    
    # truncate
    def test_truncate_basic(self):
        """Deve truncar string longa."""
        long_string = "a" * 300
        result = truncate(long_string, 100)
        assert len(result) == 100
        assert result.endswith("...")
    
    def test_truncate_no_truncate(self):
        """Não deve truncar string curta."""
        short_string = "hello"
        assert truncate(short_string, 100) == "hello"
    
    def test_truncate_exact_length(self):
        """Não deve truncar string no limite."""
        exact = "a" * 100
        assert truncate(exact, 100) == "a" * 100
    
    def test_truncate_default_length(self):
        """Deve usar tamanho padrão."""
        long_string = "a" * 300
        result = truncate(long_string)
        assert len(result) <= 255
    
    # slugify
    def test_slugify_basic(self):
        """Deve criar slug básico."""
        assert slugify("Hello World") == "hello-world"
    
    def test_slugify_with_accents(self):
        """Deve remover acentos."""
        assert slugify("Ação") == "acao"
    
    def test_slugify_special_chars(self):
        """Deve remover caracteres especiais."""
        assert slugify("Hello @#$ World!") == "hello-world"
    
    def test_slugify_multiple_spaces(self):
        """Deve colapsar espaços."""
        assert slugify("Hello    World") == "hello-world"
    
    def test_slugify_underscores(self):
        """Deve converter underscores."""
        assert slugify("hello_world") == "hello-world"
    
    def test_slugify_empty(self):
        """Deve lidar com string vazia."""
        assert slugify("@#$%") == ""
    
    # mask_pii
    def test_mask_pii_cpf(self):
        """Deve mascarar CPF."""
        assert mask_pii("CPF: 123.456.789-00") == "CPF: ***.***.789-00"
    
    def test_mask_pii_cnpj(self):
        """Deve mascarar CNPJ."""
        assert mask_pii("CNPJ: 12.345.678/0001-00") == "CNPJ: **.***.678/0001-00"
    
    def test_mask_pii_email(self):
        """Deve mascarar email."""
        assert mask_pii("Email: user@domain.com") == "Email: u***@domain.com"
    
    def test_mask_pii_multiple(self):
        """Deve mascarar múltiplos."""
        text = "CPF 123.456.789-00 e email user@test.com"
        result = mask_pii(text)
        assert "***.***.789-00" in result
        assert "u***@test.com" in result


# =============================================================================
# Testes de Aplicação de Transforms
# =============================================================================

class TestApplyTransforms:
    """Testes de aplicação de transforms."""
    
    def test_apply_transform_strip_quotes(self):
        """Deve aplicar transform strip_quotes."""
        result = apply_transform("strip_quotes", '"hello"')
        assert result == "hello"
    
    def test_apply_transform_uppercase(self):
        """Deve aplicar transform uppercase."""
        result = apply_transform("uppercase", "hello")
        assert result == "HELLO"
    
    def test_apply_transform_not_found(self):
        """Deve lançar erro se transform não existe."""
        with pytest.raises(ValueError, match="not found"):
            apply_transform("nonexistent", "value")
    
    def test_apply_transforms_chain(self):
        """Deve aplicar múltiplas transforms em cadeia."""
        result = apply_transforms('"  hello WORLD  "', [
            "strip_quotes",
            "trim",
            "lowercase",
        ])
        assert result == "hello world"
    
    def test_apply_transforms_empty_list(self):
        """Deve retornar valor original com lista vazia."""
        result = apply_transforms("hello", [])
        assert result == "hello"
    
    def test_apply_transforms_multiple(self):
        """Deve aplicar transforms múltiplas."""
        result = apply_transforms("  HELLO  ", ["trim", "lowercase"])
        assert result == "hello"


# =============================================================================
# Testes de Idempotência
# =============================================================================

class TestIdempotency:
    """Testes de idempotência das transforms."""
    
    def test_strip_quotes_idempotent(self):
        """strip_quotes deve ser idempotente."""
        value = '"hello"'
        once = strip_quotes(value)
        twice = strip_quotes(once)
        assert once == twice == "hello"
    
    def test_uppercase_idempotent(self):
        """uppercase deve ser idempotente."""
        value = "hello"
        once = uppercase(value)
        twice = uppercase(once)
        assert once == twice == "HELLO"
    
    def test_lowercase_idempotent(self):
        """lowercase deve ser idempotente."""
        value = "HELLO"
        once = lowercase(value)
        twice = lowercase(once)
        assert once == twice == "hello"
    
    def test_trim_idempotent(self):
        """trim deve ser idempotente."""
        value = "  hello  "
        once = trim(value)
        twice = trim(once)
        assert once == twice == "hello"
    
    def test_normalize_whitespace_idempotent(self):
        """normalize_whitespace deve ser idempotente."""
        value = "hello   world"
        once = normalize_whitespace(value)
        twice = normalize_whitespace(once)
        assert once == twice == "hello world"
    
    def test_strip_html_idempotent(self):
        """strip_html deve ser idempotente."""
        value = "<p>hello</p>"
        once = strip_html(value)
        twice = strip_html(once)
        assert once == twice == "hello"
    
    def test_collapse_newlines_idempotent(self):
        """collapse_newlines deve ser idempotente."""
        value = "line1\n\n\nline2"
        once = collapse_newlines(value)
        twice = collapse_newlines(once)
        assert once == twice == "line1\nline2"
    
    def test_slugify_idempotent(self):
        """slugify deve ser idempotente."""
        value = "Hello World"
        once = slugify(value)
        twice = slugify(once)
        assert once == twice == "hello-world"


# =============================================================================
# Testes de Transformações Registradas
# =============================================================================

class TestRegisteredTransforms:
    """Testes das transforms registradas globalmente."""
    
    def test_list_transforms_not_empty(self):
        """Deve ter transforms registradas."""
        transforms = list_transforms()
        assert len(transforms) >= 10  # Mínimo 10 conforme especificação
    
    def test_string_transforms_registered(self):
        """Deve ter transforms de string."""
        assert get_transform("strip_quotes") is not None
        assert get_transform("uppercase") is not None
        assert get_transform("lowercase") is not None
        assert get_transform("strip_html") is not None
    
    def test_number_transforms_registered(self):
        """Deve ter transforms numéricas."""
        assert get_transform("to_int") is not None
        assert get_transform("to_float") is not None
    
    def test_date_transforms_registered(self):
        """Deve ter transforms de data."""
        assert get_transform("parse_date_br") is not None
    
    def test_document_transforms_registered(self):
        """Deve ter transforms de documento."""
        assert get_transform("extract_process_number") is not None
        assert get_transform("normalize_cpf_cnpj") is not None
