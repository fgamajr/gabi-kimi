> Last verified: 2026-03-06

# INLabs DOU XML Format Technical Specification

Documento de referencia tecnica. Ele continua util para entender o formato XML observado pelos parsers em
[src/backend/ingest/xml_parser.py](../src/backend/ingest/xml_parser.py), mas nao substitui os runbooks operacionais.

## Document Version
- **Version**: 1.0
- **Date**: 2026-03-02
- **Analysis Based On**: 13 XML samples from INLabs DOU publications (DO1, DO1E, DO2, DO3)

---

## 1. Overview

### 1.1 Document Structure
INLabs provides Diário Oficial da União (DOU) publications as ZIP archives containing individual XML files. Each XML file represents a single article/act/publication.

### 1.2 File Naming Convention
```
{jornal_code}_{YYYYMMDD}_{idMateria}.xml
```

Examples:
- `515_20260227_23615168.xml` (DO1 - Seção 1)
- `529_20260227_23562729.xml` (DO2 - Seção 2)
- `530_20260227_22423649.xml` (DO3 - Seção 3)
- `600_20260227_23639224.xml` (DO1E - Seção 1 Extra)

### 1.3 Journal Codes
| Code | Section | Description |
|------|---------|-------------|
| 515  | DO1     | Seção 1 - Executivo |
| 529  | DO2     | Seção 2 - Legislativo/Judiciário |
| 530  | DO3     | Seção 3 - Complementar |
| 600  | DO1E    | Seção 1 Extra |
| 602  | DO1E    | Seção 1 Extra (variant) |

---

## 2. XML Schema

### 2.1 Root Structure
```xml
<?xml version="1.0" encoding="UTF-8"?>
<xml>
  <article ...>
    <body>
      <!-- Content elements -->
    </body>
    <Midias />
  </article>
</xml>
```

**Note**: Files start with UTF-8 BOM (`EF BB BF`) and may not have XML declaration.

### 2.2 Article Element
The `<article>` element is the main container with the following attributes:

#### 2.2.1 Required Attributes

| Attribute | Type | Description | Example |
|-----------|------|-------------|---------|
| `id` | String | Unique article ID | `"48049441"` |
| `name` | String | Internal name/filename | `"Acordaos - Processo Etico - nA 0"` |
| `idOficio` | String | Official process ID | `"11589967"` |
| `pubName` | String | Publication section code | `"DO1"`, `"DO1E"`, `"DO2"`, `"DO3"` |
| `artType` | String | Type of act/publication | `"Portaria"`, `"Resolução"` |
| `pubDate` | Date (DD/MM/YYYY) | Publication date | `"27/02/2026"` |
| `artClass` | String (12 levels) | Hierarchical classification | `"00071:00453:00000:..."` |
| `artCategory` | String | Full organizational path | `"Ministério/Secretaria/Órgão"` |
| `artSize` | Integer | Font size (pt) | `"12"`, `"24"` |
| `artNotes` | String | Publication notes | `"Extra"`, `"EXTRA"`, `""` |
| `numberPage` | Integer | Page number in PDF | `"160"` |
| `pdfPage` | URL | Direct link to PDF view | `http://pesquisa.in.gov.br/...` |
| `editionNumber` | String | Edition identifier | `"39"`, `"39-A"`, `"39-C"` |
| `highlightType` | String | Highlight classification | `""` (usually empty) |
| `highlightPriority` | String | Highlight priority | `""` (usually empty) |
| `highlight` | String | Highlight flag | `""` (usually empty) |
| `highlightimage` | String | Highlight image URL | `""` (usually empty) |
| `highlightimagename` | String | Highlight image name | `""` (usually empty) |
| `idMateria` | String (8 digits) | Material ID | `"23615168"` |

#### 2.2.2 Attribute Semantics

##### artClass Hierarchy
The `artClass` attribute uses a 12-level colon-separated hierarchy:
```
LEVEL1:LEVEL2:LEVEL3:LEVEL4:LEVEL5:LEVEL6:LEVEL7:LEVEL8:LEVEL9:LEVEL10:LEVEL11:LEVEL12
```

- `00000` indicates unused/empty levels
- Non-zero codes represent organizational hierarchy positions
- Real hierarchy depth varies from 2 to 7 levels in observed data

Example patterns:
- `00071:00453:00000:...` (Depth 2) - Professional regulatory entities
- `00006:00008:00009:00064:...` (Depth 3) - CAMEX/GECEX resolutions
- `00035:00056:00056:00006:...` (Depth 4) - Petrobras acts
- `00016:00011:00011:00116:00004:...` (Depth 5) - Military regions

##### idMateria
- Always 8 numeric digits
- Unique identifier for the material across all publications
- Used in filename: `{jornal_code}_{date}_{idMateria}.xml`

##### artNotes
Indicates special publication status:
- `""` (empty): Regular publication
- `"Extra"` or `"EXTRA"`: Extraordinary/special edition

---

## 3. Body Structure

### 3.1 Child Elements
The `<body>` element contains exactly these 6 child elements in order:

```xml
<body>
  <Identifica>...</Identifica>  <!-- Title/identifier -->
  <Data>...</Data>              <!-- Date (usually empty) -->
  <Ementa>...</Ementa>          <!-- Summary/abstract -->
  <Titulo>...</Titulo>          <!-- Title -->
  <SubTitulo>...</SubTitulo>    <!-- Subtitle -->
  <Texto>...</Texto>            <!-- Main content (HTML) -->
</body>
```

### 3.2 Element Details

| Element | Content Type | Required | Observations |
|---------|--------------|----------|--------------|
| `Identifica` | Text/CDATA | Yes | Usually contains title in uppercase |
| `Data` | Empty/Text | Yes | Almost always empty in observed samples |
| `Ementa` | Text/CDATA | Yes | Often empty; contains summary when present |
| `Titulo` | Text/CDATA | Yes | Usually empty; occasionally has content |
| `SubTitulo` | Empty | Yes | Always empty in observed samples |
| `Texto` | HTML/CDATA | Yes | Main content with HTML markup |

### 3.3 Body Structure Variations

Based on analysis, four distinct body structure patterns exist:

1. **Standard (No Ementa)** - 69% of samples
   ```
   Identifica(has_text) | Data(empty) | Ementa(empty) | Titulo(empty) | SubTitulo(empty) | Texto(has_text)
   ```
   Types: Portaria, Extrato de Contrato, Acórdão, Extrato de Termo Aditivo, Ato

2. **With Ementa** - 15% of samples
   ```
   Identifica(has_text) | Data(empty) | Ementa(has_text) | Titulo(empty) | SubTitulo(empty) | Texto(has_text)
   ```
   Types: Resolução

3. **With Ementa and Titulo** - 8% of samples
   ```
   Identifica(has_text) | Data(empty) | Ementa(has_text) | Titulo(has_text) | SubTitulo(empty) | Texto(has_text)
   ```
   Types: Portaria (rare)

4. **Empty Identifica** - 8% of samples
   ```
   Identifica(empty) | Data(empty) | Ementa(has_text) | Titulo(empty) | SubTitulo(empty) | Texto(has_text)
   ```
   Types: Resolução (rare)

---

## 4. HTML Content in Texto Element

### 4.1 HTML Structure
The `<Texto>` element contains HTML markup wrapped in CDATA:

```xml
<Texto><![CDATA[
  <p class="identifica">PORTARIA Nº 123, DE 27 DE FEVEREIRO DE 2026</p>
  <p class="ementa">Resumo da portaria...</p>
  <p>O MINISTRO DA ... resolve:</p>
  <p>Art. 1º ...</p>
  <p class="assina">Nome do Signatário</p>
  <p class="cargo">Cargo do Signatário</p>
]]></Texto>
```

### 4.2 HTML Elements Used

| Element | Frequency | Usage |
|---------|-----------|-------|
| `<p>` | 741 occurrences | Paragraphs, structure |
| `<td>` | 475 occurrences | Table cells |
| `<tr>` | 103 occurrences | Table rows |
| `<img>` | 18 occurrences | Embedded images |
| `<table>` | 5 occurrences | Data tables |

### 4.3 CSS Classes

| Class | Frequency | Purpose |
|-------|-----------|---------|
| `.identifica` | 12 | Title/header paragraph |
| `.assina` | 10 | Signature block |
| `.cargo` | 5 | Position/title of signatory |
| `.ementa` | 3 | Summary/abstract paragraph |
| `.titulo` | 1 | Section title |
| `.anexo` | 1 | Annex/attachment marker |

### 4.4 HTML Content Patterns

#### Pattern 1: Portaria/Act Standard
```html
<p class="identifica">PORTARIA Nº X, DE DD DE MÊS DE AAAA</p>
<p>O [AUTORIDADE] resolve:</p>
<p>Art. 1º ...</p>
<p class="assina">Nome</p>
<p class="cargo">Cargo</p>
```

#### Pattern 2: Resolução with Ementa
```html
<p class="identifica">RESOLUÇÃO Nº X, DE DD DE MÊS DE AAAA</p>
<p class="ementa">Ementa text...</p>
<p>O [ÓRGÃO] resolve:</p>
<p>Art. 1º ...</p>
<p class="assina">Nome</p>
<p class="cargo">Cargo</p>
```

#### Pattern 3: Acórdão (Professional Council Decisions)
```html
<p class="identifica">ACÓRDÃO</p>
<p>Processo Ético nº ...</p>
<p class="assina">Presidente</p>
<p class="cargo">Presidente do Conselho</p>
```

#### Pattern 4: Contract Extracts
```html
<p class="identifica">EXTRATO DE TERMO ADITIVO</p>
<table>...</table>
```

---

## 5. artType Values (Complete Taxonomy)

Based on comprehensive analysis, the following act types exist:

| artType | Translation | Typical Content |
|---------|-------------|-----------------|
| `Acórdão` | Decision/Ruling | Professional council disciplinary decisions |
| `Ato` | Act | Administrative acts, delegations |
| `Despacho` | Dispatch/Order | Regulatory agency decisions |
| `Extrato de Contrato` | Contract Extract | Contract summaries with tables |
| `Extrato de Termo Aditivo` | Addendum Extract | Contract amendment summaries |
| `Pauta` | Agenda | Meeting agendas |
| `Portaria` | Ordinance | Ministerial/departmental orders |
| `Resolução` | Resolution | Normative resolutions, GECEX/CAMEX |

### 5.1 Distribution in Sample
- Portaria: 38% (5/13)
- Resolução: 23% (3/13)
- Extrato de Termo Aditivo: 15% (2/13)
- Acórdão: 8% (1/13)
- Ato: 8% (1/13)
- Extrato de Contrato: 8% (1/13)

---

## 6. Encoding and Special Considerations

### 6.1 Character Encoding
- **Primary**: UTF-8 with BOM (`EF BB BF`)
- **BOM Handling**: Required for proper parsing
- **Alternative Encodings**: ISO-8859-1 compatible for legacy content

### 6.2 XML Parsing Requirements
1. Handle UTF-8 BOM prefix
2. Support CDATA sections (HTML content in Texto)
3. Case-sensitive element names
4. Handle empty attributes (`=""`)

### 6.3 Date Formats
- `pubDate`: DD/MM/YYYY (e.g., "27/02/2026")
- File dates in name: YYYYMMDD (e.g., "20260227")

### 6.4 URL Patterns
PDF links follow pattern:
```
http://pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?data=DD/MM/YYYY&jornal=NNN&pagina=PPP
```

---

## 7. XML Parsing Recommendations

### 7.1 Recommended Parsers (in order)

1. **ElementTree** (Python stdlib)
   - ✓ Fast and reliable
   - ✓ Built-in CDATA handling
   - ⚠ Handle BOM manually

2. **lxml**
   - ✓ Superior error recovery
   - ✓ Better namespace handling
   - ✓ Schema validation support
   - ⚠ External dependency

3. **BeautifulSoup** (for HTML in Texto)
   - ✓ Excellent HTML parsing
   - ✓ Handles malformed HTML gracefully
   - ⚠ External dependency

### 7.2 Parsing Best Practices

```python
import xml.etree.ElementTree as ET
from pathlib import Path

def parse_inlabs_xml(filepath: Path) -> dict:
    """Parse INLabs DOU XML file."""
    # Read with UTF-8-sig to handle BOM
    content = filepath.read_text(encoding='utf-8-sig')
    
    # Parse XML
    root = ET.fromstring(content)
    
    # Find article (handles both root structures)
    article = root.find('.//article')
    if article is None and root.tag == 'article':
        article = root
    
    # Extract attributes
    data = {
        'id': article.get('id'),
        'artType': article.get('artType'),
        'artCategory': article.get('artCategory'),
        'pubDate': article.get('pubDate'),
        'idMateria': article.get('idMateria'),
        # ... etc
    }
    
    # Extract body content
    body = article.find('body')
    if body is not None:
        texto = body.find('Texto')
        if texto is not None and texto.text:
            data['html_content'] = texto.text
    
    return data
```

### 7.3 Common Pitfalls

1. **BOM Handling**: Always use `utf-8-sig` encoding
2. **CDATA**: Texto content is HTML inside CDATA
3. **Empty Elements**: Many body elements may be empty
4. **Namespace**: No namespace used in observed files
5. **Case Sensitivity**: Element names are case-sensitive

---

## 8. Edge Cases and Validation

### 8.1 Observed Edge Cases

| Case | Frequency | Handling |
|------|-----------|----------|
| Empty Ementa | Common | Treat as optional |
| Empty Titulo | Common | Treat as optional |
| Empty Identifica | Rare (8%) | Use artType as fallback |
| artNotes="Extra" | Occasional | Flag special editions |
| Tables in Texto | Rare | Parse with HTML parser |
| Images in Texto | Rare | Handle `<img>` tags |

### 8.2 Validation Rules

```python
def validate_article(article_elem) -> list[str]:
    """Validate article element."""
    errors = []
    
    required_attrs = [
        'id', 'name', 'idOficio', 'pubName', 'artType',
        'pubDate', 'artClass', 'artCategory', 'idMateria'
    ]
    
    for attr in required_attrs:
        if not article_elem.get(attr):
            errors.append(f"Missing required attribute: {attr}")
    
    # Validate idMateria format
    id_materia = article_elem.get('idMateria', '')
    if not (len(id_materia) == 8 and id_materia.isdigit()):
        errors.append(f"Invalid idMateria format: {id_materia}")
    
    # Check body structure
    body = article_elem.find('body')
    if body is None:
        errors.append("Missing body element")
    else:
        required_children = ['Identifica', 'Data', 'Ementa', 'Titulo', 'SubTitulo', 'Texto']
        for child_name in required_children:
            if body.find(child_name) is None:
                errors.append(f"Missing body child: {child_name}")
    
    return errors
```

---

## 9. Complete Example

### 9.1 Sample XML (Resolução)
```xml
﻿<xml><article id="48044848" name="Resolucao 2454-2026" idOficio="11597099" 
      pubName="DO1E" artType="Resolução" pubDate="27/02/2026" 
      artClass="00006:00008:00009:00000:00000:00000:00000:00000:00000:00000:00064:00000" 
      artCategory="Presidência da República/Câmara de Comércio Exterior/Comitê-Executivo de Gestão" 
      artSize="12" artNotes="Extra" numberPage="5" 
      pdfPage="http://pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?data=27/02/2026&amp;jornal=600&amp;pagina=5" 
      editionNumber="39-A" highlightType="" highlightPriority="" highlight="" 
      highlightimage="" highlightimagename="" idMateria="23639224">
  <body>
    <Identifica><![CDATA[ RESOLUÇÃO GECEX Nº 5.476, DE 27 DE FEVEREIRO DE 2026]]></Identifica>
    <Data><![CDATA[]]></Data>
    <Ementa><![CDATA[ Dá outras providências.]]></Ementa>
    <Titulo><![CDATA[]]></Titulo>
    <SubTitulo><![CDATA[]]></SubTitulo>
    <Texto><![CDATA[<p class="identifica">RESOLUÇÃO GECEX Nº 5.476, DE 27 DE FEVEREIRO DE 2026</p><p class="ementa">Dá outras providências.</p><p>O COMITÊ-EXECUTIVO DE GESTÃO DA CÂMARA DE COMÉRCIO EXTERIOR - GECEX, no uso das atribuições que lhe confere o art. 14 do Decreto nº 11.892, de 19 de julho de 2024, tendo em vista o disposto nos arts. 7º e 8º da Lei nº 9.601, de 21 de janeiro de 1998, e considerando o que consta do Processo SEI nº 19970.100316/2026-11, resolve:</p><p>Art. 1º...</p>]]></Texto>
  </body>
  <Midias />
</article></xml>
```

### 9.2 Extracted Data Structure
```json
{
  "id": "48044848",
  "name": "Resolucao 2454-2026",
  "idOficio": "11597099",
  "pubName": "DO1E",
  "artType": "Resolução",
  "pubDate": "27/02/2026",
  "artClass": "00006:00008:00009:00000:00000:00000:00000:00000:00000:00000:00064:00000",
  "artCategory": "Presidência da República/Câmara de Comércio Exterior/Comitê-Executivo de Gestão",
  "artSize": "12",
  "artNotes": "Extra",
  "numberPage": "5",
  "pdfPage": "http://pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?data=27/02/2026&jornal=600&pagina=5",
  "editionNumber": "39-A",
  "highlightType": "",
  "highlightPriority": "",
  "highlight": "",
  "highlightimage": "",
  "highlightimagename": "",
  "idMateria": "23639224",
  "body": {
    "Identifica": "RESOLUÇÃO GECEX Nº 5.476, DE 27 DE FEVEREIRO DE 2026",
    "Data": "",
    "Ementa": "Dá outras providências.",
    "Titulo": "",
    "SubTitulo": "",
    "Texto": "<p class=\"identifica\">...</p>..."
  }
}
```

---

## 10. Appendix: artClass Hierarchy Codes

### 10.1 Level 1 Codes (Top Organization)

| Code | Organization Type |
|------|-------------------|
| 00006 | Presidência da República |
| 00016 | Ministério da Defesa |
| 00028 | Ministério da Fazenda |
| 00035 | Ministério de Minas e Energia |
| 00038 | Ministério da Pesca e Aquicultura |
| 00070 | Ministério do Desenvolvimento Agrário |
| 00071 | Entidades de Fiscalização das Profissões Liberais |

### 10.2 Complete artClass Examples

```
00006:00008:00009:00000:...00064:00000  - CAMEX/GECEX
00016:00011:00011:00116:00004:...       - Comando Militar do Norte
00028:00018:00053:...                   - CARF (Conselho Administrativo de Recursos Fiscais)
00035:00044:00019:00024:00052:...       - ANM (Agência Nacional de Mineração)
00035:00056:00056:00006:...             - Petrobras
00071:00453:00002:...                   - CRO-MG (Odontology Council)
```

---

## 11. References

1. INLabs Portal: https://inlabs.in.gov.br/
2. DOU Search: http://pesquisa.in.gov.br/
3. Lei nº 11.419/2006 - Digital publications law
4. Decreto nº 7.724/2012 - DOU regulation

---

## Document Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-02 | Initial comprehensive specification based on sample analysis |

---

*This document was generated through automated analysis of 13 XML samples from INLabs DOU publications dated February 27, 2026 and March 1, 2026.*
