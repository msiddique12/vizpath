import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Wand2, Loader2, Download, Copy, Check } from 'lucide-react'
import clsx from 'clsx'
import { generateSynthetic, SyntheticResult } from '@/lib/api'

interface SyntheticDataPanelProps {
  traceId: string
}

export default function SyntheticDataPanel({ traceId }: SyntheticDataPanelProps) {
  const [mode, setMode] = useState<'variations' | 'corrections'>('variations')
  const [n, setN] = useState(3)
  const [result, setResult] = useState<SyntheticResult | null>(null)
  const [copied, setCopied] = useState(false)

  const generateMutation = useMutation({
    mutationFn: () => generateSynthetic(traceId, mode, n),
    onSuccess: (data) => setResult(data),
  })

  const handleExportJSONL = () => {
    if (!result) return
    const lines = result.results.map((v) => JSON.stringify(v)).join('\n')
    const blob = new Blob([lines], { type: 'application/jsonl' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `synthetic-${mode}-${traceId.slice(0, 8)}.jsonl`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleCopy = async () => {
    if (!result) return
    const lines = result.results.map((v) => JSON.stringify(v)).join('\n')
    await navigator.clipboard.writeText(lines)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="bg-dark-800 rounded-lg p-4 space-y-4">
      <h3 className="text-sm font-medium text-muted-200 flex items-center gap-2">
        <Wand2 className="h-4 w-4" />
        Synthetic Data
      </h3>

      <div className="flex items-center gap-3">
        <div className="flex-1">
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as 'variations' | 'corrections')}
            className="w-full bg-dark-900 border border-dark-700 text-muted-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="variations">Variations</option>
            <option value="corrections">Corrections</option>
          </select>
        </div>
        <div className="w-20">
          <input
            type="number"
            min={1}
            max={10}
            value={n}
            onChange={(e) => setN(Math.max(1, Math.min(10, parseInt(e.target.value) || 1)))}
            className="w-full bg-dark-900 border border-dark-700 text-muted-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>
        <button
          onClick={() => generateMutation.mutate()}
          disabled={generateMutation.isPending}
          className={clsx(
            'flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-colors',
            generateMutation.isPending
              ? 'bg-dark-700 text-muted-400 cursor-wait'
              : 'bg-primary-600 text-white hover:bg-primary-700'
          )}
        >
          {generateMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Wand2 className="h-4 w-4" />
          )}
          Generate
        </button>
      </div>

      {generateMutation.isError && (
        <div className="bg-red-900/30 border border-red-800 rounded-lg px-3 py-2">
          <p className="text-xs text-red-400">
            {generateMutation.error?.message || 'Generation failed. Ensure NVIDIA API key is configured.'}
          </p>
        </div>
      )}

      {result && result.results.length > 0 && (
        <div className="space-y-3 pt-2 border-t border-dark-700">
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-400">
              {result.results.length} {result.mode} generated
            </p>
            <div className="flex items-center gap-1">
              <button
                onClick={handleCopy}
                className="flex items-center gap-1 px-2 py-1 text-xs text-muted-300 hover:text-muted-100 bg-dark-900 rounded border border-dark-700 transition-colors"
              >
                {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                {copied ? 'Copied' : 'Copy'}
              </button>
              <button
                onClick={handleExportJSONL}
                className="flex items-center gap-1 px-2 py-1 text-xs text-muted-300 hover:text-muted-100 bg-dark-900 rounded border border-dark-700 transition-colors"
              >
                <Download className="h-3 w-3" />
                JSONL
              </button>
            </div>
          </div>

          <div className="space-y-2 max-h-64 overflow-y-auto">
            {result.results.map((variation, i) => (
              <div key={i} className="bg-dark-900 rounded-lg p-3 border border-dark-700">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-medium text-muted-400">#{i + 1}</span>
                  {variation.metadata && (
                    <span className="text-xs text-muted-500">
                      {Object.entries(variation.metadata)
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(', ')}
                    </span>
                  )}
                </div>
                <div className="space-y-1.5">
                  <div>
                    <p className="text-xs text-muted-500 mb-0.5">Input</p>
                    <p className="text-xs text-muted-200 font-mono whitespace-pre-wrap break-words line-clamp-3">
                      {variation.input}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-500 mb-0.5">Output</p>
                    <p className="text-xs text-muted-200 font-mono whitespace-pre-wrap break-words line-clamp-3">
                      {variation.output}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
