import { useEffect, useRef, useCallback } from 'react'
import { message } from 'antd'
import { useStore } from '../stores/useStore'
import { getBugList, getCurrentExecution, sessionId } from '../api/axios'
import { autoSaveCurrentExecution } from '../utils/executionDraft'
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

/** 自动保存日志草稿后给出提示（同一次执行只提示一次） */
const notifyDraftAutoSaved = (draft: unknown) => {
  if (!draft) return
  message.success({
    content: '执行日志已自动保存到日志草稿箱',
    key: 'execution-draft-autosave',
  })
}

/** 执行结束/停止后刷新 BugList 页，保持与当前工作簿数据同步 */
const refreshBugList = async () => {
  try {
    const res = await getBugList()
    useStore.getState().setBugList(res.data.bug_sheet, res.data.bug_list)
  } catch {
    // BugList 刷新失败不影响执行状态收尾
  }
}

/**
 * 用后端任务状态校准前端运行态。
 *
 * 断线重连、页面刷新或在执行中切换页面后，可能错过 execution_finished；
 * 此时若后端任务已结束，必须把界面从“执行中”复位，否则会一直卡住。
 */
const reconcileExecutionState = async () => {
  try {
    const res = await getCurrentExecution()
    const task = res.data
    const active = task.status === 'running' || task.status === 'starting'
    const store = useStore.getState()
    store.setIsRunning(active)
    if (!active) store.setProgress(null)
  } catch {
    // 校准失败不影响正常消息处理
  }
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
      case 'case_start':
        store.setCurrentCaseInfo(data.case)
        store.startBoardTerminal({
          caseId: data.case.case_id,
          caseKey: data.case.case_key,
          terminals: data.case.terminals || [],
        })
        break
      case 'terminal_log':
        store.appendTerminalLog({
          caseId: data.case_id,
          caseKey: data.case_key,
          terminal: data.terminal,
          chunk: data.chunk,
        })
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
        // 执行结束自动保存日志草稿：下载结果时日志会变成图片，文本先存到草稿箱
        void autoSaveCurrentExecution().then(notifyDraftAutoSaved)
        void refreshBugList()
        break
      case 'execution_stopped':
        store.setIsRunning(false)
        store.setProgress(null)
        store.addLog({
          level: 'warning',
          message: data.message,
          timestamp: Date.now(),
        })
        void autoSaveCurrentExecution().then(notifyDraftAutoSaved)
        void refreshBugList()
        break
      case 'manual_confirm_request':
        store.setConfirmRequest(data)
        break
      case 'download_progress':
        store.setDownloadProgress(data)
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
      // 连接（重连）成功后校准运行态，补齐断线期间错过的结束消息
      void reconcileExecutionState()
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
    // 共享连接可能被其它实例重建，这里以模块级 sharedSocket 为准，
    // 避免本实例的 wsRef 仍指向已关闭的旧连接导致指令发不出去。
    const socket = sharedSocket ?? wsRef.current
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(msg))
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
      const localSocket = wsRef.current
      wsRef.current = null
      // 仍有其它页面订阅时保持共享连接。
      // 否则在执行中切到「板端日志」页会关闭 WS，导致收不到
      // case_complete / execution_finished，界面一直停在“执行中”。
      if (subscriberCount > 0) return
      clearReconnectSchedule()
      if (localSocket) {
        localSocket.close()
      }
      if (sharedSocket) {
        sharedSocket = null
      }
    }
  }, [connect, clearReconnectSchedule])

  return { connect, send, stopExecution, confirmResponse }
}
