#!/usr/bin/env python3
"""Self-analyze a trace using Nemotron intelligence.

Fetches a trace from the vizpath server and runs self-analysis
via the intelligence endpoint, which uses Nemotron to evaluate
the agent's effectiveness, reasoning quality, and tool usage.

Usage:
    export NVIDIA_API_KEY="nvapi-..."

    # Analyze the most recent trace
    python examples/self_analyze.py

    # Analyze a specific trace by ID
    python examples/self_analyze.py --trace-id <uuid>

    # Custom server URL
    python examples/self_analyze.py --server-url http://localhost:8000
"""

import argparse
import json
import sys

import httpx


def get_latest_trace(base_url: str) -> dict | None:
    """Fetch the most recent trace from the server."""
    response = httpx.get(f"{base_url}/api/v1/traces", params={"limit": 1})
    response.raise_for_status()
    data = response.json()
    traces = data.get("traces", [])
    return traces[0] if traces else None


def analyze_trace(base_url: str, trace_id: str) -> dict:
    """Run basic analysis on a trace."""
    response = httpx.post(
        f"{base_url}/api/v1/intelligence/analyze",
        json={"trace_id": trace_id},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()


def self_analyze_trace(base_url: str, trace_id: str) -> dict:
    """Run deep self-analysis on a trace."""
    response = httpx.post(
        f"{base_url}/api/v1/intelligence/self-analyze",
        json={"trace_id": trace_id},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()


def print_analysis(result: dict) -> None:
    """Pretty-print analysis results."""
    analysis = result.get("analysis", {})

    print(f"\n  Quality Score: {analysis.get('quality_score', '-')}/5")

    labels = analysis.get("labels", [])
    if labels:
        print(f"  Labels: {', '.join(labels)}")

    summary = analysis.get("summary", "")
    if summary:
        print(f"  Summary: {summary}")

    suggestions = analysis.get("suggestions", [])
    if suggestions:
        print("  Suggestions:")
        for s in suggestions:
            print(f"    - {s}")

    if result.get("cached"):
        print("  (cached result)")


def print_self_analysis(result: dict) -> None:
    """Pretty-print self-analysis results."""
    analysis = result.get("analysis", {})

    print(f"\n  Overall Score:     {analysis.get('overall_score', '-')}/5")
    print(f"  Effectiveness:     {analysis.get('effectiveness', '-')}/5")
    print(f"  Reasoning Quality: {analysis.get('reasoning_quality', '-')}/5")
    print(f"  Tool Usage:        {analysis.get('tool_usage', '-')}/5")

    summary = analysis.get("summary", "")
    if summary:
        print(f"\n  Summary: {summary}")

    strengths = analysis.get("strengths", [])
    if strengths:
        print("\n  Strengths:")
        for s in strengths:
            print(f"    + {s}")

    weaknesses = analysis.get("weaknesses", [])
    if weaknesses:
        print("\n  Weaknesses:")
        for w in weaknesses:
            print(f"    - {w}")

    improvements = analysis.get("improvements", [])
    if improvements:
        print("\n  Improvements:")
        for i in improvements:
            print(f"    > {i}")

    if result.get("cached"):
        print("\n  (cached result)")


def main():
    parser = argparse.ArgumentParser(
        description="Self-analyze a trace using Nemotron intelligence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--trace-id",
        help="Trace ID to analyze (defaults to most recent trace)",
    )
    parser.add_argument(
        "--server-url",
        default="http://localhost:8000",
        help="Vizpath server URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted text",
    )
    args = parser.parse_args()

    base_url = args.server_url.rstrip("/")

    # Get trace ID
    trace_id = args.trace_id
    if not trace_id:
        print("Fetching most recent trace...")
        trace = get_latest_trace(base_url)
        if not trace:
            print("No traces found. Run an agent first to generate traces.")
            sys.exit(1)
        trace_id = trace["id"]
        print(f"Using trace: {trace['name']} ({trace_id})")

    # Run analysis
    print(f"\nRunning analysis on trace {trace_id}...")
    try:
        analysis = analyze_trace(base_url, trace_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 503:
            print("Error: NVIDIA API key not configured on the server.")
            print("Set NVIDIA_API_KEY environment variable and restart the server.")
            sys.exit(1)
        elif e.response.status_code == 404:
            print(f"Error: Trace {trace_id} not found.")
            sys.exit(1)
        raise

    if args.json:
        print(json.dumps(analysis, indent=2))
    else:
        print("\n--- Analysis ---")
        print_analysis(analysis)

    # Run self-analysis
    print(f"\nRunning deep self-analysis...")
    try:
        self_analysis = self_analyze_trace(base_url, trace_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 503:
            print("Error: NVIDIA API key not configured on the server.")
            sys.exit(1)
        raise

    if args.json:
        print(json.dumps(self_analysis, indent=2))
    else:
        print("\n--- Deep Self-Analysis ---")
        print_self_analysis(self_analysis)

    print("\nDone.")


if __name__ == "__main__":
    main()
