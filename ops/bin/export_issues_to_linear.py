#!/usr/bin/env python3
"""Export GitHub issues into Linear.

This script reads issues from a GitHub repository and creates matching issues in a
Linear team using the Linear GraphQL API.

Environment variables:
    GITHUB_TOKEN: Personal access token with repo issue read access
    LINEAR_API_KEY: Linear API key

Examples:
    python ops/bin/export_issues_to_linear.py \
      --repo owner/repo \
      --team-key ENG

    python ops/bin/export_issues_to_linear.py \
      --repo owner/repo \
      --team-key ENG \
      --state all \
      --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

GITHUB_API_BASE = "https://api.github.com"
LINEAR_API_URL = "https://api.linear.app/graphql"

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GitHubIssue:
    number: int
    title: str
    body: str
    state: str
    html_url: str
    created_at: str
    updated_at: str
    labels: list[str]
    assignee: str | None


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _linear_headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": api_key,
    }


def _github_issue_to_model(raw: dict[str, Any]) -> GitHubIssue:
    label_names = [label.get("name", "") for label in raw.get("labels", []) if label.get("name")]
    assignee = raw.get("assignee", {}) or {}
    return GitHubIssue(
        number=raw["number"],
        title=raw.get("title", "Untitled"),
        body=raw.get("body") or "",
        state=raw.get("state", "open"),
        html_url=raw.get("html_url", ""),
        created_at=raw.get("created_at", ""),
        updated_at=raw.get("updated_at", ""),
        labels=label_names,
        assignee=assignee.get("login"),
    )


def fetch_github_issues(
    client: httpx.Client,
    repo: str,
    github_token: str,
    state: str,
    since: str | None,
) -> list[GitHubIssue]:
    issues: list[GitHubIssue] = []
    page = 1

    while True:
        params: dict[str, Any] = {"state": state, "per_page": 100, "page": page, "sort": "created", "direction": "asc"}
        if since:
            params["since"] = since

        resp = client.get(
            f"{GITHUB_API_BASE}/repos/{repo}/issues",
            headers=_github_headers(github_token),
            params=params,
            timeout=30.0,
        )
        resp.raise_for_status()

        batch = resp.json()
        if not batch:
            break

        for item in batch:
            if "pull_request" in item:
                continue
            issues.append(_github_issue_to_model(item))

        page += 1

    return issues


def get_linear_team_id(client: httpx.Client, linear_api_key: str, team_key: str) -> str:
    query = """
    query TeamByKey($key: String!) {
      teams(filter: { key: { eq: $key } }) {
        nodes {
          id
          key
          name
        }
      }
    }
    """
    resp = client.post(
        LINEAR_API_URL,
        headers=_linear_headers(linear_api_key),
        json={"query": query, "variables": {"key": team_key}},
        timeout=30.0,
    )
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("errors"):
        raise RuntimeError(f"Linear API error while fetching team: {payload['errors']}")

    nodes = payload.get("data", {}).get("teams", {}).get("nodes", [])
    if not nodes:
        raise RuntimeError(f"No Linear team found with key '{team_key}'")

    return nodes[0]["id"]


def _build_linear_description(issue: GitHubIssue) -> str:
    metadata = [
        f"- GitHub Issue: [{issue.title}]({issue.html_url})",
        f"- Issue Number: #{issue.number}",
        f"- State on export: `{issue.state}`",
        f"- Created at: `{issue.created_at}`",
        f"- Updated at: `{issue.updated_at}`",
    ]
    if issue.assignee:
        metadata.append(f"- GitHub Assignee: `{issue.assignee}`")
    if issue.labels:
        metadata.append(f"- GitHub Labels: {', '.join(f'`{label}`' for label in issue.labels)}")

    body = issue.body.strip() or "_No body provided on GitHub issue._"
    return "\n".join([
        "## Imported from GitHub",
        *metadata,
        "",
        "## Original Description",
        body,
    ])


def create_linear_issue(
    client: httpx.Client,
    linear_api_key: str,
    team_id: str,
    github_issue: GitHubIssue,
) -> tuple[str, str]:
    mutation = """
    mutation IssueCreate($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue {
          id
          identifier
          url
        }
      }
    }
    """
    issue_title = f"[GH #{github_issue.number}] {github_issue.title}".strip()
    issue_description = _build_linear_description(github_issue)

    variables = {
        "input": {
            "teamId": team_id,
            "title": issue_title,
            "description": issue_description,
        }
    }

    resp = client.post(
        LINEAR_API_URL,
        headers=_linear_headers(linear_api_key),
        json={"query": mutation, "variables": variables},
        timeout=30.0,
    )
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("errors"):
        raise RuntimeError(f"Linear API error while creating issue #{github_issue.number}: {payload['errors']}")

    data = payload.get("data", {}).get("issueCreate", {})
    if not data.get("success"):
        raise RuntimeError(f"Linear rejected issue create for GitHub issue #{github_issue.number}")

    issue_data = data.get("issue", {})
    return issue_data.get("identifier", ""), issue_data.get("url", "")


def _validate_iso8601(value: str) -> str:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO-8601 timestamp: {value}") from exc
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export GitHub issues to Linear")
    parser.add_argument("--repo", required=True, help="GitHub repository in owner/name format")
    parser.add_argument("--team-key", required=True, help="Linear team key (e.g., ENG)")
    parser.add_argument(
        "--state",
        default="open",
        choices=["open", "closed", "all"],
        help="GitHub issue state filter",
    )
    parser.add_argument(
        "--since",
        type=_validate_iso8601,
        help="Only include issues updated at or after this ISO-8601 timestamp",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of issues to export (0 means no limit)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and display issues without creating anything in Linear",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    args = parse_args()

    github_token = os.getenv("GITHUB_TOKEN")
    linear_api_key = os.getenv("LINEAR_API_KEY")

    if not github_token:
        raise SystemExit("Missing required environment variable: GITHUB_TOKEN")
    if not linear_api_key:
        raise SystemExit("Missing required environment variable: LINEAR_API_KEY")

    with httpx.Client() as client:
        team_id = get_linear_team_id(client, linear_api_key, args.team_key)
        logger.info("Resolved Linear team '%s' to id '%s'", args.team_key, team_id)

        issues = fetch_github_issues(client, args.repo, github_token, args.state, args.since)
        if args.limit > 0:
            issues = issues[: args.limit]

        logger.info("Loaded %d GitHub issues from %s", len(issues), args.repo)

        if args.dry_run:
            for issue in issues:
                logger.info("[DRY-RUN] #%d %s", issue.number, issue.title)
            logger.info("Dry-run complete. No issues were created in Linear.")
            return 0

        created = 0
        for issue in issues:
            identifier, url = create_linear_issue(client, linear_api_key, team_id, issue)
            logger.info("Created Linear issue %s for GH #%d (%s)", identifier, issue.number, url)
            created += 1

        logger.info("Export complete. Created %d Linear issues.", created)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
