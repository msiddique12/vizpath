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

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const configuredBase = import.meta.env.VITE_WS_BASE_URL as string | undefined
    const baseUrl = configuredBase?.trim()
      ? configuredBase.trim()
      : window.location.origin.replace(/^http/, 'ws')
    const url = new URL('/ws/traces', baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`).toString()

    try {
      const ws = new WebSocket(url)

      ws.onopen = () => {
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

      ws.onclose = () => {
        setConnected(false)
        onDisconnect?.()
        reconnectTimeoutRef.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => {
        ws.close()
      }

      wsRef.current = ws
    } catch {
      reconnectTimeoutRef.current = setTimeout(connect, 3000)
    }
  }, [onMessage, onConnect, onDisconnect])

  useEffect(() => {
    connect()

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      wsRef.current?.close()
    }
  }, [connect])

  return { connected }
}
