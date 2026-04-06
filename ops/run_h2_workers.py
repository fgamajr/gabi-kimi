from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multiple H2 workers in parallel")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--model", default=os.getenv("H2_LLM_MODEL", "qwen3"))
    parser.add_argument("--quality-report", required=True, help="Gate report from eval_h2_semantic_quality")
    parser.add_argument("--max-text-chars", type=int, default=12000)
    parser.add_argument("--max-spans", type=int, default=120)
    parser.add_argument("--max-rss-mb", type=float, default=2048)
    parser.add_argument("--poll-interval-sec", type=float, default=2.0)
    parser.add_argument("--max-idle-cycles", type=int, default=30)
    parser.add_argument("--h2-mode", choices=["fast", "deep"], default=os.getenv("H2_MODE", "fast"))
    parser.add_argument("--min-avg-score", type=float, default=0.75)
    parser.add_argument("--min-pass-rate", type=float, default=0.90)
    parser.add_argument("--max-span-error-rate", type=float, default=0.02)
    parser.add_argument("--max-low-coverage-rate", type=float, default=0.10)
    args = parser.parse_args()

    procs: list[subprocess.Popen[str]] = []
    for idx in range(args.workers):
        worker_id = f"h2w-{idx + 1}-{os.getpid()}"
        cmd = [
            sys.executable,
            "-m",
            "src.backend.parsing.pipeline",
            "h2-loop",
            "--worker-id",
            worker_id,
            "--model",
            args.model,
            "--quality-report",
            args.quality_report,
            "--max-text-chars",
            str(args.max_text_chars),
            "--max-spans",
            str(args.max_spans),
            "--max-rss-mb",
            str(args.max_rss_mb),
            "--poll-interval-sec",
            str(args.poll_interval_sec),
            "--max-idle-cycles",
            str(args.max_idle_cycles),
            "--h2-mode",
            args.h2_mode,
            "--min-avg-score",
            str(args.min_avg_score),
            "--min-pass-rate",
            str(args.min_pass_rate),
            "--max-span-error-rate",
            str(args.max_span_error_rate),
            "--max-low-coverage-rate",
            str(args.max_low_coverage_rate),
        ]
        procs.append(subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        time.sleep(0.2)

    exit_codes: list[int] = []
    outputs: list[dict[str, object]] = []
    for proc in procs:
        stdout, stderr = proc.communicate()
        exit_codes.append(proc.returncode)
        out = stdout.strip() if stdout else ""
        err = stderr.strip() if stderr else ""
        outputs.append({"returncode": proc.returncode, "stdout": out, "stderr": err})

    failed = any(code != 0 for code in exit_codes)
    print(json.dumps({"workers": args.workers, "failed": failed, "runs": outputs}, ensure_ascii=False))
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
