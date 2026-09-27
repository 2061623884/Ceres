/**
 * MercuryChat - 墨墨售后客服聊天界面
 * 完全复制 ChatScreen 的交互模式
 */

import { useState, useEffect, useRef } from 'react'
import { MercuryMascot, MercuryAvatar } from './components/MercuryMascot'
import { createMercurySession, sendMercuryTurn } from './lib/mercury'

interface MercuryMsg {
  id: string
  role: 'user' | 'ai'
  text: string
}

const WELCOME_MSG: MercuryMsg = {
  id: 'welcome',
  role: 'ai',
  text: '您好!我是墨墨,您的专属售后客服 🍞\n订单、物流、退款、退货问题都可以问我~'
}

const QUICK_ACTIONS = [
  { id: 'orders', label: '📦 查看订单', prompt: '我想查看我的订单' },
  { id: 'delivery', label: '🚚 查询物流', prompt: '帮我查询物流信息' },
  { id: 'refund', label: '💰 申请退款', prompt: '我想申请退款' },
  { id: 'return', label: '🔄 申请退货', prompt: '我想申请退货' }
]

interface MercuryChatProps {
  prefilledOrder?: string
}

export function MercuryChat({ prefilledOrder }: MercuryChatProps) {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [msgs, setMsgs] = useState<MercuryMsg[]>([WELCOME_MSG])
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const [mood, setMood] = useState<'cheerful' | 'attentive' | 'helpful' | 'apologetic'>('cheerful')
  const scrollRef = useRef<HTMLDivElement>(null)

  // 初始化会话
  useEffect(() => {
    const initSession = async () => {
      try {
        const sid = await createMercurySession()
        setSessionId(sid)
      } catch (error) {
        console.error('Failed to create Mercury session:', error)
      }
    }
    initSession()
  }, [])

  // 预填订单号自动发送
  useEffect(() => {
    if (prefilledOrder && sessionId && msgs.length === 1) {
      handleSend(`关于订单 ${prefilledOrder} 我想咨询...`)
    }
  }, [prefilledOrder, sessionId])

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [msgs, typing])

  const handleSend = async (text?: string) => {
    const message = text || input.trim()
    if (!message || !sessionId) return

    // 添加用户消息
    const userMsg: MercuryMsg = {
      id: `u_${Date.now()}`,
      role: 'user',
      text: message
    }
    setMsgs(prev => [...prev, userMsg])
    setInput('')
    setTyping(true)
    setMood('attentive')

    // 准备 AI 消息
    const aiMsgId = `a_${Date.now()}`
    let aiText = ''

    try {
      await sendMercuryTurn(sessionId, message, {
        onAnswerDelta: (chunk) => {
          aiText += chunk
          setMsgs(prev => {
            const existing = prev.find(m => m.id === aiMsgId)
            if (existing) {
              return prev.map(m => m.id === aiMsgId ? { ...m, text: aiText } : m)
            } else {
              return [...prev, { id: aiMsgId, role: 'ai', text: aiText }]
            }
          })
        },
        onCompleted: (finalText) => {
          setTyping(false)
          setMood('helpful')
          setMsgs(prev =>
            prev.map(m => m.id === aiMsgId ? { ...m, text: finalText } : m)
          )
        },
        onError: (err) => {
          console.error('Mercury error:', err)
          setTyping(false)
          setMood('apologetic')
          setMsgs(prev => [...prev, {
            id: aiMsgId,
            role: 'ai',
            text: '抱歉,服务暂时不可用,请稍后再试。'
          }])
        }
      })
    } catch (error) {
      console.error('Failed to send message:', error)
      setTyping(false)
      setMood('apologetic')
      setMsgs(prev => [...prev, {
        id: aiMsgId,
        role: 'ai',
        text: '抱歉,服务暂时不可用,请稍后再试。'
      }])
    }
  }

  return (
    <div
      className="mercury-chat fixed inset-x-0 bottom-0 z-40 flex flex-col bg-[#f8f9fc] rounded-t-[38px] shadow-[0_-20px_60px_rgba(67,56,202,0.15)]"
      style={{ height: 'min(71vh, 650px)', minHeight: '500px' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 bg-[#f1f3f9] rounded-t-[38px] border-b border-indigo-100">
        <div className="flex items-center gap-3">
          <MercuryAvatar size={36} animated />
          <div>
            <div className="text-[15px] font-semibold text-gray-900">墨墨</div>
            {typing && (
              <div className="text-[10px] text-indigo-600">墨墨正在思考...</div>
            )}
          </div>
        </div>
        <button
          className="text-2xl text-gray-400 hover:text-gray-600 transition"
          onClick={() => {
            setMsgs([WELCOME_MSG])
            setMood('cheerful')
          }}
          title="清空对话"
        >
          +
        </button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-6 space-y-4">
        {/* Welcome with mascot */}
        <div className="flex flex-col items-center gap-4 pb-6">
          <MercuryMascot size={180} mood={mood} animated />
          <div className="text-center">
            <div className="text-base font-medium text-gray-900 mb-2 whitespace-pre-line">
              {WELCOME_MSG.text}
            </div>
            <div className="flex flex-wrap gap-2 justify-center mt-4">
              {QUICK_ACTIONS.map(action => (
                <button
                  key={action.id}
                  onClick={() => handleSend(action.prompt)}
                  disabled={typing}
                  className="px-4 py-2 text-xs font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 rounded-full transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {action.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Message list */}
        {msgs.slice(1).map(msg => (
          <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : ''}`}>
            {msg.role === 'ai' && <MercuryAvatar size={32} />}
            <div
              className={`max-w-[70%] px-4 py-3 text-[13px] font-medium leading-[1.7] tracking-[-0.015em] whitespace-pre-line ${
                msg.role === 'user'
                  ? 'bg-[#171716] text-white rounded-[24px_24px_8px_24px]'
                  : 'bg-[#eef2ff] text-gray-900 rounded-[24px_24px_24px_8px]'
              }`}
            >
              {msg.text}
            </div>
          </div>
        ))}

        {/* Typing indicator */}
        {typing && (
          <div className="flex gap-3">
            <MercuryAvatar size={32} />
            <div className="px-4 py-3 bg-[#eef2ff] rounded-[24px_24px_24px_8px]">
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-indigo-400 rounded-full animate-pulse" style={{ animationDelay: '0s' }}></span>
                <span className="w-2 h-2 bg-indigo-400 rounded-full animate-pulse" style={{ animationDelay: '0.2s' }}></span>
                <span className="w-2 h-2 bg-indigo-400 rounded-full animate-pulse" style={{ animationDelay: '0.4s' }}></span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="px-5 pb-6 pt-4">
        <div className="flex items-center gap-3 px-5 py-3 bg-white/90 backdrop-blur-sm rounded-full border border-indigo-100">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyPress={e => e.key === 'Enter' && !e.shiftKey && handleSend()}
            placeholder="问问墨墨吧..."
            disabled={typing}
            className="flex-1 bg-transparent text-[13px] font-medium text-gray-900 placeholder-gray-400 outline-none disabled:opacity-50"
          />
          <button
            onClick={() => handleSend()}
            disabled={!input.trim() || typing}
            className={`w-8 h-8 rounded-full flex items-center justify-center transition ${
              input.trim() && !typing
                ? 'bg-indigo-600 text-white hover:bg-indigo-700'
                : 'bg-gray-200 text-gray-400 cursor-not-allowed'
            }`}
          >
            ↑
          </button>
        </div>
      </div>
    </div>
  )
}
