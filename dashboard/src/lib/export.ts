import { Trace, Span } from './types'

export type ExportFormat = 'json' | 'csv' | 'jsonl'

interface TraceExport {
  trace: Trace
  spans: Span[]
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function formatTimestamp(ts: string): string {
  return new Date(ts).toISOString().replace(/[:.]/g, '-')
}

export function exportToJSON(data: TraceExport | TraceExport[], filename?: string) {
  const content = JSON.stringify(data, null, 2)
  const blob = new Blob([content], { type: 'application/json' })
  const name = filename || `vizpath-export-${formatTimestamp(new Date().toISOString())}.json`
  downloadBlob(blob, name)
}

export function exportToJSONL(data: TraceExport[], filename?: string) {
  const lines = data.map((item) => JSON.stringify(item))
  const content = lines.join('\n')
  const blob = new Blob([content], { type: 'application/x-ndjson' })
  const name = filename || `vizpath-export-${formatTimestamp(new Date().toISOString())}.jsonl`
  downloadBlob(blob, name)
}

export function exportToCSV(spans: Span[], filename?: string) {
  const headers = [
    'id',
    'trace_id',
    'parent_span_id',
    'name',
    'span_type',
    'status',
    'start_time',
    'end_time',
    'duration_ms',
    'token_count',
    'input',
    'output',
    'error',
  ]

  const escapeCSV = (value: unknown): string => {
    if (value === null || value === undefined) return ''
    const str = typeof value === 'object' ? JSON.stringify(value) : String(value)
    if (str.includes(',') || str.includes('"') || str.includes('\n')) {
      return `"${str.replace(/"/g, '""')}"`
    }
    return str
  }

  const rows = spans.map((span) =>
    [
      span.id,
      span.trace_id,
      span.parent_id || span.parent_span_id || '',
      span.name,
      span.span_type,
      span.status,
      span.start_time,
      span.end_time || '',
      span.duration_ms || '',
      span.tokens || span.token_count || '',
      escapeCSV(span.input),
      escapeCSV(span.output),
      span.error || '',
    ].map(escapeCSV).join(',')
  )

  const content = [headers.join(','), ...rows].join('\n')
  const blob = new Blob([content], { type: 'text/csv' })
  const name = filename || `vizpath-spans-${formatTimestamp(new Date().toISOString())}.csv`
  downloadBlob(blob, name)
}

export function exportTrace(data: TraceExport, format: ExportFormat) {
  const timestamp = formatTimestamp(data.trace.created_at || data.trace.start_time)
  const baseName = `${data.trace.name.replace(/[^a-zA-Z0-9-_]/g, '_')}-${timestamp}`

  switch (format) {
    case 'json':
      exportToJSON(data, `${baseName}.json`)
      break
    case 'jsonl':
      exportToJSONL([data], `${baseName}.jsonl`)
      break
    case 'csv':
      exportToCSV(data.spans, `${baseName}-spans.csv`)
      break
  }
}

export function exportTraces(data: TraceExport[], format: ExportFormat) {
  const timestamp = formatTimestamp(new Date().toISOString())
  const baseName = `vizpath-export-${data.length}traces-${timestamp}`

  switch (format) {
    case 'json':
      exportToJSON(data, `${baseName}.json`)
      break
    case 'jsonl':
      exportToJSONL(data, `${baseName}.jsonl`)
      break
    case 'csv': {
      const allSpans = data.flatMap((d) => d.spans)
      exportToCSV(allSpans, `${baseName}-spans.csv`)
      break
    }
  }
}
