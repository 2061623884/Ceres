/**
 * 墨墨售后 — 与 ChatScreen 同结构的玻璃 Grok 面板
 */

import { useState, useEffect, useRef, useCallback, useLayoutEffect, type ReactNode } from 'react'
import { MomoAvatar } from './components/MomoToast'
import { selectMercuryOrder } from './lib/mercury'
import {
  markPromptDisplayed,
  sendOpeningTurnStream,
  streamRoleSwitch,
  type ChatRole,
} from './lib/chatOpening'
import { listOrders, yuan, type Order } from './lib/saleGuide'

interface MercuryMsg {
  id: string
  role: 'user' | 'ai'
  text: string
  suggestions?: string[]
  orderOptions?: Order[]
}

const WELCOME_MSG: MercuryMsg = {
  id: 'welcome',
  role: 'ai',
  text: '您好！我是墨墨 🍞\n订单、物流、退款、退货问题都可以问我～',
  suggestions: ['我想查看我的订单', '帮我查询物流信息', '我想申请退款', '我想申请退货'],
}

const QUICK_SEND_LABELS = ['🚚 查物流', '💰 退款', '🔄 退货']
const ORDER_QUICK_LABEL = '📦 查订单'

function KekeAvatar({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden>
      <ellipse cx="24.5" cy="27.5" rx="13" ry="10.5" fill="#B9DF75" opacity="0.8" />
      <path d="M24 27.6C24.8 31.1 23.8 34.4 21.6 36.2" stroke="#3AA763" strokeWidth="4.2" strokeLinecap="round" />
      <circle cx="20" cy="10.3" r="9.4" fill="#42B46C" />
      <circle cx="10.8" cy="19.4" r="9.5" fill="#42B46C" />
      <circle cx="29.1" cy="19.4" r="9.5" fill="#42B46C" />
      <circle cx="20" cy="28.3" r="9.35" fill="#42B46C" />
      <ellipse cx="20" cy="12.4" rx="5" ry="2.5" fill="#75CB8B" opacity="0.72" />
      <ellipse cx="15.3" cy="23.6" rx="2.6" ry="1.55" fill="#8ED196" opacity="0.85" />
      <ellipse cx="25.8" cy="23.6" rx="2.65" ry="1.55" fill="#8ED196" opacity="0.85" />
      <path d="M15 19.4C16.8 17.7 19.1 17.7 20.7 19.4" stroke="#173A2A" strokeWidth="2" strokeLinecap="round" />
      <ellipse cx="25.7" cy="19.1" rx="2.05" ry="2.55" fill="#173A2A" />
      <circle cx="26.4" cy="18.25" r="0.7" fill="white" />
      <path d="M16.9 24.1C19.3 27.2 22.9 27.3 25.2 24.1" stroke="#173A2A" strokeWidth="2.05" strokeLinecap="round" />
    </svg>
  )
}

function SheetCloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      onClick={onClose}
      aria-label="关闭"
      className="absolute right-3 top-3 z-10 grid h-[22px] w-[22px] place-items-center rounded-full bg-black/[0.06] text-black/40 backdrop-blur-sm transition hover:bg-black/[0.09]"
    >
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
        <path d="M18 6L6 18M6 6l12 12" />
      </svg>
    </button>
  )
}

function MercuryFloatingSheet({
  children,
  onClose,
  panelRef,
  morphOrigin,
  closing,
  onMorphEnd,
}: {
  children: ReactNode
  onClose: () => void
  panelRef: React.RefObject<HTMLDivElement | null>
  morphOrigin: string
  closing: boolean
  onMorphEnd: () => void
}) {
  return (
    <div className="absolute inset-x-0 bottom-full z-10 mb-2 px-4">
      <div
        ref={panelRef}
        className={`guide-glass-surface relative flex max-h-[min(52vh,320px)] flex-col overflow-hidden rounded-[24px] ${
          closing ? 'guide-sheet-morph-out' : 'guide-sheet-morph-in'
        }`}
        style={{ transformOrigin: morphOrigin }}
        onAnimationEnd={(e) => {
          if (e.target !== e.currentTarget || !closing) return
          onMorphEnd()
        }}
      >
        <SheetCloseButton onClose={onClose} />
        {children}
      </div>
    </div>
  )
}

function formatText(text: string) {
  return text.split('\n').map((line, i, arr) => (
    <span key={i}>
      {line}
      {i < arr.length - 1 && <br />}
    </span>
  ))
}

interface MercuryChatProps {
  visible?: boolean
  active?: boolean
  openingId?: string | null
  mercurySessionId?: string | null
  liveHandoff?: { role: ChatRole; user: string; assistant: string; typing: boolean } | null
  onSwitchToKeke?: () => void
  switchBusy?: boolean
  onHandoffSwitch?: (
    body: { accept: boolean; target_role: ChatRole; handoff_id: string },
    userMessage: string,
    guideCallbacks: Parameters<typeof streamRoleSwitch>[2],
  ) => Promise<void>
}

export function MercuryChat({
  visible = true,
  active = true,
  openingId = null,
  mercurySessionId = null,
  liveHandoff = null,
  onSwitchToKeke,
  switchBusy = false,
  onHandoffSwitch,
}: MercuryChatProps) {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null)
  const [msgs, setMsgs] = useState<MercuryMsg[]>([WELCOME_MSG])
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const [restoring, setRestoring] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [orderSheetOpen, setOrderSheetOpen] = useState(false)
  const [orderSheetClosing, setOrderSheetClosing] = useState(false)
  const [sheetMorphOrigin, setSheetMorphOrigin] = useState('50% 100%')
  const [pickerOrders, setPickerOrders] = useState<Order[]>([])
  const [orderPickerLoading, setOrderPickerLoading] = useState(false)
  const [orderPickerError, setOrderPickerError] = useState<string | null>(null)
  const [selectingOrderId, setSelectingOrderId] = useState<string | null>(null)
  const [pendingHandoff, setPendingHandoff] = useState<{
    handoffId: string
    targetRole: ChatRole
    promptMode: string
  } | null>(null)
  const promptMarkedRef = useRef<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const orderCapsuleRef = useRef<HTMLButtonElement>(null)
  const orderSheetPanelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (visible && active) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [msgs, typing, visible, active, liveHandoff])

  useEffect(() => {
    if (!mercurySessionId) {
      setRestoring(true)
      return
    }
    setSessionId(mercurySessionId)
    setRestoring(false)
    setError(null)
  }, [mercurySessionId])

  useEffect(() => {
    if (!openingId || !pendingHandoff || pendingHandoff.promptMode !== 'automatic') return
    if (promptMarkedRef.current === pendingHandoff.handoffId) return
    promptMarkedRef.current = pendingHandoff.handoffId
    markPromptDisplayed(openingId, pendingHandoff.handoffId).catch(() => {})
  }, [openingId, pendingHandoff])

  const measureOrderSheetOrigin = useCallback(() => {
    const capsule = orderCapsuleRef.current
    const panel = orderSheetPanelRef.current
    if (!capsule || !panel) return
    const cap = capsule.getBoundingClientRect()
    const pan = panel.getBoundingClientRect()
    const x = cap.left + cap.width / 2 - pan.left
    const y = cap.top + cap.height / 2 - pan.top
    setSheetMorphOrigin(`${x}px ${y}px`)
  }, [])

  useLayoutEffect(() => {
    if (!orderSheetOpen || orderSheetClosing) return
    measureOrderSheetOrigin()
  }, [orderSheetOpen, orderSheetClosing, measureOrderSheetOrigin, pickerOrders.length])

  const closeOrderSheet = useCallback(() => {
    if (!orderSheetOpen) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setOrderSheetOpen(false)
      setOrderSheetClosing(false)
      return
    }
    setOrderSheetClosing(true)
  }, [orderSheetOpen])

  const handleOrderSheetMorphEnd = useCallback(() => {
    setOrderSheetOpen(false)
    setOrderSheetClosing(false)
  }, [])

  const loadOrderList = useCallback(async () => {
    setOrderPickerLoading(true)
    setOrderPickerError(null)
    try {
      const result = await listOrders()
      setPickerOrders(result.items)
    } catch (e) {
      setOrderPickerError(e instanceof Error ? e.message : '订单加载失败')
    } finally {
      setOrderPickerLoading(false)
    }
  }, [])

  const openOrderSheet = useCallback(async (toggleIfOpen = true) => {
    if (toggleIfOpen && orderSheetOpen && !orderSheetClosing) {
      closeOrderSheet()
      return
    }
    setOrderSheetClosing(false)
    setOrderSheetOpen(true)
    await loadOrderList()
  }, [orderSheetOpen, orderSheetClosing, closeOrderSheet, loadOrderList])

  const send = useCallback(
    async (text: string) => {
      if (!text.trim() || !sessionId || !openingId || typing || restoring || selectingOrderId) return
      const trimmed = text.trim()
      setMsgs((p) => [...p, { id: `u-${Date.now()}`, role: 'user', text: trimmed }])
      setInput('')
      setTyping(true)
      setError(null)
      setPendingHandoff(null)

      const assistantId = `a-${Date.now()}`
      let assistantText = ''
      setMsgs((p) => [...p, { id: assistantId, role: 'ai', text: '' }])

      try {
        const requestId = `req_${Date.now()}`
        const result = await sendOpeningTurnStream(
          openingId,
          'momo',
          trimmed,
          requestId,
          null,
          0,
          null,
          undefined,
          {
            onMercuryDelta: (chunk) => {
              assistantText += chunk
              setMsgs((p) => p.map((m) => (m.id === assistantId ? { ...m, text: assistantText } : m)))
            },
            onMercuryOrders: (orders) => {
              setMsgs((p) =>
                p.map((m) => (m.id === assistantId ? { ...m, orderOptions: orders as Order[] } : m)),
              )
            },
            onMercuryCompleted: (finalText) => {
              assistantText = finalText || assistantText
              setMsgs((p) =>
                p.map((m) => (m.id === assistantId ? { ...m, text: finalText || assistantText } : m)),
              )
            },
            onRoutePrompt: (message, route) => {
              assistantText = message
              setMsgs((p) => p.map((m) => (m.id === assistantId ? { ...m, text: message } : m)))
              if (route.handoff_id && route.target_role) {
                setPendingHandoff({
                  handoffId: route.handoff_id,
                  targetRole: route.target_role,
                  promptMode: route.prompt_mode ?? 'automatic',
                })
              }
            },
            onError: (event) => {
              const message = String(event.payload?.message ?? '服务暂时不可用')
              setError(message)
            },
          },
          undefined,
          selectedOrder?.order_id ?? null,
        )

        if (result.kind === 'business') {
          const finalText = result.turn.message || assistantText
          setMsgs((p) =>
            p.map((m) => (m.id === assistantId ? { ...m, text: finalText || assistantText } : m)),
          )
        }
      } catch (e) {
        const message = e instanceof Error ? e.message : '发送失败'
        setError(message)
        setMsgs((p) =>
          p.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  text: m.text.trim()
                    ? m.text
                    : '抱歉，没有收到回复，请稍后再试。',
                }
              : m,
          ),
        )
      } finally {
        setTyping(false)
      }
    },
    [sessionId, openingId, typing, restoring, selectingOrderId, selectedOrder?.order_id],
  )

  async function respondHandoff(accept: boolean) {
    if (!pendingHandoff || !openingId) return
    const lastUser = [...msgs].reverse().find((m) => m.role === 'user')
    const userMessage = lastUser?.text ?? ''
    const { handoffId, targetRole } = pendingHandoff
    setPendingHandoff(null)
    if (!accept) {
      try {
        await streamRoleSwitch(openingId, {
          accept: false,
          target_role: targetRole,
          handoff_id: handoffId,
        })
      } catch (e) {
        setError(e instanceof Error ? e.message : '操作失败')
      }
      return
    }
    if (!onHandoffSwitch) return
    setTyping(true)
    try {
      await onHandoffSwitch(
        { accept: true, target_role: targetRole, handoff_id: handoffId },
        userMessage,
        {
          onMercuryDelta: () => {},
          onMercuryCompleted: () => {},
        },
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : '切换失败')
    } finally {
      setTyping(false)
    }
  }

  async function selectOrder(orderId: string) {
    if (!sessionId || selectingOrderId || restoring || typing) return
    setSelectingOrderId(orderId)
    setError(null)
    try {
      const result = await selectMercuryOrder(sessionId, orderId)
      const order = result.order
      setSelectedOrder(order)
      closeOrderSheet()
      const items = order.items.map((item) => `${item.product_name} × ${item.quantity}`).join('、')
      setMsgs((p) => [...p, {
        id: `selected-${Date.now()}`,
        role: 'ai',
        text: `已选中订单 ${order.order_id}：${items}，合计 ${yuan(order.total_fen)}。你可以继续咨询这笔订单。`,
      }])
    } catch (e) {
      setError(e instanceof Error ? e.message : '选单失败')
    } finally {
      setSelectingOrderId(null)
    }
  }

  async function handleNewChat() {
    setMsgs([WELCOME_MSG])
    setSelectedOrder(null)
    setOrderSheetOpen(false)
    setOrderSheetClosing(false)
    setOrderPickerError(null)
    setPendingHandoff(null)
  }

  if (!visible) return null

  return (
    <section
      className={`guide-chat-panel chat-panel-enter relative flex h-[min(71vh,650px)] max-h-full w-full min-h-[min(500px,71vh)] flex-shrink-0 flex-col overflow-hidden rounded-t-[38px] font-sans ${
        active ? '' : 'hidden'
      }`}
      aria-hidden={!active}
    >
      <div
        className={`guide-chat-scroll scrollbar-hide relative z-0 min-h-0 flex-1 space-y-5 overflow-y-auto px-6 pb-5 ${
          typing ? 'pt-[7.75rem]' : 'pt-[6.75rem]'
        }`}
      >
        {restoring && <p className="text-center text-sm text-black/40">正在连接墨墨…</p>}
        {error && <p className="text-center text-sm text-red-600">{error}</p>}
        {msgs.map((msg) => (
          <div key={msg.id} className={`flex items-end gap-2.5 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
            {msg.role === 'ai' && <MomoAvatar size={26} />}
            <div className={`flex max-w-[82%] flex-col gap-2.5 ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
              {msg.text ? (
                <div
                  className={`px-4 py-3 text-[13px] font-medium leading-[1.7] tracking-[-0.015em] ${
                    msg.role === 'ai' ? 'guide-glass-bubble' : 'guide-glass-bubble-user'
                  }`}
                  style={{
                    borderRadius: msg.role === 'user' ? '24px 24px 8px 24px' : '24px 24px 24px 8px',
                    color: msg.role === 'user' ? '#fff' : '#292825',
                  }}
                >
                  {formatText(msg.text)}
                </div>
              ) : msg.role === 'ai' && typing && msg.id === msgs[msgs.length - 1]?.id ? (
                <div
                  className="guide-glass-bubble ai-loading-bubble px-4 py-3 text-[13px] font-medium leading-[1.7] tracking-[-0.015em]"
                  style={{ borderRadius: '24px 24px 24px 8px', color: '#292825' }}
                >
                  <span className="ai-loading-ellipsis" aria-label="墨墨正在输入">
                    <span className="ai-loading-ellipsis__dot" aria-hidden="true">.</span>
                    <span className="ai-loading-ellipsis__dot" aria-hidden="true">.</span>
                    <span className="ai-loading-ellipsis__dot" aria-hidden="true">.</span>
                  </span>
                </div>
              ) : null}
              {msg.orderOptions && msg.role === 'ai' && (
                <div className="space-y-2">
                  {msg.orderOptions.map((order) => (
                    <button
                      key={order.order_id}
                      type="button"
                      onClick={() => selectOrder(order.order_id)}
                      disabled={typing || Boolean(selectingOrderId)}
                      className="w-full rounded-[18px] bg-[#f2f1ed] px-4 py-3 text-left text-[11px] transition active:scale-[.99] disabled:opacity-55"
                    >
                      <span className="font-semibold text-[#252421]">{order.order_id}</span>
                      <span className="mt-1 block text-black/45">
                        {order.items.map((item) => `${item.product_name} × ${item.quantity}`).join(' · ')}
                      </span>
                    </button>
                  ))}
                </div>
              )}
              {msg.suggestions && msg.role === 'ai' && !typing && (
                <div className="flex w-full flex-col gap-1.5">
                  {msg.suggestions.map((s, i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => send(s)}
                      className="guide-glass-chip rounded-full px-4 py-2.5 text-left text-[12px] font-medium text-black/55 transition active:scale-[.98]"
                    >
                      <span className="mr-2 text-[10px] font-semibold text-[#d79b58]">✦</span>
                      {s}
                    </button>
                  ))}
                </div>
              )}
              {pendingHandoff && msg.role === 'ai' && msg.id === msgs[msgs.length - 1]?.id && !typing && (
                <div className="flex flex-wrap gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => respondHandoff(true)}
                    className="rounded-full bg-[#eac867] px-4 py-2 text-[12px] font-semibold text-[#4E3D12] active:scale-[.98]"
                  >
                    找可可
                  </button>
                  <button
                    type="button"
                    onClick={() => respondHandoff(false)}
                    className="guide-glass-chip rounded-full px-4 py-2 text-[12px] font-medium text-black/55 active:scale-[.98]"
                  >
                    继续聊
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
        {liveHandoff?.role === 'momo' && (
          <div className="space-y-5">
            <div className="flex items-end justify-end gap-2.5">
              <div
                className="guide-glass-bubble-user max-w-[82%] px-4 py-3 text-[13px] font-medium leading-[1.7]"
                style={{ borderRadius: '24px 24px 8px 24px', color: '#fff' }}
              >
                {liveHandoff.user}
              </div>
            </div>
            <div className="flex items-end gap-2.5">
              <MomoAvatar size={26} />
              <div
                className="guide-glass-bubble max-w-[82%] px-4 py-3 text-[13px] font-medium leading-[1.7] text-[#292825]"
                style={{ borderRadius: '24px 24px 24px 8px' }}
              >
                {liveHandoff.assistant}
                {liveHandoff.typing && !liveHandoff.assistant && (
                  <span className="text-black/35">…</span>
                )}
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="pointer-events-none absolute inset-x-0 top-0 z-20 px-6 pt-3 pb-3">
        <div className="flex justify-center" aria-hidden="true">
          <span className="h-1 w-10 rounded-full bg-black/[.12]" />
        </div>
        <div className="relative mt-2 flex min-h-[44px] items-center justify-center">
          <button
            type="button"
            onClick={handleNewChat}
            disabled={Boolean(selectingOrderId)}
            className="guide-glass-icon-btn pointer-events-auto absolute right-5 top-1/2 z-10 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full text-black/45 transition hover:bg-white/70 active:scale-95"
            aria-label="发起新对话"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
          <div className="guide-glass-header-pill pointer-events-auto relative z-10 inline-flex items-center gap-2.5 rounded-full py-2 pl-2 pr-5">
            <MomoAvatar size={36} animated />
            <p className="text-[15px] font-semibold tracking-[-0.04em] text-[#191817]">墨墨</p>
          </div>
        </div>
        {typing && (
          <p className="mt-1 text-center text-[10px] text-black/40">墨墨正在输入…</p>
        )}
      </div>

      <div className="relative z-10 flex-shrink-0 px-5 pb-4 pt-2">
        {selectedOrder && (
          <div className="mb-2 flex items-center justify-between px-3 text-[10px] text-black/45">
            <span>当前咨询订单：<strong className="font-semibold text-[#252421]">{selectedOrder.order_id}</strong></span>
            <button
              type="button"
              onClick={() => openOrderSheet(false)}
              disabled={typing || restoring || Boolean(selectingOrderId)}
              className="font-medium text-[#54755a] disabled:opacity-50"
            >更换</button>
          </div>
        )}
        {(orderSheetOpen || orderSheetClosing) && (
          <MercuryFloatingSheet
            panelRef={orderSheetPanelRef}
            morphOrigin={sheetMorphOrigin}
            closing={orderSheetClosing}
            onMorphEnd={handleOrderSheetMorphEnd}
            onClose={closeOrderSheet}
          >
            <p className="px-4 pb-2 pt-4 text-[13px] font-semibold text-[#1d1c1a]">选择要咨询的订单</p>
            <div
              className={`scrollbar-hide min-h-0 space-y-2 px-4 pb-4 ${
                pickerOrders.length > 2 ? 'guide-sheet-scroll max-h-[148px] overflow-y-auto pr-1.5' : ''
              }`}
            >
              {orderPickerLoading && <p className="py-6 text-center text-[11px] text-black/40">正在加载订单…</p>}
              {orderPickerError && <p className="py-6 text-center text-[11px] text-red-600">订单加载失败：{orderPickerError}</p>}
              {!orderPickerLoading && !orderPickerError && pickerOrders.length === 0 && (
                <p className="py-6 text-center text-[11px] text-black/40">还没有可咨询的订单</p>
              )}
              {!orderPickerLoading && !orderPickerError && pickerOrders.map((order) => (
                <button
                  key={order.order_id}
                  type="button"
                  onClick={() => selectOrder(order.order_id)}
                  disabled={typing || Boolean(selectingOrderId)}
                  className="w-full rounded-[18px] bg-[#f2f1ed] px-4 py-3 text-left transition active:scale-[.99] disabled:opacity-55"
                >
                  <span className="flex items-center justify-between gap-3">
                    <span className="text-[12px] font-semibold text-[#252421]">{order.order_id}</span>
                    <span className="text-[10px] text-black/38">{order.status === 'paid' ? '模拟下单，未发货' : order.status}</span>
                  </span>
                  <span className="mt-1 block text-[10px] leading-relaxed text-black/45">
                    {order.items.map((item) => `${item.product_name} × ${item.quantity}`).join(' · ')}
                  </span>
                  <span className="mt-1 block text-[10px] font-medium text-black/55">合计 {yuan(order.total_fen)}</span>
                </button>
              ))}
            </div>
          </MercuryFloatingSheet>
        )}
        <div className="mb-2.5 flex items-stretch gap-2">
          <div className="scrollbar-hide min-w-0 flex-1 overflow-x-auto">
            <div className="flex w-max gap-2 pr-1">
              <button
                type="button"
                ref={orderCapsuleRef}
                onClick={() => openOrderSheet()}
                disabled={typing || restoring || Boolean(selectingOrderId)}
                className={`inline-flex shrink-0 items-center rounded-full px-3 py-2.5 text-[11px] font-medium transition-colors disabled:opacity-40 ${
                  orderSheetOpen && !orderSheetClosing
                    ? 'guide-glass-surface text-[#1d1c1a]'
                    : 'guide-glass-chip text-black/55'
                }`}
              >
                {ORDER_QUICK_LABEL}
              </button>
              {QUICK_SEND_LABELS.map((label) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => send(label.replace(/^[^\s]+\s/, ''))}
                  disabled={typing || restoring || Boolean(selectingOrderId) || !openingId}
                  className="guide-glass-chip inline-flex shrink-0 items-center rounded-full px-3 py-2.5 text-[11px] font-medium text-black/55 disabled:opacity-40"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <button
            type="button"
            disabled={switchBusy || !onSwitchToKeke}
            onClick={() => onSwitchToKeke?.()}
            className="inline-flex shrink-0 items-center gap-1.5 overflow-visible rounded-full border border-[#b8ddb8]/80 bg-[#e8f5e6] px-3 py-2.5 text-[13px] font-semibold text-[#2d5c3a] shadow-[inset_0_1px_0_rgba(255,255,255,.85)] transition active:scale-[.98] disabled:opacity-45"
          >
            <span className="grid shrink-0 place-items-center overflow-visible">
              <KekeAvatar size={20} />
            </span>
            继续逛逛
          </button>
        </div>
        <div className="guide-glass-surface flex items-center gap-2 rounded-[28px] px-4 py-2.5">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') send(input)
            }}
            placeholder="问问墨墨吧…"
            disabled={restoring || typing || Boolean(selectingOrderId) || !openingId}
            className="min-w-0 flex-1 bg-transparent text-[13px] font-medium text-[#1d1c1a] outline-none placeholder:text-black/30"
          />
          <button
            type="button"
            onClick={() => send(input)}
            disabled={!input.trim() || !sessionId || !openingId || typing || restoring || Boolean(selectingOrderId)}
            className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full transition-all active:scale-90 ${
              input.trim() && !typing && !restoring && !selectingOrderId && openingId ? 'bg-[#171716]' : 'bg-[#eeece7]'
            }`}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="white">
              <path d="M2 21L23 12 2 3v7l15 2-15 2z" />
            </svg>
          </button>
        </div>
      </div>
    </section>
  )
}
