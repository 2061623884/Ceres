/**
 * MercuryMascot - 墨墨面包吉祥物组件
 * 基于 ToastMascot 模式,使用靛蓝色系
 */

type MercuryMood = 'cheerful' | 'attentive' | 'helpful' | 'apologetic' | 'thinking'

interface MercuryMascotProps {
  size?: number
  mood?: MercuryMood
  animated?: boolean
}

export function MercuryMascot({ size = 205, mood = 'cheerful', animated = false }: MercuryMascotProps) {
  const motionClass = animated ? `mercury-motion mercury-motion-${mood}` : ''

  // 靛蓝色系 - 区别于可可的绿色系
  const ink = '#4338ca'  // 深靛蓝色 (indigo-700)
  const blush = '#c4b5fd' // 浅靛蓝腮红 (indigo-300)

  // 面部表情 SVG paths
  const face = {
    // 专注倾听
    attentive: (
      <>
        <path d="M244 310q29 20 58 0m64 0q29 20 58 0" fill="none" stroke={ink} strokeWidth="10" strokeLinecap="round"/>
        <path d="M300 367h74" stroke={ink} strokeWidth="9" strokeLinecap="round"/>
      </>
    ),
    // 乐于助人
    helpful: (
      <>
        <path d="M244 309q29 22 58 0m64 0q29 22 58 0" fill="none" stroke={ink} strokeWidth="10" strokeLinecap="round"/>
        <path d="M298 359q40 47 80 0" fill="none" stroke={ink} strokeWidth="10" strokeLinecap="round"/>
        <ellipse cx="239" cy="349" rx="22" ry="12" fill={blush} opacity=".75"/>
        <ellipse cx="430" cy="349" rx="22" ry="12" fill={blush} opacity=".75"/>
      </>
    ),
    // 抱歉/同情
    apologetic: (
      <>
        <path d="M246 296q28-18 55 1m67 1q28-18 55 1" fill="none" stroke={ink} strokeWidth="10" strokeLinecap="round"/>
        <ellipse cx="278" cy="311" rx="10" ry="13" fill={ink}/>
        <ellipse cx="391" cy="311" rx="10" ry="13" fill={ink}/>
        <path d="M296 373q41-25 82 0" fill="none" stroke={ink} strokeWidth="9" strokeLinecap="round"/>
      </>
    ),
    // 思考中
    thinking: (
      <>
        <path d="M246 279l42 12m137-3-42 14" stroke={ink} strokeWidth="12" strokeLinecap="round"/>
        <ellipse cx="278" cy="310" rx="12" ry="16" fill={ink}/>
        <ellipse cx="391" cy="310" rx="12" ry="16" fill={ink}/>
        <path d="M296 367q41-25 82 0" fill="none" stroke={ink} strokeWidth="10" strokeLinecap="round"/>
      </>
    ),
    // 开心
    cheerful: (
      <>
        <path d="M243 303q30 27 60 0m63 0q30 27 60 0" fill="none" stroke={ink} strokeWidth="11" strokeLinecap="round"/>
        <path d="M295 354q42 55 85 0" fill={ink} stroke={ink} strokeWidth="8" strokeLinecap="round"/>
        <path d="M314 372q23 12 46 0" stroke="white" strokeWidth="8" strokeLinecap="round"/>
        <ellipse cx="238" cy="347" rx="24" ry="13" fill={blush} opacity=".8"/>
        <ellipse cx="432" cy="347" rx="24" ry="13" fill={blush} opacity=".8"/>
      </>
    ),
  }[mood]

  return (
    <div
      className={`mercury-mascot relative brightness-[1.04] saturate-[1.02] ${motionClass}`}
      style={{ width: size, height: size * 1.063 }}
    >
      <img
        src="/assets/a49bc.svg"
        alt="墨墨客服"
        className="block h-full w-full"
        width={size}
        height={size * 1.063}
      />
      <svg
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 h-full w-full -translate-y-[6px] scale-[1.12]"
        viewBox="0 0 676 720"
        fill="none"
      >
        {/* 面包主体保持金黄色 */}
        <path d="M210 236C256 205 337 204 401 236C432 251 444 279 434 318L415 394C374 420 278 411 221 375C203 332 197 277 210 236Z" fill="#E0D080" />
        {face}
      </svg>
    </div>
  )
}

/**
 * MercuryAvatar - 墨墨小头像 (用于消息列表)
 */
interface MercuryAvatarProps {
  size?: number
  animated?: boolean
}

export function MercuryAvatar({ size = 28, animated = false }: MercuryAvatarProps) {
  return (
    <div
      className={`mercury-avatar rounded-full bg-indigo-100 flex items-center justify-center ${animated ? 'mercury-breathe' : ''}`}
      style={{ width: size, height: size }}
    >
      <span className="text-lg">🍞</span>
    </div>
  )
}
