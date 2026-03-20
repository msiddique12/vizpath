import { FormEvent, useState } from 'react'
import clsx from 'clsx'

interface WebSocketCloseReason {
  code: number
  reason: string
  canRetry: boolean
}

interface WebSocketRecoveryPanelProps {
  isConnected: boolean
  lastDisconnect: WebSocketCloseReason | null
  authKeyConfigured: boolean
  onRetry: () => void
  onSubmitApiKey: (apiKey: string) => void
  inputId: string
  panelTone?: 'default' | 'muted'
}

export default function WebSocketRecoveryPanel({
  isConnected,
  lastDisconnect,
  authKeyConfigured,
  onRetry,
  onSubmitApiKey,
  inputId,
  panelTone = 'default',
}: WebSocketRecoveryPanelProps) {
  const isAuthFailure = lastDisconnect?.code === 4001
  const canRetryConnection = lastDisconnect?.canRetry ?? !isAuthFailure
  const connectionStatusText = isAuthFailure
    ? 'Live updates are unavailable: authentication is required for WebSocket streaming.'
    : isConnected
      ? null
      : 'Live updates disconnected. Retrying automatically when possible.'
  const [manualWsApiKey, setManualWsApiKey] = useState('')

  if (!connectionStatusText) {
    return null
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmed = manualWsApiKey.trim()
    if (!trimmed) {
      return
    }
    onSubmitApiKey(trimmed)
    setManualWsApiKey('')
  }

  return (
    <div
      role="status"
        className={clsx(
        'mt-3 rounded-lg border px-3 py-2 text-xs',
        isAuthFailure
          ? 'bg-amber-900/30 border-amber-700/60 text-amber-200'
          : panelTone === 'muted'
            ? 'bg-blue-900/20 border-blue-700/40 text-blue-200'
            : 'bg-blue-900/30 border-blue-700/60 text-blue-200'
      )}
    >
      <p>{connectionStatusText}</p>
      <div className="mt-2 flex items-center gap-2 flex-wrap">
        {isAuthFailure && (
          <p className="text-xs text-amber-300/90">
            {authKeyConfigured
              ? 'A websocket API key was provided, but authentication failed. Use a replacement key to reconnect.'
              : 'Use a websocket API key to reconnect with live updates.'}
          </p>
        )}
        {canRetryConnection && (
          <button
            type="button"
            onClick={onRetry}
            className="px-3 py-1 text-xs rounded-full bg-dark-800 border border-dark-700 text-muted-100 hover:bg-dark-700"
          >
            Retry connection
          </button>
        )}
        {!canRetryConnection && !isAuthFailure && (
          <p className="text-xs text-amber-300/90">
            Streaming views will continue via polling when websocket access is unavailable.
          </p>
        )}
        {isAuthFailure && (
          <form onSubmit={handleSubmit} className="w-full flex items-center gap-2 flex-wrap">
            <label className="sr-only" htmlFor={inputId}>
              Websocket API key
            </label>
            <input
              id={inputId}
              name="wsAuthKey"
              type="password"
              value={manualWsApiKey}
              onChange={(event) => setManualWsApiKey(event.target.value)}
              placeholder="Enter websocket API key"
              className="h-8 px-2 bg-dark-900 border border-dark-700 rounded text-xs text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
            <button
              type="submit"
              disabled={!manualWsApiKey.trim()}
              className="px-3 py-1 text-xs rounded-full bg-dark-800 border border-dark-700 text-muted-100 hover:bg-dark-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Connect with API key
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
