#!/usr/bin/env python3
"""Monitor GABI ingestion process and track document counts per source."""

import subprocess
import time
from datetime import datetime
from collections import defaultdict

# Configuration
COMMAND = [
    "docker", "exec", "gabi-postgres", "psql",
    "-U", "gabi", "-d", "gabi", "-t",
    "-c", "SELECT sr.id, COALESCE((SELECT COUNT(*) FROM documents d WHERE d.source_id = sr.id AND d.is_deleted = false), 0) FROM source_registry sr WHERE sr.deleted_at IS NULL ORDER BY sr.id;"
]
INTERVAL = 15  # seconds
MAX_DURATION = 600  # 10 minutes
STUCK_THRESHOLD = 120  # 2 minutes in seconds
MIN_DOCS = 500
EXPECTED_SOURCES = 11

def get_doc_counts():
    """Run the command and return parsed document counts."""
    try:
        result = subprocess.run(
            COMMAND,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            return None
        
        counts = {}
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if not line or '|' not in line:
                continue
            parts = line.split('|')
            if len(parts) == 2:
                source_name = parts[0].strip()
                try:
                    count = int(parts[1].strip())
                    counts[source_name] = count
                except ValueError:
                    continue
        return counts
    except Exception as e:
        print(f"Error running command: {e}")
        return None

def format_counts(counts):
    """Format counts for display."""
    if not counts:
        return "No data available"
    lines = []
    for source in sorted(counts.keys()):
        status = " ✓" if counts[source] >= MIN_DOCS else ""
        lines.append(f"  {source}: {counts[source]} docs{status}")
    return '\n'.join(lines)

def check_stuck(history, current_counts, current_time):
    """Check if any source has been stuck at the same count for > 2 minutes."""
    stuck_sources = []
    lookback_iterations = STUCK_THRESHOLD // INTERVAL  # 8 iterations = 120s
    
    if len(history) < lookback_iterations:
        return stuck_sources
    
    old_record = history[-lookback_iterations]
    for source, count in current_counts.items():
        old_count = old_record.get(source)
        if old_count is not None and old_count == count:
            stuck_sources.append((source, count))
    
    return stuck_sources

def check_all_complete(counts):
    """Check if all sources have reached MIN_DOCS."""
    if not counts:
        return False
    if len(counts) < EXPECTED_SOURCES:
        return False
    return all(count >= MIN_DOCS for count in counts.values())

def main():
    print("=" * 70)
    print("GABI Ingestion Monitor")
    print("=" * 70)
    print(f"Monitoring {EXPECTED_SOURCES} sources every {INTERVAL} seconds")
    print(f"Target: {MIN_DOCS}+ docs per source")
    print(f"Stuck threshold: {STUCK_THRESHOLD} seconds (same count)")
    print(f"Max duration: {MAX_DURATION} seconds (10 minutes)")
    print("=" * 70)
    
    history = []
    start_time = time.time()
    iteration = 0
    reported_stuck = set()
    
    while True:
        iteration += 1
        elapsed = time.time() - start_time
        
        # Check if max duration reached
        if elapsed >= MAX_DURATION:
            print(f"\n[INFO] Maximum duration ({MAX_DURATION}s / 10 min) reached. Exiting.")
            break
        
        # Get current counts
        counts = get_doc_counts()
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if counts is None:
            print(f"\n[{timestamp}] Failed to retrieve document counts")
            time.sleep(INTERVAL)
            continue
        
        history.append(counts)
        
        # Display results
        print(f"\n[{timestamp}] Iteration {iteration} (elapsed: {int(elapsed)}s)")
        print(format_counts(counts))
        
        # Calculate totals
        total_docs = sum(counts.values())
        complete_count = sum(1 for c in counts.values() if c >= MIN_DOCS)
        print(f"  Total: {total_docs} docs | {complete_count}/{len(counts)} sources >= {MIN_DOCS}")
        
        # Check if all sources are complete
        if check_all_complete(counts):
            print(f"\n[✓] SUCCESS: All {len(counts)} sources have reached {MIN_DOCS}+ docs!")
            print("Exiting monitor.")
            break
        
        # Check for stuck sources
        if len(history) >= 8:
            stuck = check_stuck(history, counts, time.time())
            new_stuck = [s for s in stuck if s[0] not in reported_stuck]
            if new_stuck:
                print(f"\n[!] WARNING: Potentially stuck sources (>2 min at same count):")
                for source, count in new_stuck:
                    print(f"    - {source}: stuck at {count} docs")
                    reported_stuck.add(source)
        
        # Wait for next iteration
        time.sleep(INTERVAL)
    
    print("\n" + "=" * 70)
    print("Monitoring complete")
    print("=" * 70)
    
    if history:
        final_counts = history[-1]
        print("\nFinal document counts:")
        print(format_counts(final_counts))
        
        total_docs = sum(final_counts.values())
        complete_count = sum(1 for c in final_counts.values() if c >= MIN_DOCS)
        print(f"\nSummary: {complete_count}/{len(final_counts)} sources reached {MIN_DOCS}+ docs")
        print(f"Total documents: {total_docs}")

if __name__ == "__main__":
    main()
