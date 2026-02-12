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
    "-c", "SELECT sr.name || ': ' || COALESCE((SELECT COUNT(*) FROM documents d WHERE d.source_id = sr.id AND d.is_deleted = false), 0) || ' docs' FROM source_registry sr WHERE sr.deleted_at IS NULL ORDER BY sr.name;"
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
            if not line:
                continue
            # Parse format: "source_name: X docs"
            if ': ' in line and ' docs' in line:
                parts = line.rsplit(' docs', 1)[0].split(': ')
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
        lines.append(f"  {source}: {counts[source]} docs")
    return '\n'.join(lines)

def check_stuck(history, current_counts):
    """Check if any source has been stuck at the same count for > 2 minutes."""
    stuck_sources = []
    for source, count in current_counts.items():
        # Look back 8 iterations (120 seconds / 15 seconds)
        lookback = 8
        if len(history) >= lookback:
            old_count = history[-lookback].get(source)
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
    print("=" * 60)
    print("GABI Ingestion Monitor")
    print("=" * 60)
    print(f"Monitoring {EXPECTED_SOURCES} sources every {INTERVAL} seconds")
    print(f"Target: {MIN_DOCS}+ docs per source")
    print(f"Stuck threshold: {STUCK_THRESHOLD} seconds (same count)")
    print(f"Max duration: {MAX_DURATION} seconds")
    print("=" * 60)
    
    history = []
    start_time = time.time()
    iteration = 0
    
    while True:
        iteration += 1
        elapsed = time.time() - start_time
        
        # Check if max duration reached
        if elapsed >= MAX_DURATION:
            print(f"\n[INFO] Maximum duration ({MAX_DURATION}s) reached. Exiting.")
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
        
        # Check if all sources are complete
        if check_all_complete(counts):
            print(f"\n[✓] SUCCESS: All {len(counts)} sources have reached {MIN_DOCS}+ docs!")
            print("Exiting monitor.")
            break
        
        # Check for stuck sources
        if len(history) >= 8:
            stuck = check_stuck(history, counts)
            if stuck:
                print(f"\n[!] WARNING: Potentially stuck sources (>2 min at same count):")
                for source, count in stuck:
                    print(f"    - {source}: stuck at {count} docs")
        
        # Calculate ETA
        if len(counts) > 0:
            total_docs = sum(counts.values())
            target_total = EXPECTED_SOURCES * MIN_DOCS
            remaining = target_total - total_docs
            
            if remaining > 0 and len(history) >= 2:
                # Calculate rate based on last few samples
                recent = history[-5:] if len(history) >= 5 else history
                if len(recent) >= 2:
                    prev_total = sum(recent[0].values())
                    curr_total = sum(recent[-1].values())
                    time_diff = (len(recent) - 1) * INTERVAL
                    if time_diff > 0:
                        rate = (curr_total - prev_total) / time_diff
                        if rate > 0:
                            eta_seconds = remaining / rate
                            print(f"  Total: {total_docs}/{target_total} docs | Rate: {rate:.1f} docs/sec | ETA: {int(eta_seconds/60)}m {int(eta_seconds%60)}s")
                        else:
                            print(f"  Total: {total_docs}/{target_total} docs | Rate: 0 docs/sec (no progress)")
            else:
                print(f"  Total: {total_docs}/{target_total} docs")
        
        # Wait for next iteration
        time.sleep(INTERVAL)
    
    print("\n" + "=" * 60)
    print("Monitoring complete")
    print("=" * 60)
    
    if history:
        final_counts = history[-1]
        print("\nFinal document counts:")
        print(format_counts(final_counts))

if __name__ == "__main__":
    main()
