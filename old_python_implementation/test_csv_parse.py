#!/usr/bin/env python3
"""Test CSV parsing for tcu_normas"""

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_csv_parsing():
    """Test parsing the tcu_normas CSV"""
    import httpx
    import yaml
    from pathlib import Path
    from gabi.pipeline.parser import CSVParser
    from gabi.pipeline.contracts import FetchedContent

    # Load config
    sources_file = Path("sources.yaml")
    with open(sources_file) as f:
        data = yaml.safe_load(f)

    source_cfg = data['sources']['tcu_normas']
    parse_config = source_cfg['parse']
    fetch_config = source_cfg['fetch']['output']

    print(f"Parse config: {parse_config}")
    print(f"Fetch config: {fetch_config}")

    # Fetch the CSV
    print("\n1. Fetching CSV...")
    url = "https://sites.tcu.gov.br/dados-abertos/normas/arquivos/norma.csv"
    response = httpx.get(url, timeout=60.0)
    content_bytes = response.content
    print(f"Fetched {len(content_bytes)} bytes")

    # Create FetchedContent with metadata
    from gabi.pipeline.contracts import FetchMetadata
    metadata = FetchMetadata(
        url=url,
        method="GET",
        status_code=200,
        content_type="text/csv",
        content_length=len(content_bytes),
        encoding="utf-8",
        headers=dict(response.headers),
        fetch_duration_ms=1000
    )

    fetched = FetchedContent(
        url=url,
        content=content_bytes,
        metadata=metadata,
        size_bytes=len(content_bytes)
    )

    # Parse
    print("\n2. Parsing CSV...")
    parser = CSVParser()

    # Merge configs
    merged_config = {**fetch_config, **parse_config}
    print(f"Merged config: {merged_config}")

    # Check content
    text = content_bytes.decode('utf-8')
    lines = text.split('\n')
    print(f"Total lines in CSV: {len(lines)}")
    print(f"First line: {lines[0][:200]}")
    if len(lines) > 1:
        print(f"Second line: {lines[1][:200]}")

    result = await parser.parse(fetched, merged_config)

    print(f"Parse result errors: {result.errors}")

    print(f"\n3. Parse complete!")
    print(f"Documents: {len(result.documents)}")
    if result.documents:
        doc = result.documents[0]
        print(f"First doc ID: {doc.document_id}")
        print(f"First doc title: {doc.metadata.get('title', 'N/A')}")
        print(f"First doc text length: {len(doc.text or '')}")

    return result

if __name__ == "__main__":
    result = asyncio.run(test_csv_parsing())
    print(f"\n✅ SUCCESS: Parsed {len(result.documents)} documents")
