import { useEffect, useRef, useCallback, useState } from 'react'

interface WebSocketMessage {
  type: string
  trace_id?: string
  span_count?: number
}

interface UseWebSocketOptions {
  onMessage?: (message: WebSocketMessage) => void
  onConnect?: () => void
  onDisconnect?: () => void
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const { onMessage, onConnect, onDisconnect } = options
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const reconnectAttemptRef = useRef(0)
  const shouldReconnectRef = useRef(true)

  const resolveWebSocketUrl = () => {
    const configuredBase = import.meta.env.VITE_WS_BASE_URL as string | undefined
    const configuredApiKey = import.meta.env.VITE_VIZPATH_API_KEY as string | undefined
    const baseUrl = configuredBase?.trim()
      ? configuredBase.trim()
      : window.location.origin.replace(/^http/, 'ws')
    const url = new URL('/ws/traces', baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`)

    const apiKey = configuredApiKey?.trim()
    if (apiKey) {
      url.searchParams.set('api_key', apiKey)
    }

    return url.toString()
  }

  const connect = useCallback(() => {
    shouldReconnectRef.current = true
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return
    }

    const url = resolveWebSocketUrl()

    try {
      const ws = new WebSocket(url)

      ws.onopen = () => {
        reconnectAttemptRef.current = 0
        setConnected(true)
        onConnect?.()
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'ping') {
            ws.send('pong')
            return
          }
          onMessage?.(data)
        } catch {
          // Ignore non-JSON messages
        }
      }

      ws.onclose = (event) => {
        wsRef.current = null
        setConnected(false)
        onDisconnect?.()

        if (!shouldReconnectRef.current) {
          return
        }

        if (event.code === 4001) {
          return
        }

        if (reconnectAttemptRef.current >= 0) {
          reconnectAttemptRef.current += 1
          const delay = Math.min(1000 * 2 ** Math.min(reconnectAttemptRef.current, 5), 30_000)
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, delay)
        }
      }

      ws.onerror = () => {
        ws.close()
      }

      wsRef.current = ws
    } catch {
      reconnectTimeoutRef.current = setTimeout(connect, 3000)
    }
  }, [onMessage, onConnect, onDisconnect])

  const resetConnection = useCallback(() => {
    shouldReconnectRef.current = false
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = undefined
    }

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  useEffect(() => {
    connect()

    return () => {
      resetConnection()
    }
  }, [connect, resetConnection])

  return { connected }
}
