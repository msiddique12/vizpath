import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import IntelligencePanel from '../IntelligencePanel'
import { renderWithProviders } from '../../test/test-utils'

function createJsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('IntelligencePanel deterministic diagnostics', () => {
  let originalFetch: typeof fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('runs failure mode diagnostics and renders primary mode', async () => {
    let failureRequestBody: Record<string, unknown> | null = null
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/v1/intelligence/status')) {
        return createJsonResponse({
          nvidia_api_key_configured: false,
          model: 'nvidia/test-model',
          base_url: 'https://api.example.test',
          llm_timeout_seconds: 20,
          llm_max_tokens: 2000,
        })
      }
      if (url.includes('/api/v1/intelligence/copilot')) {
        return createJsonResponse({
          trace_id: 'trace-current',
          baseline_trace_id: null,
          triage_score: 42,
          triage_status: 'review',
          confidence: 0.72,
          summary: 'Failure signals point to tool instability (72% confidence).',
          root_cause: {
            title: 'Failure signals point to tool instability',
            detail: 'Validate tool inputs, permissions, and fallback behavior.',
            source: 'failure_modes',
            confidence: 0.72,
          },
          next_fixes: [
            {
              id: 'fix-1',
              title: 'Mitigate tool failure mode',
              priority: 'high',
              rationale: 'Validate tool inputs, permissions, and fallback behavior.',
              expected_gain: 'Improve trace reliability and reduce failed spans.',
              linked_span_ids: ['trace-current-span-1'],
            },
          ],
          span_references: [
            {
              span_id: 'trace-current-span-1',
              span_name: 'shell_command',
              span_type: 'tool',
              status: 'error',
              duration_ms: 430,
              tokens: 0,
              reason: 'Referenced by failure-mode evidence',
            },
          ],
          candidate_failure: { status: 'issue_detected', primary_mode: 'tool', confidence: 0.72 },
          candidate_anomaly: { status: 'watch', anomaly_score: 22, anomaly_count: 1 },
          candidate_safety: { risk_level: 'low', risk_score: 0 },
          compare_summary: null,
          generated_at: new Date().toISOString(),
          cached: false,
          cache_ttl_seconds: 120,
        })
      }
      if (url.includes('/api/v1/intelligence/failure-modes')) {
        failureRequestBody = JSON.parse(String(init?.body ?? '{}'))
        return createJsonResponse({
          trace_id: 'trace-current',
          status: 'issue_detected',
          primary_mode: 'tool',
          confidence: 0.81,
          summary: "Primary failure mode is 'tool' with high severity signals.",
          modes: [
            {
              mode: 'tool',
              score: 68,
              severity: 'high',
              evidence_count: 2,
              evidence: [],
              recommendations: ['Validate tool inputs, permissions, and fallback behavior.'],
            },
          ],
        })
      }
      throw new Error(`Unexpected fetch call: ${url}`)
    }) as unknown as typeof fetch

    renderWithProviders(<IntelligencePanel traceId="trace-current" />)
    const button = await screen.findByRole('button', { name: 'Failure Modes' })
    fireEvent.click(button)

    await waitFor(() => {
      expect(screen.getByText(/Primary mode:/)).toBeInTheDocument()
      expect(screen.getByText(/tool · 68 · high/)).toBeInTheDocument()
    })
    expect(failureRequestBody).toEqual({ trace_id: 'trace-current' })
  })

  it('runs regression explain with baseline trace id', async () => {
    let regressionRequestBody: Record<string, unknown> | null = null
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/v1/intelligence/status')) {
        return createJsonResponse({
          nvidia_api_key_configured: true,
          model: 'nvidia/test-model',
          base_url: 'https://api.example.test',
          llm_timeout_seconds: 15,
          llm_max_tokens: 1024,
        })
      }
      if (url.includes('/api/v1/intelligence/copilot')) {
        return createJsonResponse({
          trace_id: 'trace-current',
          baseline_trace_id: null,
          triage_score: 24,
          triage_status: 'stable',
          confidence: 0.25,
          summary: 'No strong root-cause signal detected (25% confidence).',
          root_cause: {
            title: 'No strong root-cause signal detected',
            detail: 'This trace looks stable relative to current deterministic checks.',
            source: 'summary',
            confidence: 0.25,
          },
          next_fixes: [
            {
              id: 'fix-1',
              title: 'Continue monitoring this trace pattern',
              priority: 'low',
              rationale: 'No high-confidence failure vectors were detected by deterministic checks.',
              expected_gain: 'Maintain baseline quality while collecting more data.',
              linked_span_ids: [],
            },
          ],
          span_references: [],
          candidate_failure: { status: 'no_major_failure_signals', primary_mode: 'none', confidence: 0 },
          candidate_anomaly: { status: 'normal', anomaly_score: 0, anomaly_count: 0 },
          candidate_safety: { risk_level: 'low', risk_score: 0 },
          compare_summary: null,
          generated_at: new Date().toISOString(),
          cached: false,
          cache_ttl_seconds: 120,
        })
      }
      if (url.includes('/api/v1/intelligence/regression-explain')) {
        regressionRequestBody = JSON.parse(String(init?.body ?? '{}'))
        return createJsonResponse({
          trace_a_id: 'trace-baseline',
          trace_b_id: 'trace-current',
          compare_summary: { status: 'regressed', regression_score: 55, signal_count: 2 },
          candidate_failure: { status: 'issue_detected', primary_mode: 'infra', confidence: 0.77 },
          candidate_anomaly: { status: 'outlier', anomaly_score: 72, anomaly_count: 2 },
          candidate_safety: { risk_level: 'low', risk_score: 0 },
          explanation: {
            status: 'regression_explained',
            hypothesis_count: 1,
            top_hypothesis_confidence: 0.88,
            summary: 'Generated 1 ranked root-cause hypotheses from deterministic signals.',
            hypotheses: [
              {
                id: 'reliability_regression',
                title: 'New reliability failures in candidate trace',
                confidence: 0.88,
                severity: 'high',
                evidence: ['Trace B has more error spans than Trace A.'],
                recommendation: 'Review erroring spans first; add retries/fallbacks only where deterministic.',
              },
            ],
          },
        })
      }
      throw new Error(`Unexpected fetch call: ${url}`)
    }) as unknown as typeof fetch

    renderWithProviders(<IntelligencePanel traceId="trace-current" />)
    const explainButton = await screen.findByRole('button', { name: 'Explain Regression' })
    expect(explainButton).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Baseline Trace ID (for regression explain)'), {
      target: { value: 'trace-baseline' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Explain Regression' }))

    await waitFor(() => {
      expect(screen.getByText('Guardrails: timeout 15s · max tokens 1024')).toBeInTheDocument()
      expect(screen.getByText(/Regression Explain/)).toBeInTheDocument()
      expect(screen.getByText(/New reliability failures in candidate trace/)).toBeInTheDocument()
    })
    expect(regressionRequestBody).toMatchObject({
      trace_a_id: 'trace-baseline',
      trace_b_id: 'trace-current',
    })
  })

  it('renders copilot root cause and fix recommendations', async () => {
    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/v1/intelligence/status')) {
        return createJsonResponse({
          nvidia_api_key_configured: true,
          model: 'nvidia/test-model',
          base_url: 'https://api.example.test',
          llm_timeout_seconds: 12,
          llm_max_tokens: 1500,
        })
      }
      if (url.includes('/api/v1/intelligence/copilot')) {
        return createJsonResponse({
          trace_id: 'trace-current',
          baseline_trace_id: null,
          triage_score: 78,
          triage_status: 'high_risk',
          confidence: 0.88,
          summary: 'New reliability failures in candidate trace (88% confidence).',
          root_cause: {
            title: 'New reliability failures in candidate trace',
            detail: 'Review erroring spans first and add deterministic fallback handling.',
            source: 'regression_explain',
            confidence: 0.88,
          },
          next_fixes: [
            {
              id: 'fix-1',
              title: 'Address primary root-cause recommendation',
              priority: 'high',
              rationale: 'Review erroring spans first and add deterministic fallback handling.',
              expected_gain: 'Reduce recurrence of the top failure signal.',
              linked_span_ids: ['span-1'],
            },
          ],
          span_references: [
            {
              span_id: 'span-1',
              span_name: 'candidate_tool',
              span_type: 'tool',
              status: 'error',
              duration_ms: 410,
              tokens: 0,
              reason: 'Referenced by failure-mode evidence',
            },
          ],
          candidate_failure: { status: 'issue_detected', primary_mode: 'tool', confidence: 0.82 },
          candidate_anomaly: { status: 'outlier', anomaly_score: 66, anomaly_count: 2 },
          candidate_safety: { risk_level: 'low', risk_score: 0 },
          compare_summary: null,
          generated_at: new Date().toISOString(),
          cached: false,
          cache_ttl_seconds: 120,
        })
      }
      throw new Error(`Unexpected fetch call: ${url}`)
    }) as unknown as typeof fetch

    renderWithProviders(<IntelligencePanel traceId="trace-current" />)

    await waitFor(() => {
      expect(screen.getByText('Guardrails: timeout 12s · max tokens 1500')).toBeInTheDocument()
      expect(
        screen.getByText((text) => text.includes('Fresh') && text.includes('generated'))
      ).toBeInTheDocument()
      expect(screen.getByText('Trace Copilot')).toBeInTheDocument()
      expect(screen.getByText('New reliability failures in candidate trace')).toBeInTheDocument()
      expect(screen.getAllByText('Address primary root-cause recommendation').length).toBeGreaterThan(0)
      expect(screen.getByText('candidate_tool')).toBeInTheDocument()
    })
  })

  it('forces fresh copilot recompute when refresh is clicked', async () => {
    const copilotRefreshFlags: boolean[] = []

    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/v1/intelligence/status')) {
        return createJsonResponse({
          nvidia_api_key_configured: true,
          model: 'nvidia/test-model',
          base_url: 'https://api.example.test',
          llm_timeout_seconds: 12,
          llm_max_tokens: 1500,
        })
      }
      if (url.includes('/api/v1/intelligence/copilot')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as { refresh_cache?: boolean }
        copilotRefreshFlags.push(Boolean(body.refresh_cache))
        const isFresh = Boolean(body.refresh_cache)
        return createJsonResponse({
          trace_id: 'trace-current',
          baseline_trace_id: null,
          triage_score: isFresh ? 80 : 78,
          triage_status: 'high_risk',
          confidence: 0.88,
          summary: isFresh
            ? 'Fresh copilot recompute completed.'
            : 'Cached copilot summary.',
          root_cause: {
            title: 'New reliability failures in candidate trace',
            detail: 'Review erroring spans first and add deterministic fallback handling.',
            source: 'regression_explain',
            confidence: 0.88,
          },
          next_fixes: [
            {
              id: 'fix-1',
              title: 'Address primary root-cause recommendation',
              priority: 'high',
              rationale: 'Review erroring spans first and add deterministic fallback handling.',
              expected_gain: 'Reduce recurrence of the top failure signal.',
              linked_span_ids: ['span-1'],
            },
          ],
          span_references: [
            {
              span_id: 'span-1',
              span_name: 'candidate_tool',
              span_type: 'tool',
              status: 'error',
              duration_ms: 410,
              tokens: 0,
              reason: 'Referenced by failure-mode evidence',
            },
          ],
          candidate_failure: { status: 'issue_detected', primary_mode: 'tool', confidence: 0.82 },
          candidate_anomaly: { status: 'outlier', anomaly_score: 66, anomaly_count: 2 },
          candidate_safety: { risk_level: 'low', risk_score: 0 },
          compare_summary: null,
          generated_at: new Date().toISOString(),
          cached: !isFresh,
          cache_ttl_seconds: 120,
        })
      }
      throw new Error(`Unexpected fetch call: ${url}`)
    }) as unknown as typeof fetch

    renderWithProviders(<IntelligencePanel traceId="trace-current" />)

    await waitFor(() => {
      expect(copilotRefreshFlags.length).toBeGreaterThan(0)
    })
    expect(copilotRefreshFlags).toContain(false)

    const refreshButton = screen.getByRole('button', { name: 'Refresh' })
    await waitFor(() => {
      expect(refreshButton).not.toBeDisabled()
    })
    fireEvent.click(refreshButton)

    await waitFor(() => {
      expect(copilotRefreshFlags.length).toBeGreaterThan(1)
      expect(copilotRefreshFlags).toContain(true)
    })
  })
})
