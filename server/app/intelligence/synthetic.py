"""Synthetic data generation for agent trace finetuning.

Uses Nemotron via NIM to generate training data variations and corrections
from real traces. Adapted from engine/intelligence/synthetic.py.
"""

import json
import logging

from openai import AsyncOpenAI

from app.config import settings
from app.intelligence.llm import _extract_json

logger = logging.getLogger(__name__)


class SyntheticDataGenerator:
    """Generate synthetic training data from agent traces using Nemotron."""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
        )
        self.model = settings.nvidia_llm_model

    async def generate_variations(self, trace_data: dict, n: int = 5) -> list[dict]:
        """Generate N successful variations of a trace.

        Args:
            trace_data: Dict with trace name, spans, and metadata.
            n: Number of variations to generate.

        Returns:
            List of variation dicts with name, steps, and approach.
        """
        steps_desc = []
        for span in trace_data.get("spans", []):
            steps_desc.append(
                f"- {span.get('name', 'unnamed')} (type={span.get('span_type', 'unknown')})"
            )
        steps_text = "\n".join(steps_desc) if steps_desc else "No steps recorded."

        prompt = f"""You are generating synthetic training data for AI agent finetuning.

Given this successful agent trace, generate {n} plausible variations that:
- Achieve the same goal through different valid approaches
- Maintain semantic correctness
- Vary in tool ordering, strategy, or detail level

Original trace: {trace_data.get('name', 'unnamed')}
Steps:
{steps_text}

Respond with JSON only:
{{
  "variations": [
    {{
      "name": "variation description",
      "steps": [
        {{"action": "step description", "tool": "tool_name", "reasoning": "why this step"}}
      ],
      "approach": "brief description of how this differs from original"
    }}
  ]
}}
"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=2000,
            )
            content = response.choices[0].message.content or ""
            result = _extract_json(content)
            return result.get("variations", [])[:n]
        except Exception as e:
            logger.error(f"Variation generation failed: {e}")
            return []

    async def generate_corrections(self, failed_trace: dict, n: int = 3) -> list[dict]:
        """Generate corrected versions of a failed trace.

        Args:
            failed_trace: Dict with trace data including error information.
            n: Number of corrections to generate.

        Returns:
            List of correction dicts with corrected steps and explanation.
        """
        steps_desc = []
        for span in failed_trace.get("spans", []):
            entry = f"- {span.get('name', 'unnamed')} (type={span.get('span_type', 'unknown')})"
            if span.get("error"):
                entry += f" [ERROR: {span['error']}]"
            steps_desc.append(entry)
        steps_text = "\n".join(steps_desc) if steps_desc else "No steps recorded."

        error_info = failed_trace.get("error", "Unknown error")

        prompt = f"""You are generating corrected training data for AI agent finetuning.

This agent trace failed. Analyze the failure and generate {n} corrected versions
that would have succeeded.

Failed trace: {failed_trace.get('name', 'unnamed')}
Error: {error_info}
Steps:
{steps_text}

Respond with JSON only:
{{
  "corrections": [
    {{
      "name": "corrected version description",
      "failure_analysis": "what went wrong in the original",
      "steps": [
        {{"action": "corrected step", "tool": "tool_name", "reasoning": "why this fixes the issue"}}
      ]
    }}
  ]
}}
"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=2000,
            )
            content = response.choices[0].message.content or ""
            result = _extract_json(content)
            return result.get("corrections", [])[:n]
        except Exception as e:
            logger.error(f"Correction generation failed: {e}")
            return []

    async def export_training_pairs(self, traces: list[dict], format: str = "jsonl") -> str:
        """Format traces as input/output pairs for SFT/RLHF.

        Args:
            traces: List of trace dicts with task description and spans.
            format: Output format (currently 'jsonl').

        Returns:
            String of formatted training data.
        """
        lines = []
        for trace in traces:
            task = trace.get("name", "")
            steps = trace.get("spans", [])

            input_text = f"Task: {task}"
            if trace.get("metadata"):
                meta = trace["metadata"]
                if meta.get("research.topic"):
                    input_text = f"Research: {meta['research.topic']}"

            output_steps = []
            for span in steps:
                step = {
                    "action": span.get("name", ""),
                    "type": span.get("span_type", ""),
                }
                if span.get("output"):
                    output_str = str(span["output"])
                    step["result"] = output_str[:500]
                output_steps.append(step)

            pair = {
                "input": input_text,
                "output": json.dumps(output_steps),
                "metadata": {
                    "source_trace": trace.get("id", ""),
                    "success": trace.get("status") == "success",
                },
            }
            lines.append(json.dumps(pair))

        return "\n".join(lines)
