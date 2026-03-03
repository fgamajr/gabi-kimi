# DOU Data Sources: Field Comparison

## Semantic Field Mapping

This table shows the semantic equivalent fields between leiturajornal and INLabs.

| Concept | Leiturajornal | INLabs | Match Type |
|---------|---------------|--------|------------|
| **Document Type** | `artType` | `art_type` | ✅ Exact (case diff) |
| **Title** | `title` | `identifica` | ⚠️ Semantic equivalent |
| **Page Number** | `numberPage` | `number_page` | ✅ Exact (case diff) |
| **Edition Number** | `editionNumber` | `edition_number` | ✅ Exact (case diff) |
| **Publication Date** | `pubDate` | `pub_date` | ✅ Exact (case diff) |
| **Publication Section** | `pubName` | `pub_name` | ✅ Exact (case diff) |
| **Subtitle** | `subTitulo` | `sub_titulo` | ✅ Exact (case diff) |
| **Content** | `content` | `texto` | ⚠️ Semantic equivalent |
| **Organization** | `hierarchyStr` | `art_category` | ⚠️ Similar purpose |
| **Organization (list)** | `hierarchyList` | - | ❌ LJ only |
| **Organization (depth)** | `hierarchyLevelSize` | - | ❌ LJ only |
| **URL Slug** | `urlTitle` | - | ❌ LJ only |
| **Publication Order** | `pubOrder` | - | ❌ LJ only |
| **Unique ID** | - | `id_materia` | ❌ IN only |
| **Office ID** | - | `id_oficio` | ❌ IN only |
| **XML ID** | - | `id` | ❌ IN only |
| **Internal Name** | - | `name` | ❌ IN only |
| **PDF Page** | - | `pdf_page` | ❌ IN only |
| **Hierarchy Code** | - | `art_class` | ❌ IN only |
| **Font Size** | - | `art_size` | ❌ IN only |
| **Extra Edition** | - | `art_notes` | ❌ IN only |
| **Date Field** | - | `data` | ❌ IN only |
| **Summary/Ementa** | - | `ementa` | ❌ IN only |
| **Title Field** | - | `titulo` | ❌ IN only |

## Key Differences Explained

### Naming Convention
- **Leiturajornal:** camelCase (`artType`, `pubDate`)
- **INLabs:** snake_case (`art_type`, `pub_date`)

### Content Fields
- **Leiturajornal `content`:** Plain text, already extracted
- **INLabs `texto`:** HTML content in CDATA section, needs parsing

### Organization Hierarchy
- **Leiturajornal:** 
  - `hierarchyStr` = Human-readable path string
  - `hierarchyList` = Array of organization levels
  - `hierarchyLevelSize` = Depth of hierarchy
- **INLabs:**
  - `art_category` = Human-readable path string
  - `art_class` = Machine-readable 12-level colon-separated code

### Title Fields
- **Leiturajornal `title`:** Full document title
- **INLabs `identifica`:** Display title (equivalent)
- **INLabs `titulo`:** Usually empty (reserved field)
- **INLabs `sub_titulo`:** Usually empty (reserved field)

### Unique Identification
- **Leiturajornal:** No official unique ID (use `urlTitle` as pseudo-key)
- **INLabs:** `id_materia` = Official 8-digit unique identifier

## Field Completeness

| Field Category | Leiturajornal | INLabs |
|----------------|---------------|--------|
| **Core Identity** (type, title, ID) | 2/3 | 3/3 |
| **Publication Info** (date, edition, page, section) | 4/4 | 5/5 |
| **Organization** (hierarchy) | 3/3 | 2/3 |
| **Content** (text, summary) | 1/2 | 2/2 |
| **Technical** (IDs, codes, URLs) | 1/5 | 5/5 |
| **Total Fields** | 14 | 20 |

## Recommendations by Use Case

### Document Identification
| Need | Best Source | Field(s) |
|------|-------------|----------|
| Official citation | INLabs | `id_materia` |
| URL generation | Leiturajornal | `urlTitle` |
| Cross-matching | Both | `art_type` + `number_page` |

### Content Extraction
| Need | Best Source | Reason |
|------|-------------|--------|
| Clean text | Leiturajornal | Pre-extracted |
| Preserved formatting | INLabs | Original HTML |
| Full-text search | Leiturajornal | No HTML tags |
| Print reproduction | INLabs | Original layout |

### Metadata Indexing
| Need | Best Source | Field(s) |
|------|-------------|----------|
| Organization tree | Leiturajornal | `hierarchyList` |
| Machine hierarchy | INLabs | `art_class` |
| Edition tracking | Both | `edition_number` |
| Extra edition flag | INLabs | `art_notes` |

---

*Generated: 2025-03-02*
