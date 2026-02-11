"""LLM-based labeling and analysis of agent traces using Nemotron via NIM.

Adapted from engine/intelligence/llm.py to work with vizpath Trace+Span model.
"""

import asyncio
import json
import logging
import re
from typing import Any

import redis
from openai import AsyncOpenAI

from app.config import settings
from app.intelligence.embeddings import trace_to_text

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 86400 * 30  # 30 days
LABEL_CACHE_PREFIX = "label:"


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response text with 3-tier fallback.

    Strategies (in order):
    1. Direct json.loads on the full text
    2. Extract from ```json code block
    3. Regex for first {...} block

    Raises:
        ValueError: If all strategies fail.
    """
    if not text or not text.strip():
        raise ValueError("Empty text, cannot extract JSON")

    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from ```json ... ``` code block
    code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1))
        except json.JSONDecodeError:
            pass

    # Strategy 3: Regex for first { ... } block (greedy from first { to last })
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from text: {text[:200]}")


class LLMLabeler:
    """Nemotron-powered evaluation and analysis of agent traces."""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
        )
        self.model = settings.nvidia_llm_model
        self.temperature = 0.0
        self.max_tokens = 100

        # Redis setup
        try:
            self.redis: redis.Redis | None = redis.from_url(
                settings.redis_url, decode_responses=False
            )
            self.redis.ping()
        except Exception:
            self.redis = None

    async def label_trace(self, trace_data: dict[str, Any]) -> dict[str, Any] | None:
        """Evaluate a single trace using the LLM.

        Args:
            trace_data: Dict with trace fields and "spans" list.

        Returns:
            Dict with 'success', 'confidence', 'reasoning', or None on failure.
        """
        trace_id = trace_data.get("id")
        if not trace_id:
            logger.warning("Trace missing ID, skipping labeling.")
            return None

        # Check cache
        if self.redis:
            try:
                cached = self.redis.get(f"{LABEL_CACHE_PREFIX}{trace_id}")
                if cached:
                    return json.loads(cached)
            except Exception as e:
                logger.warning(f"Redis GET failed for label {trace_id}: {e}")

        trace_text = trace_to_text(trace_data)
        prompt = f"""You are an expert evaluator of AI agent behavior.

Evaluate this agent trace and determine if it was successful.

Trace:
{trace_text}

Respond ONLY with JSON:
{{
  "success": true,
  "confidence": 0.85,
  "reasoning": "brief explanation"
}}
"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            content = response.choices[0].message.content
            if not content:
                return None

            result = _extract_json(content)

            # Validate structure
            if not isinstance(result.get("success"), bool):
                raise ValueError("Invalid 'success' field")
            if not isinstance(result.get("confidence"), (int, float)):
                raise ValueError("Invalid 'confidence' field")
            if not isinstance(result.get("reasoning"), str):
                raise ValueError("Invalid 'reasoning' field")

            # Normalize confidence to [0, 1]
            if result["confidence"] > 1.0:
                result["confidence"] /= 100.0

            # Cache result
            if self.redis:
                try:
                    self.redis.set(
                        f"{LABEL_CACHE_PREFIX}{trace_id}",
                        json.dumps(result),
                        ex=CACHE_TTL_SECONDS,
                    )
                except Exception as e:
                    logger.warning(f"Redis SET failed for label {trace_id}: {e}")

            return result
        except Exception as e:
            logger.error(f"LLM labeling failed for trace {trace_id}: {e}")
            return None

    async def label_batch(
        self, traces: list[dict[str, Any]], batch_size: int = 10
    ) -> dict[str, dict[str, Any]]:
        """Label a batch of traces concurrently with rate limiting."""
        results: dict[str, dict[str, Any]] = {}
        semaphore = asyncio.Semaphore(batch_size)

        async def _process_one(trace_data: dict) -> None:
            async with semaphore:
                label = await self.label_trace(trace_data)
                if label and "id" in trace_data:
                    results[str(trace_data["id"])] = label

        tasks = [_process_one(t) for t in traces]
        await asyncio.gather(*tasks)
        return results

    async def analyze_trace(self, trace_data: dict) -> dict:
        """Analyze a trace, returning quality and efficiency scores.

        Returns:
            Dict with quality_score, efficiency_score, error_analysis, suggestions.
        """
        spans_summary = []
        for span in trace_data.get("spans", []):
            entry = f"- {span.get('name', 'unnamed')} (type={span.get('span_type', 'unknown')}"
            if span.get("duration_ms"):
                entry += f", duration={span['duration_ms']}ms"
            if span.get("tokens"):
                entry += f", tokens={span['tokens']}"
            if span.get("error"):
                entry += f", error={span['error']}"
            entry += ")"
            spans_summary.append(entry)

        spans_text = "\n".join(spans_summary) if spans_summary else "No spans recorded."

        prompt = f"""You are an expert AI agent evaluator analyzing execution traces.

Trace: {trace_data.get('name', 'unnamed')}
Status: {trace_data.get('status', 'unknown')}
Duration: {trace_data.get('duration_ms', 'unknown')}ms
Total tokens: {trace_data.get('total_tokens', 'unknown')}

Spans:
{spans_text}

Evaluate this trace and respond with JSON only:
{{
  "quality_score": 0-100,
  "efficiency_score": 0-100,
  "error_analysis": "description of any errors or issues found",
  "suggestions": ["suggestion 1", "suggestion 2"]
}}
"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
            )
            content = response.choices[0].message.content or ""
            return _extract_json(content)
        except Exception as e:
            logger.error(f"Trace analysis failed: {e}")
            return {
                "quality_score": 0,
                "efficiency_score": 0,
                "error_analysis": f"Analysis failed: {e}",
                "suggestions": [],
            }

    async def self_analyze(self, trace_data: dict) -> dict:
        """Deep evaluation of agent decision-making quality.

        Returns:
            Dict with quality, efficiency, completeness, overall_score,
            redundant_steps, suggestions, summary.
        """
        spans_detail = []
        for i, span in enumerate(trace_data.get("spans", []), 1):
            entry = f"Step {i}: {span.get('name', 'unnamed')}"
            entry += f" [type={span.get('span_type', 'unknown')}]"
            if span.get("duration_ms"):
                entry += f" ({span['duration_ms']}ms)"
            if span.get("input"):
                input_str = str(span["input"])[:200]
                entry += f"\n  Input: {input_str}"
            if span.get("output"):
                output_str = str(span["output"])[:200]
                entry += f"\n  Output: {output_str}"
            if span.get("error"):
                entry += f"\n  ERROR: {span['error']}"
            spans_detail.append(entry)

        steps_text = "\n".join(spans_detail) if spans_detail else "No execution steps recorded."

        prompt = f"""You are performing a thorough audit of an AI agent's execution trace. \
Your job is to evaluate the agent's decision-making quality, identify inefficiencies, \
and provide actionable improvement suggestions.

Agent Trace: {trace_data.get('name', 'unnamed')}
Status: {trace_data.get('status', 'unknown')}
Total duration: {trace_data.get('duration_ms', 'unknown')}ms
Total tokens used: {trace_data.get('total_tokens', 'unknown')}
Total cost: {trace_data.get('total_cost', 'unknown')}

Execution steps:
{steps_text}

Analyze this agent's behavior thoroughly. Consider:
1. Were the steps logical and well-ordered?
2. Were any steps redundant or unnecessary?
3. Did the agent use tools effectively?
4. Were there missed opportunities or better approaches?
5. Was token usage efficient?

Respond with JSON only:
{{
  "quality": 0-100,
  "efficiency": 0-100,
  "completeness": 0-100,
  "overall_score": 0-100,
  "redundant_steps": ["step description if any"],
  "suggestions": ["actionable improvement 1", "actionable improvement 2"],
  "summary": "2-3 sentence overall assessment"
}}
"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=800,
            )
            content = response.choices[0].message.content or ""
            return _extract_json(content)
        except Exception as e:
            logger.error(f"Self-analysis failed: {e}")
            return {
                "quality": 0,
                "efficiency": 0,
                "completeness": 0,
                "overall_score": 0,
                "redundant_steps": [],
                "suggestions": [],
                "summary": f"Analysis failed: {e}",
            }

    def estimate_cost(self, trace_count: int) -> float:
        """Estimate cost of labeling N traces via NIM.

        NIM free tier: zero cost for development.
        """
        input_tokens = trace_count * 500
        output_tokens = trace_count * 50
        input_cost = (input_tokens / 1_000_000) * 0.10
        output_cost = (output_tokens / 1_000_000) * 0.30
        return round(input_cost + output_cost, 4)
