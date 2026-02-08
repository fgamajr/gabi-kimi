#!/usr/bin/env python3
"""
GABI Import Path Validator

Tests all imports in the project to identify:
- Imports that work
- Imports that fail (with error messages)
- Circular import issues
- Missing __init__.py files
- PYTHONPATH issues
"""

import sys
import os
import traceback
import importlib
from typing import List, Tuple, Dict

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# ANSI colors for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

# Results containers
working_imports: List[str] = []
failed_imports: List[Tuple[str, str]] = []
circular_imports: List[Tuple[str, str]] = []
missing_init_dirs: List[str] = []

# Test modules - organized by category
TEST_MODULES = {
    "config": [
        "gabi.config",
    ],
    "models": [
        "gabi.models",
        "gabi.models.base",
        "gabi.models.source",
        "gabi.models.document",
        "gabi.models.dlq",
        "gabi.models.execution",
        "gabi.models.audit",
        "gabi.models.chunk",
        "gabi.models.cache",
        "gabi.models.lineage",
        "gabi.models.document_simple",
    ],
    "api": [
        "gabi.api",
        "gabi.api.router",
        "gabi.api.sources",
        "gabi.api.search",
        "gabi.api.admin",
        "gabi.api.health",
        "gabi.api.documents",
        "gabi.api.dashboard",
    ],
    "core": [
        "gabi.core.source_registry",
    ],
    "services": [
        "gabi.services",
        "gabi.services.discovery",
        "gabi.services.search_service",
        "gabi.services.embedding_service",
        "gabi.services.indexing_service",
        "gabi.services.elasticsearch_setup",
    ],
    "pipeline": [
        "gabi.pipeline",
        "gabi.pipeline.fetcher",
        "gabi.pipeline.parser",
        "gabi.pipeline.chunker",
        "gabi.pipeline.embedder",
        "gabi.pipeline.indexer",
        "gabi.pipeline.discovery",
        "gabi.pipeline.deduplication",
        "gabi.pipeline.change_detection",
        "gabi.pipeline.fingerprint",
        "gabi.pipeline.transforms",
        "gabi.pipeline.contracts",
    ],
    "crawler": [
        "gabi.crawler",
        "gabi.crawler.base_agent",
        "gabi.crawler.navigator",
        "gabi.crawler.orchestrator",
        "gabi.crawler.metadata",
        "gabi.crawler.politeness",
    ],
    "auth": [
        "gabi.auth",
        "gabi.auth.jwt",
        "gabi.auth.middleware",
    ],
    "schemas": [
        "gabi.schemas",
        "gabi.schemas.sources",
        "gabi.schemas.documents",
        "gabi.schemas.search",
        "gabi.schemas.admin",
        "gabi.schemas.health",
    ],
    "tasks": [
        "gabi.tasks",
        "gabi.tasks.sync",
        "gabi.tasks.dlq",
        "gabi.tasks.alerts",
        "gabi.tasks.health",
    ],
    "governance": [
        "gabi.governance",
        "gabi.governance.audit",
        "gabi.governance.lineage",
        "gabi.governance.quality",
        "gabi.governance.catalog",
    ],
    "mcp": [
        "gabi.mcp",
        "gabi.mcp.server",
        "gabi.mcp.tools",
        "gabi.mcp.resources",
    ],
    "middleware": [
        "gabi.middleware",
        "gabi.middleware.rate_limit",
        "gabi.middleware.request_id",
        "gabi.middleware.security_headers",
    ],
    "main_modules": [
        "gabi.main",
        "gabi.worker",
        "gabi.db",
        "gabi.dependencies",
        "gabi.exceptions",
        "gabi.types",
        "gabi.logging_config",
        "gabi.metrics",
    ],
}

def is_circular_import_error(error_msg: str) -> bool:
    """Check if error is a circular import issue."""
    circular_patterns = [
        "cannot import name",
        "partially initialized module",
        "circular import",
        "ImportError",
    ]
    return any(pattern in error_msg for pattern in circular_patterns)

def test_import(module_path: str) -> Tuple[bool, str]:
    """Test importing a single module."""
    try:
        # Clear module from cache if exists to test fresh import
        if module_path in sys.modules:
            del sys.modules[module_path]
        
        module = importlib.import_module(module_path)
        return True, "OK"
    except ImportError as e:
        error_msg = str(e)
        tb = traceback.format_exc()
        return False, f"ImportError: {error_msg}\n{tb}"
    except Exception as e:
        error_msg = str(e)
        tb = traceback.format_exc()
        return False, f"{type(e).__name__}: {error_msg}\n{tb}"

def check_init_files():
    """Check for missing __init__.py files in package directories."""
    src_path = os.path.join(os.path.dirname(__file__), "src", "gabi")
    
    for root, dirs, files in os.walk(src_path):
        # Skip __pycache__ directories
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        
        if root == src_path:
            continue
            
        init_file = os.path.join(root, "__init__.py")
        if not os.path.exists(init_file):
            rel_path = os.path.relpath(root, os.path.dirname(__file__))
            missing_init_dirs.append(rel_path)

def print_header(title: str):
    """Print a formatted header."""
    print(f"\n{BLUE}{'='*70}{RESET}")
    print(f"{BLUE}{title.center(70)}{RESET}")
    print(f"{BLUE}{'='*70}{RESET}\n")

def print_section(title: str):
    """Print a section header."""
    print(f"\n{YELLOW}▶ {title}{RESET}")
    print(f"{YELLOW}{'-'*50}{RESET}")

def run_tests():
    """Run all import tests."""
    print_header("GABI IMPORT PATH VALIDATOR")
    print(f"Python: {sys.version}")
    print(f"Working directory: {os.getcwd()}")
    print(f"src in sys.path: {os.path.join(os.path.dirname(__file__), 'src') in sys.path}")
    
    # Check for missing __init__.py files
    print_section("Checking __init__.py Files")
    check_init_files()
    if missing_init_dirs:
        print(f"{RED}✗ Missing __init__.py in directories:{RESET}")
        for d in missing_init_dirs:
            print(f"  - {d}")
    else:
        print(f"{GREEN}✓ All package directories have __init__.py{RESET}")
    
    # Test all modules
    total_tests = 0
    for category, modules in TEST_MODULES.items():
        print_section(f"Testing {category.upper()}")
        for module_path in modules:
            total_tests += 1
            success, msg = test_import(module_path)
            
            if success:
                working_imports.append(module_path)
                print(f"{GREEN}✓{RESET} {module_path}")
            else:
                failed_imports.append((module_path, msg))
                if is_circular_import_error(msg):
                    circular_imports.append((module_path, msg))
                    print(f"{RED}✗{RESET} {module_path} {YELLOW}[CIRCULAR]{RESET}")
                else:
                    print(f"{RED}✗{RESET} {module_path}")
                    # Print error details for failures
                    lines = msg.strip().split('\n')
                    if len(lines) > 1:
                        print(f"   {RED}└─ {lines[0][:80]}{RESET}")
    
    # Summary
    print_header("SUMMARY")
    print(f"Total tests: {total_tests}")
    print(f"{GREEN}Working: {len(working_imports)}{RESET}")
    print(f"{RED}Failed: {len(failed_imports)}{RESET}")
    
    if circular_imports:
        print(f"{YELLOW}Circular imports detected: {len(circular_imports)}{RESET}")
    
    if working_imports:
        print_section("Working Imports")
        for imp in working_imports:
            print(f"  {GREEN}✓{RESET} {imp}")
    
    if failed_imports:
        print_section("Failed Imports")
        for imp, err in failed_imports:
            print(f"  {RED}✗{RESET} {imp}")
    
    if circular_imports:
        print_section("Circular Import Details")
        for imp, err in circular_imports:
            print(f"\n{YELLOW}{imp}:{RESET}")
            print(f"  {err[:500]}...")
    
    # PYTHONPATH check
    print_section("PYTHONPATH Analysis")
    print(f"Current sys.path (first 5 entries):")
    for i, p in enumerate(sys.path[:5]):
        marker = GREEN + "✓" + RESET if "src" in p else ""
        print(f"  {i}: {p} {marker}")
    
    # Recommendations
    print_header("RECOMMENDATIONS")
    if not failed_imports and not missing_init_dirs:
        print(f"{GREEN}✓ All imports are working correctly!{RESET}")
    else:
        if missing_init_dirs:
            print(f"{YELLOW}• Add __init__.py files to:{RESET}")
            for d in missing_init_dirs:
                print(f"  - {d}/__init__.py")
        if circular_imports:
            print(f"{YELLOW}• Fix circular imports by refactoring dependencies{RESET}")
        if failed_imports and not circular_imports:
            print(f"{YELLOW}• Check missing dependencies or incorrect import paths{RESET}")
    
    return len(failed_imports) == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
