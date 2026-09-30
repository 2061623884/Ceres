/** 墨墨 — 欢迎区用吐司原图（自带表情），头像用圆形吐司脸 */

type ToastMood = 'angry' | 'sad' | 'calm' | 'pleased' | 'happy'

export function MomoAvatar({ size = 28, animated = false }: { size?: number; animated?: boolean }) {
  const ink = '#303040'
  const blush = '#f39aad'
  return (
    <svg
      className={`shrink-0 ${animated ? 'toast-motion toast-motion-calm' : ''}`}
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      aria-label="墨墨，吐司售后客服"
    >
      <circle cx="20" cy="20" r="20" fill="#f3e4a8" />
      <ellipse cx="20" cy="22.5" rx="13.5" ry="11.5" fill="#E0D080" />
      <ellipse cx="20" cy="17.5" rx="10" ry="4.5" fill="#F5EBA8" opacity="0.55" />
      <path
        d="M9 21.5C9 16.5 14 13 20 13C26 13 31 16.5 31 21.5"
        stroke="#C9B86A"
        strokeWidth="1.2"
        strokeLinecap="round"
        opacity="0.5"
      />
      <ellipse cx="14.5" cy="20" rx="2.05" ry="2.55" fill={ink} />
      <ellipse cx="25.5" cy="20" rx="2.05" ry="2.55" fill={ink} />
      <circle cx="15.25" cy="19.1" r="0.65" fill="white" />
      <circle cx="26.25" cy="19.1" r="0.65" fill="white" />
      <ellipse cx="11.5" cy="24.8" rx="3.1" ry="1.75" fill={blush} opacity="0.72" />
      <ellipse cx="28.5" cy="24.8" rx="3.1" ry="1.75" fill={blush} opacity="0.72" />
      <path d="M14.2 27.8Q20 32.2 25.8 27.8" fill={ink} />
      <path d="M16.2 28.6Q20 30.8 23.8 28.6" stroke="white" strokeWidth="1.15" strokeLinecap="round" />
    </svg>
  )
}

export function MomoToastHero({
  size = 120,
  mood = 'happy',
  animated = false,
}: {
  size?: number
  mood?: ToastMood
  animated?: boolean
}) {
  const motionClass = animated ? `toast-motion toast-motion-${mood}` : ''
  const h = size * 1.063
  return (
    <div
      className={`toast-mascot relative brightness-[1.06] saturate-[1.04] contrast-[1.01] ${motionClass}`}
      style={{ width: size, height: h }}
    >
      <img src="/assets/a49bc.svg" alt="墨墨" className="block h-full w-full" width={size} height={h} />
    </div>
  )
}
