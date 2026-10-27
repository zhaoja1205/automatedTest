import { useEffect, useRef, useCallback } from 'react'
import { useStore } from '../stores/useStore'
import { sessionId } from '../api/axios'
import type {
  ConfirmResponseMessage,
  StopExecutionMessage,
  WsIncomingMessage,
  WsOutgoingMessage,
} from '../types'

let sharedSocket: WebSocket | null = null
let subscriberCount = 0
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 15000

const buildWebSocketUrl = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws?session_id=${sessionId}`
}

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const prevReconnectDelayMsRef = useRef(RECONNECT_BASE_MS)
  // Mutable ref to avoid circular dependency between scheduleReconnect and connect
  const connectFnRef = useRef<(() => void) | null>(null)

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimer) return // already scheduled
    const delay = Math.min(prevReconnectDelayMsRef.current, RECONNECT_MAX_MS)
    prevReconnectDelayMsRef.current = Math.min(delay * 2, RECONNECT_MAX_MS)
    reconnectAttemptsRef.current += 1
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connectFnRef.current?.()
    }, delay)
  }, [])

  const clearReconnectSchedule = useCallback(() => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }, [])

  const handleMessage = useCallback((data: WsIncomingMessage) => {
    const store = useStore.getState()

    switch (data.type) {
      case 'log':
        store.addLog(data)
        break
      case 'progress':
        store.setProgress(data)
        break
      case 'case_complete':
        store.updateCaseStatus(
          data.case_key || data.case_id,
          data.status,
          data.actual_result,
          data.log_file,
          data.remarks,
        )
        if (data.reason) {
          store.addLog({
            level: data.status === 'Fail' ? 'error' : 'info',
            message: `[${data.case_id}] ${data.reason}`,
            timestamp: Date.now(),
          })
        }
        break
      case 'execution_finished':
        store.setIsRunning(false)
        store.setProgress(null)
        break
      case 'execution_stopped':
        store.setIsRunning(false)
        store.setProgress(null)
        store.addLog({
          level: 'warning',
          message: data.message,
          timestamp: Date.now(),
        })
        break
      case 'manual_confirm_request':
        store.setConfirmRequest(data)
        break
      case 'ai_parse_progress':
        store.setAIParseProgress({
          current: data.current,
          total: data.total,
          status: 'parsing',
          message: data.message,
          success: 0,
          failed: 0,
        })
        break
      case 'ai_parse_case_done':
        store.addAIParsedCase(data.case_key)
        break
      case 'ai_parse_complete':
        store.setAIParseProgress({
          current: data.total,
          total: data.total,
          status: data.message.includes('中断') ? 'interrupted' : 'done',
          message: data.message,
          success: data.success,
          failed: data.failed,
        })
        // 30 秒后自动清除完成状态（给用户足够时间看到结果）
        setTimeout(() => {
          const s = useStore.getState()
          if (s.aiParseProgress?.status === 'done' || s.aiParseProgress?.status === 'interrupted') {
            s.setAIParseProgress(null)
          }
        }, 30000)
        break
    }
  }, [])

  const connect = useCallback(() => {
    const store = useStore.getState()

    if (sharedSocket && (sharedSocket.readyState === WebSocket.OPEN || sharedSocket.readyState === WebSocket.CONNECTING)) {
      wsRef.current = sharedSocket
      if (sharedSocket.readyState === WebSocket.OPEN) {
        store.setIsConnected(true)
      }
      return
    }

    const ws = new WebSocket(buildWebSocketUrl())
    sharedSocket = ws
    wsRef.current = ws

    ws.onopen = () => {
      if (wsRef.current !== ws) {
        return
      }
      store.setIsConnected(true)
      store.addLog({ level: 'info', message: 'WebSocket 已连接', timestamp: Date.now() })
      // Reset reconnect state on successful connection
      reconnectAttemptsRef.current = 0
      prevReconnectDelayMsRef.current = RECONNECT_BASE_MS
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      handleMessage(data)
    }

    ws.onclose = (event) => {
      if (wsRef.current !== ws && sharedSocket !== ws) {
        return
      }
      if (sharedSocket === ws) {
        sharedSocket = null
      }
      store.setIsConnected(false)

      // Don't reconnect during normal unmount (subscriberCount === 0 handled in effect cleanup)
      // Also skip reconnect if the close was intentional (code 1000 Normal Closure)
      if (event.code === 1000 || event.code === 1001) {
        return
      }

      const attempt = reconnectAttemptsRef.current
      store.addLog({
        level: 'warning',
        message: `WebSocket 已断开 (尝试#${attempt + 1} 重连)...`,
        timestamp: Date.now(),
      })
      scheduleReconnect()
    }

    ws.onerror = () => {
      if (wsRef.current !== ws) {
        return
      }
      store.addLog({ level: 'error', message: 'WebSocket 连接错误', timestamp: Date.now() })
    }
  }, [handleMessage, scheduleReconnect])

  // Store connect in ref so scheduleReconnect can call it without circular deps
  connectFnRef.current = connect

  const send = useCallback((msg: WsOutgoingMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  const stopExecution = useCallback(() => {
    const message: StopExecutionMessage = { type: 'stop_execution' }
    send(message)
  }, [send])

  const confirmResponse = useCallback((confirmId: string, result: boolean) => {
    const store = useStore.getState()
    const message: ConfirmResponseMessage = {
      type: 'confirm_response',
      confirm_id: confirmId,
      result,
    }
    send(message)
    store.setConfirmRequest(null)
  }, [send])

  useEffect(() => {
    subscriberCount += 1
    connect()
    return () => {
      subscriberCount = Math.max(0, subscriberCount - 1)
      clearReconnectSchedule()
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      if (sharedSocket) {
        sharedSocket = null
      }
    }
  }, [connect, clearReconnectSchedule])

  return { connect, send, stopExecution, confirmResponse }
}
