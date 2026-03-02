"""Anchor chaining — deterministic append-only commitment chain.

After every sealed ingestion, a new sequential anchor is created:
  0000-bootstrap  (genesis)
  0001-*          (first ingestion after genesis)
  0002-*          (next ingestion)
  ...

Invariants:
  CHAIN-1  Sequence numbers are monotonically increasing with no gaps.
  CHAIN-2  Every anchor's log_high_water_mark >= previous anchor's.
  CHAIN-3  Every anchor embeds prev_commitment_root from the prior anchor.
  CHAIN-4  hostile_verify.py MUST pass before the anchor is written.
  CHAIN-5  Anchor write failure aborts the ingestion.
  CHAIN-6  No ingestion completes without producing an anchor.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ANCHORS_DIR = Path("proofs/anchors")
ANCHORS_LOG = ANCHORS_DIR / "anchors.log"
HOSTILE_VERIFY = Path("hostile_verify.py")


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


_ANCHOR_RE = re.compile(r"^(\d{4})-(envelope|bootstrap)\.json$")


def _next_seq(anchors_dir: Path) -> int:
    """Determine next sequence number from existing anchor files.

    Only matches NNNN-envelope.json and NNNN-bootstrap.json.
    Returns max(seq) + 1.
    """
    max_seq = -1
    for p in anchors_dir.glob("*.json"):
        m = _ANCHOR_RE.match(p.name)
        if m:
            seq = int(m.group(1))
            if seq > max_seq:
                max_seq = seq
    return max_seq + 1


def _read_prev_anchor(anchors_dir: Path, seq: int) -> dict[str, Any] | None:
    """Read the previous anchor's envelope. Returns None if seq == 0."""
    if seq == 0:
        return None
    prev_seq = seq - 1
    matches = sorted(
        p for p in anchors_dir.glob(f"{prev_seq:04d}-*.json")
        if _ANCHOR_RE.match(p.name)
    )
    if len(matches) == 1:
        return json.loads(matches[0].read_text(encoding="utf-8"))
    if len(matches) > 1:
        raise RuntimeError(
            f"CHAIN-1 violation: multiple anchors for seq {prev_seq:04d}: "
            + ", ".join(p.name for p in matches)
        )
    raise FileNotFoundError(
        f"CHAIN-1 violation: previous anchor {prev_seq:04d}-*.json not found "
        f"in {anchors_dir}"
    )


def _run_hostile_verify(records_path: Path, envelope_path: Path) -> None:
    """Run hostile_verify.py as a subprocess. Raises on failure."""
    result = subprocess.run(
        [sys.executable, str(HOSTILE_VERIFY), str(records_path), str(envelope_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        _log(f"hostile_verify FAILED:\n{result.stdout}\n{result.stderr}")
        raise RuntimeError(
            f"CHAIN-4 violation: hostile_verify.py returned {result.returncode}"
        )
    _log("hostile_verify PASSED")


def _fsync_dir(path: Path) -> None:
    """Fsync a directory to ensure rename durability."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes atomically via unique tmp+rename, then fsync file and dir."""
    import tempfile

    fd_tmp, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd_tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
        _fsync_dir(path.parent)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically via unique tmp+rename, then fsync file and dir."""
    import tempfile

    fd_tmp, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd_tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
        _fsync_dir(path.parent)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _append_anchors_log(
    anchors_dir: Path,
    seq: int,
    envelope: dict[str, Any],
) -> None:
    """Append a line to anchors.log with fsync for durability."""
    log_path = anchors_dir / "anchors.log"
    root = envelope["commitment_root"]
    record_count = envelope["record_count"]
    hwm = envelope["snapshot"]["log_high_water_mark"]
    # Use latest_publication_date from scope, or computed_at date
    pub_date = envelope.get("scope", {}).get("latest_publication_date", "")
    if not pub_date:
        pub_date = envelope["snapshot"]["computed_at_utc"][:10]

    line = f"{seq:04d}  {pub_date}  {root}  {record_count}  {hwm}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    _log(f"anchors.log: appended seq={seq:04d}")


def _cleanup_anchor_files(anchors_dir: Path, seq: int) -> None:
    """Remove anchor files for a given sequence."""
    for name in (f"{seq:04d}-envelope.json", f"{seq:04d}-records.txt"):
        (anchors_dir / name).unlink(missing_ok=True)


def chain_anchor(
    envelope: dict[str, Any],
    records_data: bytes,
    anchors_dir: Path | None = None,
) -> Path:
    """Create a chained anchor after sealed ingestion.

    This is the ONLY way to produce an anchor after genesis.
    Failure at any step MUST abort the calling ingestion.

    Uses an exclusive file lock to serialize concurrent ingestions,
    preventing TOCTOU races on sequence number assignment.

    Args:
        envelope: The CRSS-1 commitment envelope (already persisted to DB).
        records_data: Raw canonical record lines (bytes, newline-separated).
        anchors_dir: Override for proofs/anchors/ (testing).

    Returns:
        Path to the written envelope JSON.

    Raises:
        RuntimeError: On any chain invariant violation.
        FileNotFoundError: If previous anchor is missing.
        subprocess.TimeoutExpired: If hostile_verify times out.
    """
    envelope = dict(envelope)  # shallow copy to avoid mutating caller's dict

    if anchors_dir is None:
        anchors_dir = ANCHORS_DIR

    anchors_dir.mkdir(parents=True, exist_ok=True)

    # Exclusive lock serializes all anchor operations (TOCTOU protection).
    lock_path = anchors_dir / ".chain.lock"
    lock_fd = open(lock_path, "a+")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        # CHAIN-1: Determine next sequence
        seq = _next_seq(anchors_dir)
        _log(f"chain: next sequence = {seq:04d}")

        # CHAIN-2 + CHAIN-3: Validate and inject prev_commitment_root
        # prev_commitment_root is injected HERE under the lock (not by caller)
        # to eliminate TOCTOU between seal and chain steps.
        prev = _read_prev_anchor(anchors_dir, seq)
        if prev is not None:
            prev_hwm = prev["snapshot"]["log_high_water_mark"]
            curr_hwm = envelope["snapshot"]["log_high_water_mark"]
            if curr_hwm < prev_hwm:
                raise RuntimeError(
                    f"CHAIN-2 violation: current high_water={curr_hwm} < "
                    f"previous high_water={prev_hwm}"
                )
            envelope["prev_commitment_root"] = prev["commitment_root"]
        else:
            envelope["prev_commitment_root"] = None

        # Write files atomically (tmp + rename) for crash safety
        envelope_path = anchors_dir / f"{seq:04d}-envelope.json"
        records_path = anchors_dir / f"{seq:04d}-records.txt"

        _atomic_write_bytes(records_path, records_data)
        _atomic_write_text(
            envelope_path,
            json.dumps(envelope, ensure_ascii=False, indent=2),
        )

        # CHAIN-4: hostile verification MUST pass before anchor is accepted
        try:
            _run_hostile_verify(records_path, envelope_path)
        except Exception:
            _cleanup_anchor_files(anchors_dir, seq)
            raise

        # Append to anchors.log (after verification passes)
        # CHAIN-5: if this fails, roll back anchor files
        try:
            _append_anchors_log(anchors_dir, seq, envelope)
        except Exception:
            _cleanup_anchor_files(anchors_dir, seq)
            raise RuntimeError(
                "CHAIN-5 violation: failed to append anchors.log; anchor rolled back"
            )

        _log(
            f"ANCHOR CHAINED: seq={seq:04d} root={envelope['commitment_root'][:16]}... "
            f"hwm={envelope['snapshot']['log_high_water_mark']}"
        )
        return envelope_path

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
