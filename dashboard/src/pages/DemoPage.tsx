import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { CheckCircle2, Circle, Copy, ExternalLink, Loader2, PlayCircle, Server, Sparkles } from 'lucide-react'
import { getDetailedHealth, getIntelligenceStatus } from '@/lib/api'

function StatusDot({ ok }: { ok: boolean }) {
  return ok ? (
    <CheckCircle2 className="h-4 w-4 text-green-400" />
  ) : (
    <Circle className="h-4 w-4 text-muted-500" />
  )
}

export default function DemoPage() {
  const [copiedCmd, setCopiedCmd] = useState<string | null>(null)

  const healthQuery = useQuery({
    queryKey: ['health-detailed'],
    queryFn: getDetailedHealth,
    refetchInterval: 5000,
  })

  const intelligenceQuery = useQuery({
    queryKey: ['intelligence-status'],
    queryFn: getIntelligenceStatus,
    refetchInterval: 5000,
  })

  const isLoading = healthQuery.isLoading || intelligenceQuery.isLoading
  const dbReady = healthQuery.data?.checks.database?.status === 'healthy'
  const redisReady = healthQuery.data?.checks.redis?.status === 'healthy'
  const apiReady = healthQuery.data?.status === 'healthy' || healthQuery.data?.status === 'degraded'
  const nimReady = intelligenceQuery.data?.nvidia_api_key_configured ?? false

  const runCommand = 'python -m examples.code_agent.run "How does the intelligence module work?" -v'
  const startupCommand = './demo.sh'

  const copyText = async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedCmd(key)
      setTimeout(() => setCopiedCmd(null), 1500)
    } catch {
      setCopiedCmd(null)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-muted-100">Demo Mode</h1>
        <p className="mt-1 text-sm text-muted-400">
          Run a complete end-to-end demo with live trace visualization and intelligence checks.
        </p>
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-muted-200 flex items-center gap-2">
            <Server className="h-4 w-4" />
            Readiness Status
          </h2>
          {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-400" />}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
          <div className="bg-dark-800 rounded-lg p-3 flex items-center justify-between">
            <span className="text-sm text-muted-300">API reachable</span>
            <StatusDot ok={!!apiReady} />
          </div>
          <div className="bg-dark-800 rounded-lg p-3 flex items-center justify-between">
            <span className="text-sm text-muted-300">Database healthy</span>
            <StatusDot ok={!!dbReady} />
          </div>
          <div className="bg-dark-800 rounded-lg p-3 flex items-center justify-between">
            <span className="text-sm text-muted-300">Redis healthy</span>
            <StatusDot ok={!!redisReady} />
          </div>
          <div className="bg-dark-800 rounded-lg p-3 flex items-center justify-between">
            <span className="text-sm text-muted-300">NVIDIA key configured</span>
            <StatusDot ok={nimReady} />
          </div>
        </div>

        {(healthQuery.isError || intelligenceQuery.isError) && (
          <div className="mt-3 text-xs text-red-400">
            Could not fetch readiness data. Make sure `./demo.sh` is running.
          </div>
        )}
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 p-4">
        <h2 className="text-sm font-medium text-muted-200 flex items-center gap-2">
          <PlayCircle className="h-4 w-4" />
          Demo Checklist
        </h2>
        <ol className="mt-3 space-y-3 text-sm text-muted-300">
          <li className="bg-dark-800 rounded-lg p-3">
            In terminal 1, run the stack startup script.
            <div className="mt-2 flex items-center gap-2">
              <code className="text-xs text-muted-200 bg-dark-900 border border-dark-700 rounded px-2 py-1">
                {startupCommand}
              </code>
              <button
                onClick={() => copyText(startupCommand, 'startup')}
                className="inline-flex items-center gap-1 text-xs text-muted-300 hover:text-muted-100"
              >
                <Copy className="h-3 w-3" />
                {copiedCmd === 'startup' ? 'Copied' : 'Copy'}
              </button>
            </div>
          </li>

          <li className="bg-dark-800 rounded-lg p-3">
            In terminal 2, run the demo agent.
            <div className="mt-2 flex items-center gap-2">
              <code className="text-xs text-muted-200 bg-dark-900 border border-dark-700 rounded px-2 py-1 break-all">
                {runCommand}
              </code>
              <button
                onClick={() => copyText(runCommand, 'agent')}
                className="inline-flex items-center gap-1 text-xs text-muted-300 hover:text-muted-100"
              >
                <Copy className="h-3 w-3" />
                {copiedCmd === 'agent' ? 'Copied' : 'Copy'}
              </button>
            </div>
          </li>

          <li className="bg-dark-800 rounded-lg p-3">
            Open the latest trace and show timeline, DAG, and heatmap views.
          </li>

          <li className="bg-dark-800 rounded-lg p-3">
            Run <span className="text-muted-100">Analyze</span> and{' '}
            <span className="text-muted-100">Deep Analysis</span> in the trace detail panel.
          </li>

          <li className="bg-dark-800 rounded-lg p-3">
            Add curation labels, then export synthetic data from the Curation page.
          </li>
        </ol>
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 p-4">
        <h2 className="text-sm font-medium text-muted-200 flex items-center gap-2">
          <Sparkles className="h-4 w-4" />
          Quick Links
        </h2>
        <div className="mt-3 flex flex-wrap gap-2">
          <a
            href="/traces"
            className={clsx(
              'inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm',
              'bg-dark-800 text-muted-200 hover:bg-dark-700'
            )}
          >
            Traces <ExternalLink className="h-3 w-3" />
          </a>
          <a
            href="/curation"
            className={clsx(
              'inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm',
              'bg-dark-800 text-muted-200 hover:bg-dark-700'
            )}
          >
            Curation <ExternalLink className="h-3 w-3" />
          </a>
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noreferrer"
            className={clsx(
              'inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm',
              'bg-dark-800 text-muted-200 hover:bg-dark-700'
            )}
          >
            API Docs <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </div>
    </div>
  )
}

