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
    """Extract JSON from LLM response text with 4-tier fallback.

    Strategies (in order):
    0. Strip <think>...</think> tags (model chain-of-thought)
    1. Direct json.loads on the full text
    2. Extract from ```json code block
    3. Regex for first {...} block

    Raises:
        ValueError: If all strategies fail.
    """
    if not text or not text.strip():
        raise ValueError("Empty text, cannot extract JSON")

    # Strategy 0: Strip <think>...</think> tags (Nemotron outputs these)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    if not text:
        raise ValueError("Empty text after stripping think tags")

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
        """Analyze a trace, returning quality scores, labels, and suggestions.

        Returns:
            Dict with trace_id, analysis (quality_score, labels, suggestions, summary), cached.
        """
        trace_id = trace_data.get("id", "unknown")

        # Check cache
        cache_key = f"analyze:{trace_id}"
        if self.redis:
            try:
                cached = self.redis.get(cache_key)
                if cached:
                    result = json.loads(cached)
                    result["cached"] = True
                    return result
            except Exception as e:
                logger.warning(f"Redis GET failed for analyze {trace_id}: {e}")

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
  "labels": ["label1", "label2"],
  "suggestions": ["suggestion 1", "suggestion 2"],
  "summary": "Brief 1-2 sentence summary of trace quality"
}}

Labels should be relevant categories like: "efficient", "slow", "error_prone", "tool_heavy", "well_structured", "needs_optimization", etc.
"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
            )
            content = response.choices[0].message.content or ""
            analysis = _extract_json(content)
            result = {
                "trace_id": trace_id,
                "quality_score": analysis.get("quality_score", 0),
                "efficiency_score": analysis.get("efficiency_score", 0),
                "error_analysis": analysis.get("error_analysis", analysis.get("summary", "")),
                "suggestions": analysis.get("suggestions", []),
                "labels": analysis.get("labels", []),
                "summary": analysis.get("summary", ""),
                "cached": False,
            }

            # Cache result
            if self.redis:
                try:
                    self.redis.set(cache_key, json.dumps(result), ex=CACHE_TTL_SECONDS)
                except Exception as e:
                    logger.warning(f"Redis SET failed for analyze {trace_id}: {e}")

            return result
        except Exception as e:
            logger.error(f"Trace analysis failed: {e}")
            return {
                "trace_id": trace_id,
                "quality_score": 0,
                "efficiency_score": 0,
                "error_analysis": f"Analysis failed: {e}",
                "suggestions": [],
                "labels": [],
                "summary": f"Analysis failed: {e}",
                "cached": False,
            }

    async def self_analyze(self, trace_data: dict) -> dict:
        """Deep evaluation of agent decision-making quality.

        Returns:
            Dict with trace_id, analysis (effectiveness, reasoning_quality, tool_usage,
            overall_score, strengths, weaknesses, improvements, summary), cached.
        """
        trace_id = trace_data.get("id", "unknown")

        # Check cache
        cache_key = f"self_analyze:{trace_id}"
        if self.redis:
            try:
                cached = self.redis.get(cache_key)
                if cached:
                    result = json.loads(cached)
                    result["cached"] = True
                    return result
            except Exception as e:
                logger.warning(f"Redis GET failed for self_analyze {trace_id}: {e}")

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
Your job is to evaluate the agent's decision-making quality, identify strengths and weaknesses, \
and provide actionable improvement suggestions.

Agent Trace: {trace_data.get('name', 'unnamed')}
Status: {trace_data.get('status', 'unknown')}
Total duration: {trace_data.get('duration_ms', 'unknown')}ms
Total tokens used: {trace_data.get('total_tokens', 'unknown')}
Total cost: {trace_data.get('total_cost', 'unknown')}

Execution steps:
{steps_text}

Analyze this agent's behavior thoroughly. Consider:
1. How effective was the agent at achieving its goal?
2. Was the reasoning quality high? Were decisions logical?
3. Were tools used appropriately and efficiently?
4. What were the agent's strengths?
5. What were the agent's weaknesses?

Respond with JSON only:
{{
  "effectiveness": 0-100,
  "reasoning_quality": 0-100,
  "tool_usage": 0-100,
  "overall_score": 0-100,
  "strengths": ["strength 1", "strength 2"],
  "weaknesses": ["weakness 1", "weakness 2"],
  "improvements": ["actionable improvement 1", "actionable improvement 2"],
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
            analysis = _extract_json(content)
            result = {
                "trace_id": trace_id,
                "quality": analysis.get("quality", analysis.get("effectiveness", 0)),
                "efficiency": analysis.get("efficiency", analysis.get("tool_usage", 0)),
                "completeness": analysis.get("completeness", analysis.get("reasoning_quality", 0)),
                "overall_score": analysis.get("overall_score", 0),
                "redundant_steps": analysis.get("redundant_steps", []),
                "suggestions": analysis.get("suggestions", analysis.get("improvements", [])),
                "summary": analysis.get("summary", ""),
                "effectiveness": analysis.get("effectiveness", analysis.get("quality", 0)),
                "reasoning_quality": analysis.get("reasoning_quality", analysis.get("completeness", 0)),
                "tool_usage": analysis.get("tool_usage", analysis.get("efficiency", 0)),
                "strengths": analysis.get("strengths", []),
                "weaknesses": analysis.get("weaknesses", []),
                "improvements": analysis.get("improvements", analysis.get("suggestions", [])),
                "cached": False,
            }

            # Cache result
            if self.redis:
                try:
                    self.redis.set(cache_key, json.dumps(result), ex=CACHE_TTL_SECONDS)
                except Exception as e:
                    logger.warning(f"Redis SET failed for self_analyze {trace_id}: {e}")

            return result
        except Exception as e:
            logger.error(f"Self-analysis failed: {e}")
            return {
                "trace_id": trace_id,
                "quality": 0,
                "efficiency": 0,
                "completeness": 0,
                "overall_score": 0,
                "redundant_steps": [],
                "suggestions": [],
                "summary": f"Analysis failed: {e}",
                "effectiveness": 0,
                "reasoning_quality": 0,
                "tool_usage": 0,
                "strengths": [],
                "weaknesses": [],
                "improvements": [],
                "cached": False,
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
