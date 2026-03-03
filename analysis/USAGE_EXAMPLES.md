# Leiturajornal Parser - Usage Examples

## Basic Usage

### Parse Local HTML File

```python
from leiturajornal_parser import parse_file

# Parse a downloaded HTML file
data = parse_file("2025-02-28_do1.html")

print(f"Date: {data.date_url}")
print(f"Section: {data.section}")
print(f"Articles: {data.article_count}")

# Iterate over articles
for article in data.articles:
    print(f"{article.art_type}: {article.title}")
```

### Fetch and Parse from URL

```python
from leiturajornal_parser import fetch_and_parse, Section

# Fetch today's DO1 section
data = fetch_and_parse("28-02-2025", Section.DO1)

# Or use string
# data = fetch_and_parse("28-02-2025", "do1")

print(f"Found {len(data.articles)} articles")
```

## Working with Articles

### Article Properties

```python
article = data.articles[0]

# Basic fields
print(article.title)              # Full title
print(article.art_type)           # Article type (e.g., "Portaria")
print(article.pub_date)           # Publication date (DD/MM/YYYY)
print(article.pub_date_iso)       # ISO format (YYYY-MM-DD)

# URLs
print(article.detail_url)         # Full article URL
print(article.url_title)          # URL slug

# Content
print(article.content)            # Excerpt (~400 chars)
print(article.is_truncated)       # True if content is truncated

# Hierarchy
print(article.hierarchy_str)      # Full path as string
print(article.hierarchy_list)     # Path as list
print(article.hierarchy_level_size)  # Number of levels

# Publication info
print(article.number_page)        # Page number
print(article.edition_number)     # Edition number
print(article.pub_order)          # Sorting key
```

## Filtering and Grouping

### By Article Type

```python
# Get all Portarias
portarias = data.get_by_art_type("Portaria")

# Case insensitive
portarias = data.get_by_art_type("portaria", case_sensitive=False)

# Get all unique types
types = data.get_art_types()
for art_type in sorted(types):
    count = len(data.get_by_art_type(art_type))
    print(f"{art_type}: {count}")
```

### By Hierarchy

```python
# Find articles from specific ministry
min_agro = data.get_by_hierarchy("Ministério da Agricultura")

# More specific
sec_edu = data.get_by_hierarchy(
    "Ministério da Educação/Secretaria de Regulação"
)
```

### By Publication Name (Extra Editions)

```python
# For extra editions, filter by sub-edition
data = fetch_and_parse("28-02-2025", "do1e")

# Articles come from multiple sub-editions
for pub_name in data.get_pub_names():
    articles = data.get_by_pub_name(pub_name)
    print(f"{pub_name}: {len(articles)} articles")
```

## Working with Extra Editions

```python
data = fetch_and_parse("28-02-2025", "do1e")

# Check if extra edition
print(data.is_extra_edition)  # True

# All sections included
print(data.section)
# "DO1E,DO1_EXTRA_E,DO1_EXTRA_F,DO1_EXTRA_G,DO1_EXTRA_H,..."

print(data.sections)
# ('DO1E', 'DO1_EXTRA_E', 'DO1_EXTRA_F', ...)

# Articles have specific pubName
for article in data.articles:
    print(f"{article.pub_name}: {article.title}")
```

## Special Edition Flags

```python
# Check available special editions
print(data.type_norm_day.do1e)   # DO1 Extra available?
print(data.type_norm_day.do2e)   # DO2 Extra available?
print(data.type_norm_day.do3e)   # DO3 Extra available?
print(data.type_norm_day.do1a)   # DO1 Admin available?
print(data.type_norm_day.do1esp) # DO1 Special available?
```

## CLI Usage

### Summary Output

```bash
python leiturajornal_parser.py page.html --format summary
```

### JSON Output

```bash
python leiturajornal_parser.py page.html --format json > articles.json
```

### CSV Output

```bash
python leiturajornal_parser.py page.html --format csv > articles.csv
```

### Filter by Type

```bash
python leiturajornal_parser.py page.html --format csv --filter-type "Portaria"
```

### Fetch from URL (CLI)

```bash
python leiturajornal_parser.py fetch --date 28-02-2025 --section do1 --format summary
```

## Error Handling

```python
from leiturajornal_parser import parse_file, ParseError, ValidationError

try:
    data = parse_file("page.html")
except ParseError as e:
    print(f"Parse failed: {e}")
except ValidationError as e:
    print(f"Invalid data: {e}")

# Check for empty results
if data.is_empty:
    print("No articles for this date/section")
```

## Batch Processing

```python
from leiturajornal_parser import fetch_and_parse
import json

results = []

for section in ["do1", "do2", "do3"]:
    try:
        data = fetch_and_parse("28-02-2025", section)
        results.append({
            "section": section,
            "count": data.article_count,
            "types": list(data.get_art_types())
        })
    except Exception as e:
        print(f"Failed to fetch {section}: {e}")

# Save summary
with open("summary.json", "w") as f:
    json.dump(results, f, indent=2)
```

## Advanced: Raw JSON Access

```python
# Access original parsed JSON
data.raw_json

# Access specific fields not in dataclass
custom_field = data.raw_json.get("customField", "")
```
