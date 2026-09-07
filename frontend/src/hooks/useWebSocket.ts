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

const buildWebSocketUrl = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws?session_id=${sessionId}`
}

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)

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
        store.updateCaseStatus(data.case_key || data.case_id, data.status, data.actual_result)
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
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      handleMessage(data)
    }

    ws.onclose = () => {
      if (wsRef.current !== ws && sharedSocket !== ws) {
        return
      }
      if (sharedSocket === ws) {
        sharedSocket = null
      }
      store.setIsConnected(false)
      store.addLog({ level: 'warning', message: 'WebSocket 已断开', timestamp: Date.now() })
    }

    ws.onerror = () => {
      if (wsRef.current !== ws) {
        return
      }
      store.addLog({ level: 'error', message: 'WebSocket 连接错误', timestamp: Date.now() })
    }
  }, [handleMessage])

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
      if (subscriberCount === 0 && wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
        sharedSocket = null
      }
    }
  }, [connect])

  return { connect, send, stopExecution, confirmResponse }
}