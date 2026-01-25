#!/usr/bin/env python3
"""Run the research agent example.

Usage:
    # Set your API key
    export NVIDIA_API_KEY="your-api-key"

    # Configure vizpath to send traces to the server
    export VIZPATH_API_URL="http://localhost:8000"
    export VIZPATH_PROJECT_ID="your-project-id"  # Optional

    # Run the agent
    python -m examples.research_agent.run "Your research topic"

    # Or with a custom topic
    python -m examples.research_agent.run "How do transformers work in machine learning?"
"""

import argparse
import os
import sys

from vizpath import configure

from .agent import ResearchAgent


def main():
    parser = argparse.ArgumentParser(
        description="Research Agent - Demonstrates vizpath tracing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "topic",
        nargs="?",
        default="What are the latest developments in AI agents?",
        help="The topic to research (default: AI agents)",
    )
    parser.add_argument(
        "--api-key",
        help="NVIDIA API key (or set NVIDIA_API_KEY env var)",
    )
    parser.add_argument(
        "--model",
        default="meta/llama-3.1-70b-instruct",
        help="Model to use (default: meta/llama-3.1-70b-instruct)",
    )
    parser.add_argument(
        "--vizpath-url",
        default="http://localhost:8000",
        help="Vizpath server URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--project-id",
        help="Vizpath project ID (optional, uses default project if not set)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without sending traces to vizpath (for testing)",
    )

    args = parser.parse_args()

    # Configure vizpath
    if not args.dry_run:
        configure(
            api_url=args.vizpath_url,
            project_id=args.project_id,
        )
        print(f"Vizpath configured: {args.vizpath_url}")
    else:
        print("Dry run mode - traces will not be sent to vizpath")

    # Check for API key
    api_key = args.api_key or os.getenv("NVIDIA_API_KEY")
    if not api_key:
        print("Error: NVIDIA_API_KEY not set. Please set it via:")
        print("  export NVIDIA_API_KEY='your-api-key'")
        print("  or pass --api-key 'your-api-key'")
        sys.exit(1)

    print(f"\nResearch Agent")
    print(f"==============")
    print(f"Topic: {args.topic}")
    print(f"Model: {args.model}")
    print()

    # Create and run agent
    agent = ResearchAgent(
        api_key=api_key,
        model=args.model,
    )

    print("Starting research...\n")
    report = agent.research(args.topic)

    print("\n" + "=" * 60)
    print("RESEARCH REPORT")
    print("=" * 60)
    print(report)
    print("=" * 60)

    if not args.dry_run:
        print(f"\nView traces at: {args.vizpath_url}/traces")


if __name__ == "__main__":
    main()
