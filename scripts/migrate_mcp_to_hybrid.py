#!/usr/bin/env python3
"""
Migration Script: Legacy MCP → Hybrid Search MCP

This script helps migrate from the legacy MCP server to the new Hybrid Search MCP server.

What it does:
1. Checks current MCP configuration
2. Validates new hybrid MCP deployment
3. Updates environment variables if needed
4. Provides rollback instructions

Usage:
    python scripts/migrate_mcp_to_hybrid.py [--check-only|--migrate|--rollback]

Options:
    --check-only    Only check current state without making changes
    --migrate       Perform migration (default)
    --rollback      Rollback to legacy MCP
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

LEGACY_MCP_PORT = int(os.getenv("GABI_MCP_PORT", "8001"))
HYBRID_MCP_PORT = int(os.getenv("GABI_MCP_HYBRID_PORT", "8001"))

LEGACY_ENDPOINTS = {
    "health": f"http://localhost:{LEGACY_MCP_PORT}/health",
    "sse": f"http://localhost:{LEGACY_MCP_PORT}/mcp/sse",
    "tools": f"http://localhost:{LEGACY_MCP_PORT}/mcp/message",
}

HYBRID_ENDPOINTS = {
    "health": f"http://localhost:{HYBRID_MCP_PORT}/health",
    "sse": f"http://localhost:{HYBRID_MCP_PORT}/mcp/sse",
    "tools": f"http://localhost:{HYBRID_MCP_PORT}/mcp/message",
}

REQUIRED_ENV_VARS = [
    "GABI_DATABASE_URL",
    "GABI_ELASTICSEARCH_URL",
    "GABI_REDIS_URL",
    "GABI_EMBEDDINGS_URL",
]

OPTIONAL_ENV_VARS = [
    "GABI_JWT_ISSUER",
    "GABI_JWT_AUDIENCE",
    "GABI_JWT_JWKS_URL",
]


# =============================================================================
# Check Functions
# =============================================================================

async def check_endpoint(url: str, name: str) -> Tuple[bool, Dict]:
    """Check if an endpoint is healthy."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✓ {name} is healthy")
                return True, data
            else:
                logger.warning(f"✗ {name} returned {response.status_code}")
                return False, {}
    except Exception as e:
        logger.warning(f"✗ {name} is unreachable: {e}")
        return False, {}


async def check_legacy_mcp() -> Dict:
    """Check legacy MCP server status."""
    logger.info("\n=== Checking Legacy MCP Server ===")
    
    results = {
        "healthy": False,
        "version": None,
        "capabilities": {},
    }
    
    healthy, data = await check_endpoint(LEGACY_ENDPOINTS["health"], "Legacy MCP")
    
    if healthy:
        results["healthy"] = True
        results["version"] = data.get("version", "unknown")
        results["capabilities"] = data.get("capabilities", {})
        
        logger.info(f"  Version: {results['version']}")
        logger.info(f"  Capabilities: {results['capabilities']}")
    
    return results


async def check_hybrid_mcp() -> Dict:
    """Check hybrid MCP server status."""
    logger.info("\n=== Checking Hybrid MCP Server ===")
    
    results = {
        "healthy": False,
        "version": None,
        "capabilities": {},
    }
    
    healthy, data = await check_endpoint(HYBRID_ENDPOINTS["health"], "Hybrid MCP")
    
    if healthy:
        results["healthy"] = True
        results["version"] = data.get("version", "unknown")
        results["capabilities"] = data.get("capabilities", {})
        
        logger.info(f"  Version: {results['version']}")
        logger.info(f"  Capabilities: {results['capabilities']}")
    
    return results


def check_environment() -> Dict:
    """Check environment variables."""
    logger.info("\n=== Checking Environment Variables ===")
    
    results = {
        "required_present": [],
        "required_missing": [],
        "optional_present": [],
        "optional_missing": [],
    }
    
    for var in REQUIRED_ENV_VARS:
        if os.getenv(var):
            results["required_present"].append(var)
            logger.info(f"✓ {var} is set")
        else:
            results["required_missing"].append(var)
            logger.warning(f"✗ {var} is NOT set")
    
    for var in OPTIONAL_ENV_VARS:
        if os.getenv(var):
            results["optional_present"].append(var)
            logger.info(f"✓ {var} is set (optional)")
        else:
            results["optional_missing"].append(var)
            logger.info(f"○ {var} is NOT set (optional)")
    
    return results


def check_docker_compose() -> Dict:
    """Check docker-compose configuration."""
    logger.info("\n=== Checking Docker Compose Configuration ===")
    
    results = {
        "legacy_service_present": False,
        "hybrid_service_present": False,
        "has_mcp_hybrid_compose": False,
    }
    
    # Check if docker-compose.mcp-hybrid.yml exists
    if os.path.exists("docker/docker-compose.mcp-hybrid.yml"):
        results["has_mcp_hybrid_compose"] = True
        logger.info("✓ docker/docker-compose.mcp-hybrid.yml found")
    else:
        logger.warning("✗ docker/docker-compose.mcp-hybrid.yml NOT found")
    
    # Check main docker-compose.yml
    if os.path.exists("docker-compose.yml"):
        with open("docker-compose.yml", "r") as f:
            content = f.read()
            if "mcp:" in content or "mcp-hybrid:" in content:
                results["legacy_service_present"] = True
                logger.info("✓ MCP service found in docker-compose.yml")
    
    return results


# =============================================================================
# Migration Functions
# =============================================================================

def generate_env_updates() -> List[str]:
    """Generate environment variable updates needed for hybrid MCP."""
    updates = []
    
    # Check if hybrid-specific vars are set
    if not os.getenv("GABI_SEARCH_RRF_K"):
        updates.append("GABI_SEARCH_RRF_K=60")
    
    if not os.getenv("GABI_SEARCH_BM25_WEIGHT"):
        updates.append("GABI_SEARCH_BM25_WEIGHT=1.0")
    
    if not os.getenv("GABI_SEARCH_VECTOR_WEIGHT"):
        updates.append("GABI_SEARCH_VECTOR_WEIGHT=1.0")
    
    if not os.getenv("GABI_MCP_CORS_ORIGINS"):
        updates.append("GABI_MCP_CORS_ORIGINS=http://localhost:3000,https://chattcu.tcu.gov.br")
    
    return updates


def create_backup() -> str:
    """Create backup of current configuration."""
    backup_dir = ".backup/mcp-migration"
    os.makedirs(backup_dir, exist_ok=True)
    
    # Backup .env
    if os.path.exists(".env"):
        import shutil
        shutil.copy(".env", f"{backup_dir}/.env.backup")
        logger.info(f"✓ Backup created: {backup_dir}/.env.backup")
    
    return backup_dir


def update_docker_compose() -> bool:
    """Update docker-compose to use hybrid MCP."""
    logger.info("\n=== Updating Docker Compose ===")
    
    try:
        # Check if we need to update
        compose_override = "docker-compose.override.yml"
        
        override_content = """# MCP Hybrid Search Server Override
# This file adds the hybrid MCP server to the GABI stack

version: "3.8"

include:
  - docker/docker-compose.mcp-hybrid.yml
"""
        
        with open(compose_override, "w") as f:
            f.write(override_content)
        
        logger.info(f"✓ Created {compose_override}")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to update docker-compose: {e}")
        return False


def print_post_migration_instructions():
    """Print instructions after migration."""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    MIGRATION COMPLETED SUCCESSFULLY                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Next Steps:                                                                 ║
║                                                                              ║
║  1. Review the new environment variables in .env                             ║
║                                                                              ║
║  2. Start the hybrid MCP server:                                             ║
║     docker-compose up -d mcp-hybrid                                          ║
║                                                                              ║
║  3. Verify the server is running:                                            ║
║     curl http://localhost:8001/health                                        ║
║                                                                              ║
║  4. Update ChatTCU configuration to use new endpoints:                       ║
║     - Tools: search_exact, search_semantic, search_hybrid                    ║
║     - Resources: document://, chunk://, source://, search://                 ║
║                                                                              ║
║  5. Test the new search capabilities                                         ║
║                                                                              ║
║  Rollback (if needed):                                                       ║
║     python scripts/migrate_mcp_to_hybrid.py --rollback                       ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")


def print_rollback_instructions():
    """Print rollback instructions."""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                         ROLLBACK COMPLETED                                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  The system has been rolled back to the legacy MCP server.                   ║
║                                                                              ║
║  To restart with legacy MCP:                                                 ║
║     docker-compose up -d mcp                                                 ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")


# =============================================================================
# Main
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(
        description="Migrate from Legacy MCP to Hybrid Search MCP"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check current state without making changes"
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Perform migration (default)"
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback to legacy MCP"
    )
    
    args = parser.parse_args()
    
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║           GABI MCP Migration: Legacy → Hybrid Search                         ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
    
    if args.rollback:
        logger.info("Performing ROLLBACK to legacy MCP...")
        # Remove docker-compose.override.yml
        if os.path.exists("docker-compose.override.yml"):
            os.remove("docker-compose.override.yml")
            logger.info("✓ Removed docker-compose.override.yml")
        
        # Restore .env from backup
        backup_env = ".backup/mcp-migration/.env.backup"
        if os.path.exists(backup_env):
            import shutil
            shutil.copy(backup_env, ".env")
            logger.info("✓ Restored .env from backup")
        
        print_rollback_instructions()
        return
    
    # Check current state
    legacy_status = await check_legacy_mcp()
    hybrid_status = await check_hybrid_mcp()
    env_status = check_environment()
    compose_status = check_docker_compose()
    
    if args.check_only:
        logger.info("\n=== Check Only Mode - No changes made ===")
        
        print("\n📊 Summary:")
        print(f"  Legacy MCP: {'✓ Running' if legacy_status['healthy'] else '✗ Not running'}")
        print(f"  Hybrid MCP: {'✓ Running' if hybrid_status['healthy'] else '✗ Not running'}")
        print(f"  Env Vars: {len(env_status['required_present'])}/{len(REQUIRED_ENV_VARS)} required present")
        print(f"  Docker Compose: {'✓ Configured' if compose_status['has_mcp_hybrid_compose'] else '✗ Not configured'}")
        
        return
    
    # Migration
    if args.migrate or not args.check_only:
        logger.info("\n=== Starting Migration ===")
        
        # Check prerequisites
        if env_status["required_missing"]:
            logger.error(f"✗ Missing required environment variables: {env_status['required_missing']}")
            sys.exit(1)
        
        # Create backup
        backup_dir = create_backup()
        
        # Generate env updates
        env_updates = generate_env_updates()
        if env_updates:
            logger.info("\n=== Adding Environment Variables ===")
            with open(".env", "a") as f:
                f.write("\n# Hybrid MCP Settings (added by migration)\n")
                for update in env_updates:
                    f.write(f"{update}\n")
                    logger.info(f"✓ Added: {update}")
        
        # Update docker-compose
        if not update_docker_compose():
            logger.error("✗ Failed to update docker-compose")
            sys.exit(1)
        
        # Print instructions
        print_post_migration_instructions()


if __name__ == "__main__":
    asyncio.run(main())
