import { useState, useRef, useEffect, useLayoutEffect, useCallback } from 'react'
import {
  ensureOpening,
  fetchOpening,
  fixedRoleSwitch,
  markPromptDisplayed,
  streamRoleSwitch,
  sendOpeningTurnStream,
  type ChatRole,
  type OpeningView,
} from './lib/chatOpening'
import { MercuryChat } from './MercuryChat'
import { MomoAvatar } from './components/MomoToast'
import {
  ApiError,
  addCartItem,
  cartItemCount,
  checkoutCart,
  categoryEmoji,
  clearStoredSessionId,
  confirmPlan,
  confirmableItems,
  ensureIdentity,
  getCart,
  getProduct,
  getGuideSession,
  getStoredSessionId,
  listOrders,
  listCategories,
  listProducts,
  clarificationChipOptions,
  normalizePendingClarifications,
  patchCartItem,
  progressPhaseLabel,
  productImageUrl,
  remainingQuantity,
  revisePlan,
  storeSessionId,
  yuan,
  type Cart,
  type Category,
  type Order,
  type PlanResponse,
  type Product,
  type ProductComparisonCard,
  type ClarificationAnswer,
  type ClarificationChoice,
  type SessionResponse,
  type TurnResponse,
} from './lib/saleGuide'

// ── Ceres Mascot ─────────────────────────────────────────────
type CeresMood = 'angry' | 'sad' | 'calm' | 'pleased' | 'happy'

function CeresMascot({ size = 36, mood = 'happy', animated = false }: { size?: number; mood?: CeresMood; animated?: boolean }) {
  const g = '#3DAA6B'
  const s = '#1A2E1F'
  return (
    <svg className={animated ? `ceres-hero-motion ceres-motion-${mood}` : undefined} width={size} height={size * 1.05} viewBox="0 0 72 76" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="36" cy="19" r="17" fill={g} />
      <circle cx="19" cy="36" r="17" fill={g} />
      <circle className={animated ? 'ceres-wave-leaf' : undefined} cx="53" cy="36" r="17" fill={g} />
      <circle cx="36" cy="53" r="17" fill={g} />
      <circle cx="36" cy="36" r="16" fill={g} />
      <ellipse cx="36" cy="12" rx="8" ry="4.5" fill="white" opacity="0.18" />
      {mood === 'angry' && <><path d="M27 37 L33 39 M45 37 L39 39" stroke={s} strokeWidth="2.4" strokeLinecap="round" /><ellipse className="ceres-eye" cx="31" cy="42" rx="2.1" ry="2.4" fill={s}/><ellipse className="ceres-eye" cx="41" cy="42" rx="2.1" ry="2.4" fill={s}/><path d="M30 51 Q36 46.5 42 51" stroke={s} strokeWidth="2.3" fill="none" strokeLinecap="round"/></>}
      {mood === 'sad' && <><ellipse className="ceres-eye" cx="31" cy="40" rx="2" ry="2.5" fill={s}/><ellipse className="ceres-eye" cx="41" cy="40" rx="2" ry="2.5" fill={s}/><path d="M30 51 Q36 46.5 42 51" stroke={s} strokeWidth="2" fill="none" strokeLinecap="round"/><path d="M45 44 C48 47 45 51 43.5 48 C42 46 44 44 45 44Z" fill="#9EDAF2"/></>}
      {mood === 'calm' && <><path d="M27 41 Q31 44 34 41 M38 41 Q41 44 45 41" stroke={s} strokeWidth="2" fill="none" strokeLinecap="round"/><path d="M31 49 L41 49" stroke={s} strokeWidth="2" strokeLinecap="round"/></>}
      {mood === 'pleased' && <><path d="M27 40 Q31 44 34 40 M38 40 Q42 44 45 40" stroke={s} strokeWidth="2.1" fill="none" strokeLinecap="round"/><path d="M30 48 Q36 54 42 48" stroke={s} strokeWidth="2.2" fill="none" strokeLinecap="round"/><ellipse cx="25.5" cy="46" rx="4" ry="2.5" fill="#F5A8C0" opacity="0.48"/><ellipse cx="46.5" cy="46" rx="4" ry="2.5" fill="#F5A8C0" opacity="0.48"/></>}
      {mood === 'happy' && <><path d="M 29 40 Q 32.5 37 36 40" stroke={s} strokeWidth="2.2" fill="none" strokeLinecap="round" /><ellipse className="ceres-eye" cx="42" cy="38.5" rx="2.6" ry="2.8" fill={s} /><circle cx="43.1" cy="37.1" r="1" fill="white" /><ellipse cx="25.5" cy="44.5" rx="4" ry="2.5" fill="#F5A8C0" opacity="0.4" /><ellipse cx="46.5" cy="44.5" rx="4" ry="2.5" fill="#F5A8C0" opacity="0.4" /><path d="M 30 47.5 Q 36 52.5 42 47.5" stroke={s} strokeWidth="2" fill="none" strokeLinecap="round" /></>}
    </svg>
  )
}

function ToastMascot({ mood, animated = false }: { mood: CeresMood; animated?: boolean }) {
  const motionClass = animated ? `toast-motion toast-motion-${mood}` : ''
  const face = {
    angry: <><path d="M246 279l42 12m137-3-42 14" stroke="#303040" strokeWidth="12" strokeLinecap="round"/><ellipse cx="278" cy="310" rx="12" ry="16" fill="#303040"/><ellipse cx="391" cy="310" rx="12" ry="16" fill="#303040"/><path d="M296 367q41-25 82 0" fill="none" stroke="#303040" strokeWidth="10" strokeLinecap="round"/></>,
    sad: <><path d="M246 296q28-18 55 1m67 1q28-18 55 1" fill="none" stroke="#303040" strokeWidth="10" strokeLinecap="round"/><ellipse cx="278" cy="311" rx="10" ry="13" fill="#303040"/><ellipse cx="391" cy="311" rx="10" ry="13" fill="#303040"/><path d="M296 373q41-25 82 0" fill="none" stroke="#303040" strokeWidth="9" strokeLinecap="round"/><path className="toast-tear" d="M407 329c10 15 5 27-5 27s-15-12 5-27Z" fill="#79cbe8"/></>,
    calm: <><path d="M244 310q29 20 58 0m64 0q29 20 58 0" fill="none" stroke="#303040" strokeWidth="10" strokeLinecap="round"/><path d="M300 367h74" stroke="#303040" strokeWidth="9" strokeLinecap="round"/></>,
    pleased: <><path d="M244 309q29 22 58 0m64 0q29 22 58 0" fill="none" stroke="#303040" strokeWidth="10" strokeLinecap="round"/><path d="M298 359q40 47 80 0" fill="none" stroke="#303040" strokeWidth="10" strokeLinecap="round"/><ellipse cx="239" cy="349" rx="22" ry="12" fill="#f39aad" opacity=".75"/><ellipse cx="430" cy="349" rx="22" ry="12" fill="#f39aad" opacity=".75"/></>,
    happy: <><path d="M243 303q30 27 60 0m63 0q30 27 60 0" fill="none" stroke="#303040" strokeWidth="11" strokeLinecap="round"/><path d="M295 354q42 55 85 0" fill="#303040" stroke="#303040" strokeWidth="8" strokeLinecap="round"/><path d="M314 372q23 12 46 0" stroke="white" strokeWidth="8" strokeLinecap="round"/><ellipse cx="238" cy="347" rx="24" ry="13" fill="#f39aad" opacity=".8"/><ellipse cx="432" cy="347" rx="24" ry="13" fill="#f39aad" opacity=".8"/></>,
  }[mood]

  return (
    <div className={`toast-mascot relative block h-[218px] w-[205px] brightness-[1.06] saturate-[1.04] contrast-[1.01] ${motionClass}`}>
      <img src="/assets/a49bc.svg" alt="吐司吉祥物" className="block h-full w-full" width="205" height="218" />
      <svg aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full -translate-y-[6px] scale-[1.12]" viewBox="0 0 676 720" fill="none">
        <path d="M210 236C256 205 337 204 401 236C432 251 444 279 434 318L415 394C374 420 278 411 221 375C203 332 197 277 210 236Z" fill="#E0D080" />
        {face}
      </svg>
    </div>
  )
}

// ── Keke Avatar ───────────────────────────────────────────────
function KekeAvatar({ size = 28, animated = false }: { size?: number; animated?: boolean }) {
  return (
    <svg className={animated ? 'keke-breathe' : undefined} width={size} height={size} viewBox="0 0 40 40" fill="none" aria-label="可可，四叶草导购助手">
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

// ── Illustrations ─────────────────────────────────────────────
function DietBowlSVG() {
  return (
    <svg width="110" height="110" viewBox="0 0 110 110" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* plate shadow */}
      <ellipse cx="55" cy="88" rx="32" ry="7" fill="#E8D5C4" opacity="0.5" />
      {/* bowl body */}
      <path d="M22 58 Q22 86 55 86 Q88 86 88 58 Z" fill="white" stroke="#E8D5C4" strokeWidth="1.5" />
      {/* bowl rim */}
      <ellipse cx="55" cy="58" rx="33" ry="10" fill="white" stroke="#E8D5C4" strokeWidth="1.5" />
      {/* salad greens */}
      <ellipse cx="55" cy="54" rx="26" ry="9" fill="#5BC480" />
      <path d="M30 54 Q38 44 46 54 Q54 44 62 54 Q70 44 78 54" fill="#3DAA6B" />
      <path d="M34 56 Q42 48 50 56" fill="#5BC480" />
      <path d="M60 56 Q68 48 76 56" fill="#5BC480" />
      {/* tomatoes */}
      <circle cx="44" cy="52" r="6" fill="#F05A5A" />
      <path d="M42 46 Q44 43 46 46" stroke="#3DAA6B" strokeWidth="1.5" fill="none" strokeLinecap="round" />
      <circle cx="44" cy="52" r="2" fill="#F07070" opacity="0.5" />
      <circle cx="65" cy="53" r="5" fill="#F05A5A" />
      <path d="M63 48 Q65 45 67 48" stroke="#3DAA6B" strokeWidth="1.5" fill="none" strokeLinecap="round" />
      {/* lemon wedge */}
      <path d="M72 48 Q80 44 82 52 Q76 54 72 48Z" fill="#FFE566" stroke="#F5C800" strokeWidth="1" />
      <path d="M74 49 L80 51" stroke="#F5C800" strokeWidth="0.8" strokeLinecap="round" />
      {/* sparkles */}
      <path d="M20 38 L21.5 34 L23 38 L20 38Z" fill="#FFD166" />
      <path d="M21.5 34 L21.5 30 L20 34" fill="#FFD166" opacity="0.6" />
      <circle cx="21.5" cy="34" r="1.5" fill="#FFD166" />
      <path d="M88 30 L89.5 26 L91 30 L88 30Z" fill="#FFD166" />
      <path d="M89.5 26 L89.5 22" stroke="#FFD166" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M85 28 L89.5 26 L94 28" stroke="#FFD166" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="25" cy="24" r="2" fill="#FFD166" opacity="0.6" />
      <circle cx="85" cy="40" r="1.5" fill="#FFD166" opacity="0.8" />
    </svg>
  )
}

function BasketSVG() {
  return (
    <svg width="110" height="110" viewBox="0 0 110 110" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* shadow */}
      <ellipse cx="55" cy="90" rx="30" ry="6" fill="#E0C9A0" opacity="0.4" />
      {/* basket body */}
      <path d="M20 55 Q20 85 55 85 Q90 85 90 55 Z" fill="#D4A86A" />
      <path d="M20 55 L90 55" stroke="#C49050" strokeWidth="1" />
      {/* weave lines horizontal */}
      <path d="M22 63 L88 63" stroke="#C49050" strokeWidth="0.8" opacity="0.6" />
      <path d="M23 71 L87 71" stroke="#C49050" strokeWidth="0.8" opacity="0.6" />
      <path d="M25 79 L85 79" stroke="#C49050" strokeWidth="0.8" opacity="0.6" />
      {/* weave lines vertical */}
      <path d="M35 55 L32 85" stroke="#C49050" strokeWidth="0.8" opacity="0.5" />
      <path d="M45 55 L43 85" stroke="#C49050" strokeWidth="0.8" opacity="0.5" />
      <path d="M55 55 L55 85" stroke="#C49050" strokeWidth="0.8" opacity="0.5" />
      <path d="M65 55 L67 85" stroke="#C49050" strokeWidth="0.8" opacity="0.5" />
      <path d="M75 55 L78 85" stroke="#C49050" strokeWidth="0.8" opacity="0.5" />
      {/* basket rim */}
      <ellipse cx="55" cy="55" rx="35" ry="10" fill="#E8B87A" stroke="#C49050" strokeWidth="1.5" />
      {/* handle */}
      <path d="M30 55 Q30 28 55 28 Q80 28 80 55" fill="none" stroke="#C49050" strokeWidth="5" strokeLinecap="round" />
      <path d="M30 55 Q30 30 55 30 Q80 30 80 55" fill="none" stroke="#D4A86A" strokeWidth="3" strokeLinecap="round" />
      {/* carrot */}
      <path d="M62 22 Q65 10 68 20 Q70 30 65 40 Q60 35 62 22Z" fill="#FF8C3A" />
      <path d="M65 10 L62 4 M65 10 L68 3 M65 10 L60 5" stroke="#3DAA6B" strokeWidth="1.8" strokeLinecap="round" />
      {/* leafy greens */}
      <path d="M28 44 Q20 30 30 28 Q32 38 28 44Z" fill="#5BC480" />
      <path d="M33 42 Q26 26 38 24 Q38 36 33 42Z" fill="#3DAA6B" />
      <path d="M38 42 Q34 28 44 26 Q43 38 38 42Z" fill="#5BC480" />
      {/* radish */}
      <circle cx="48" cy="44" r="7" fill="#F06090" />
      <path d="M46 37 L45 30 M48 37 L48 29 M50 37 L51 30" stroke="#3DAA6B" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M48 51 L49 57" stroke="#F06090" strokeWidth="1.5" strokeLinecap="round" />
      {/* sparkles */}
      <circle cx="88" cy="38" r="2" fill="#FFD166" />
      <path d="M88 34 L88 42 M84 38 L92 38" stroke="#FFD166" strokeWidth="1.2" strokeLinecap="round" />
      <circle cx="18" cy="42" r="1.5" fill="#FFD166" opacity="0.8" />
      <path d="M20 26 L21 22 L22 26 L20 26Z" fill="#FFD166" />
      <circle cx="85" cy="22" r="1.5" fill="#FFD166" opacity="0.7" />
    </svg>
  )
}

// ── Icons ─────────────────────────────────────────────────────
function IconHome({ filled }: { filled?: boolean }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      {!filled && <polyline points="9 22 9 12 15 12 15 22" />}
    </svg>
  )
}
function IconGrid({ filled }: { filled?: boolean }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" fill={filled ? 'currentColor' : 'none'} />
      <rect x="14" y="3" width="7" height="7" fill={filled ? 'currentColor' : 'none'} />
      <rect x="3" y="14" width="7" height="7" fill={filled ? 'currentColor' : 'none'} />
      <rect x="14" y="14" width="7" height="7" fill={filled ? 'currentColor' : 'none'} />
    </svg>
  )
}
function IconOrders({ filled }: { filled?: boolean }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  )
}
function IconUser({ filled }: { filled?: boolean }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  )
}
function IconCart() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9" cy="21" r="1" /><circle cx="20" cy="21" r="1" />
      <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6" />
    </svg>
  )
}
function IconSearch() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
}
function IconBell() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  )
}

// ── Demo badge & Chat types ───────────────────────────────────
function DemoBadge() {
  return (
    <span className="rounded-full bg-black/[0.06] px-1.5 py-0.5 text-[9px] font-semibold tracking-wide text-black/40">
      演示
    </span>
  )
}

type Role = 'user' | 'ai'
interface Msg { id: string; role: Role; text: string; suggestions?: string[]; clarificationOptions?: ClarificationChoice[]; productCards?: ProductComparisonCard[] }

const WELCOME_MSG: Msg = {
  id: 'welcome',
  role: 'ai',
  text: '嗨！我是可可 🌿\n你的专属导购小助手！告诉我今天想吃什么，我来帮你搞定～',
  suggestions: ['今晚做红烧肉', '减脂餐计划', '家里有小孩', '来点零食'],
}

function newRequestId() {
  return `req-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

function formatText(text: string) {
  return text.split('\n').map((line, i, arr) => (
    <span key={i}>
      {line.split(/\*\*(.*?)\*\*/g).map((part, j) =>
        j % 2 === 1 ? <strong key={j}>{part}</strong> : part
      )}
      {i < arr.length - 1 && <br />}
    </span>
  ))
}

function stripDuplicateClarificationOptions(text: string, suggestions: string[] | undefined): string {
  if (!suggestions?.length || !text.trim()) return text

  const lines = text.split('\n')
  const numbered: { index: number; label: string }[] = []

  for (let i = 0; i < lines.length; i++) {
    const match = lines[i].trim().match(/^\d+\.\s*(.+)$/)
    if (match) numbered.push({ index: i, label: match[1].trim() })
  }

  if (numbered.length === 0) return text

  const firstIdx = numbered[0].index
  const contiguous = numbered.every((item, idx) => item.index === firstIdx + idx)
  if (!contiguous) return text

  const parsedLabels = numbered.map(item => item.label)
  const suggestionSet = new Set(suggestions)
  const labelsMatch =
    parsedLabels.length === suggestions.length &&
    parsedLabels.every(label => suggestionSet.has(label)) &&
    suggestions.every(label => parsedLabels.includes(label))

  if (!labelsMatch) return text

  return lines.slice(0, firstIdx).join('\n').trimEnd()
}

// ── Landing Screen ────────────────────────────────────────────
const MOODS: { id: CeresMood; label: string; emoji: string }[] = [
  { id: 'angry', label: '烦躁', emoji: '😡' }, { id: 'sad', label: '低气压', emoji: '😕' }, { id: 'calm', label: '平静', emoji: '😐' }, { id: 'pleased', label: '不错', emoji: '🙂' }, { id: 'happy', label: '超开心', emoji: '😍' },
]

function LandingScreen({ onGoShelf, onGreenReset }: { onGoShelf: () => void; onGreenReset: () => void }) {
  const [activeMood, setActiveMood] = useState<CeresMood>('happy')
  const [moodMotion, setMoodMotion] = useState(0)

  return (
    <div className="home-atmosphere h-full overflow-y-auto scrollbar-hide">
      <div className="flex min-h-full flex-col justify-end">
      <section className="relative h-[326px] shrink-0 overflow-hidden px-5 pt-8">
        <div aria-hidden="true" className="absolute -left-16 bottom-14 h-36 w-56 rounded-[50%] bg-[#dfe8ff]" />
        <div aria-hidden="true" className="absolute -left-8 bottom-10 h-20 w-56 rounded-[50%] bg-[#385af2]" />
        <div aria-hidden="true" className="absolute right-[-22px] top-12 h-20 w-20 rounded-full bg-[#ffb18c]" />
        <div aria-hidden="true" className="absolute bottom-12 right-3 h-28 w-28 rounded-full bg-[#b8dd82]" />
        <div aria-hidden="true" className="absolute bottom-[82px] left-8 h-2.5 w-2.5 rounded-full bg-[#e97255] shadow-[13px_-13px_0_#e97255]" />
        <div className="absolute left-7 top-4 z-10 whitespace-nowrap text-[40px] font-normal leading-[1.16] tracking-[-0.035em] text-[#18251d]" style={{ fontFamily: "'ZCOOL KuaiLe', 'Noto Sans SC', sans-serif" }}>哈喽，<br/>Ceres的朋友!</div>
        <svg aria-hidden="true" className="absolute left-[226px] top-[106px] z-10" width="38" height="28" viewBox="0 0 38 28" fill="none"><path d="M2 4C8 2 15 6 16 13C17 20 25 23 35 20" stroke="#18251D" strokeWidth="2.5" strokeLinecap="round" strokeDasharray="4 5" /></svg>
        <div className="absolute right-5 top-[82px] z-10 rotate-[8deg] drop-shadow-[0_13px_5px_rgba(57,93,40,0.18)]"><CeresMascot key={`${activeMood}-${moodMotion}`} size={174} mood={activeMood} animated /></div>
        <div aria-hidden="true" className="absolute bottom-[92px] right-[48px] h-8 w-4 rotate-[16deg] rounded-full bg-[#3d9a61]" />
      </section>

      <section className="shrink-0 px-6 pb-5">
        <h2 className="mb-3 flex items-center gap-2 text-[18px] font-bold tracking-[-0.04em] text-[#34463a]">今日心情 <DemoBadge /></h2>
        <div className="flex items-center justify-between">
          {MOODS.map(mood => {
            const selected = activeMood === mood.id
            return <button key={mood.id} aria-label={mood.label} onClick={() => { setActiveMood(mood.id); setMoodMotion(n => n + 1) }} className="grid h-[55px] w-[55px] place-items-center bg-transparent text-[43px] leading-none transition-transform active:scale-90" style={{ transform: selected ? 'translateY(-4px) scale(1.12)' : undefined, filter: selected ? 'drop-shadow(0 5px 5px rgba(49,86,60,0.24))' : 'drop-shadow(0 2px 3px rgba(67,75,57,0.10))' }}>{mood.emoji}</button>
          })}
        </div>
      </section>

      <section className="shrink-0 px-5 pb-4 pt-3">
        <div className="mb-3 flex items-center justify-between"><h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-[-0.02em] text-[#26372c]"><span className="h-2 w-2 rounded-full bg-[#d6bded]"/>为你准备</h2><button className="text-[11px] font-semibold text-[#477950]">查看全部 ↗</button></div>
        <div className="grid grid-cols-2 gap-3">
          <button onClick={onGreenReset} aria-label="GREEN RESET 今天轻一点今日限定活动" className="relative h-[178px] overflow-hidden rounded-[25px] border-2 border-white bg-[#f3b18e] p-4 text-left shadow-[0_5px_0_#d7876c] transition-transform active:translate-y-1 active:shadow-none"><div aria-hidden="true" className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-[#f9e58d]"/><div aria-hidden="true" className="absolute -left-8 bottom-4 h-12 w-16 rotate-[-25deg] rounded-full bg-[#cf92e8]/60"/><span className="relative text-[10px] font-semibold text-[#7f3328]">今日限定</span><p className="relative mt-1 text-[17px] font-bold leading-none tracking-[-0.04em] text-[#522d27]">GREEN RESET</p><p className="relative mt-1 max-w-[95px] text-[10px] font-medium leading-snug text-[#794f45]">今天轻一点 · 成品轻食</p><div className="absolute -bottom-5 right-[-3px] scale-[0.86]"><DietBowlSVG /></div></button>
          <button onClick={onGoShelf} className="relative h-[178px] overflow-hidden rounded-[25px] border-2 border-white bg-[#c3e493] p-4 text-left shadow-[0_5px_0_#90b567] transition-transform active:translate-y-1 active:shadow-none"><div aria-hidden="true" className="absolute -left-5 -top-5 h-20 w-20 rounded-full bg-[#f7e666]"/><div aria-hidden="true" className="absolute right-4 top-12 h-12 w-5 rotate-[35deg] rounded-full bg-[#bca8ec]/70"/><span className="relative text-[10px] font-semibold text-[#356234]">当季鲜选</span><p className="relative mt-1 text-lg font-bold leading-none tracking-[-0.04em] text-[#244c2c]">生鲜采买</p><p className="relative mt-1 max-w-[95px] text-[10px] font-medium leading-snug text-[#527151]">当季食材一键备货</p><div className="absolute -bottom-5 right-[-4px] scale-[0.86]"><BasketSVG /></div></button>
        </div>
      </section>
      </div>
    </div>
  )
}

// ── Cart Drawer ───────────────────────────────────────────────
function CartDrawer({
  open,
  cart,
  onClose,
  onUpdateQty,
  loading,
  error,
}: {
  open: boolean
  cart: Cart | null
  onClose: () => void
  onUpdateQty: (skuId: string, qty: number) => void
  loading: boolean
  error: string | null
}) {
  if (!open) return null
  return (
    <div className="absolute inset-0 z-30 flex flex-col justify-end bg-black/25" role="dialog" aria-label="购物车">
      <button type="button" className="absolute inset-0" aria-label="关闭购物车" onClick={onClose} />
      <aside className="relative max-h-[70vh] overflow-hidden rounded-t-[28px] bg-white shadow-xl">
        <div className="flex items-center justify-between border-b px-5 py-4">
          <h3 className="text-[17px] font-semibold tracking-[-0.04em] text-[#1d1c1a]">购物车</h3>
          <button type="button" onClick={onClose} className="grid h-8 w-8 place-items-center rounded-full bg-[#f2f1ed] text-black/50 active:scale-90">✕</button>
        </div>
        <div className="scrollbar-hide max-h-[50vh] overflow-y-auto px-5 py-3">
          {error && <p className="mb-2 text-xs text-red-600">{error}</p>}
          {!cart?.items.length && <p className="py-8 text-center text-sm text-black/40">购物车是空的</p>}
          {cart?.items.map((item) => (
            <div key={item.sku_id} className="flex items-center gap-3 border-b border-black/[0.05] py-3 last:border-0">
              <img src={productImageUrl(item.image_path)} alt="" className="h-12 w-12 rounded-xl object-cover bg-[#f2f2f4]" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium text-[#1d1c1a]">{item.name}</p>
                <p className="text-[12px] text-black/45">{yuan(item.unit_price_fen)}</p>
              </div>
              <div className="flex items-center gap-2">
                <button type="button" disabled={loading} onClick={() => onUpdateQty(item.sku_id, item.quantity - 1)} className="grid h-7 w-7 place-items-center rounded-full bg-[#f2f1ed] text-sm active:scale-90">−</button>
                <span className="w-5 text-center text-sm font-semibold">{item.quantity}</span>
                <button type="button" disabled={loading} onClick={() => onUpdateQty(item.sku_id, item.quantity + 1)} className="grid h-7 w-7 place-items-center rounded-full bg-[#f2f1ed] text-sm active:scale-90">+</button>
              </div>
            </div>
          ))}
        </div>
        {cart && cart.items.length > 0 && (
          <div className="border-t px-5 py-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-black/50">合计</span>
              <span className="text-[17px] font-bold tracking-[-0.03em]">{yuan(cart.total_price_fen)}</span>
            </div>
          </div>
        )}
      </aside>
    </div>
  )
}

// ── Shelf Screen ──────────────────────────────────────────────
function ProductCard({ p, onAdd, adding }: { p: Product; onAdd: (skuId: string) => void; adding: boolean }) {
  const [liked, setLiked] = useState(false)
  const displayName = p.name_zh || p.name
  const unitLabel = p.spec_unit ? `/${p.spec_unit}` : ''
  return (
    <article className="group flex flex-col overflow-hidden rounded-[22px] border border-black/[0.06] bg-white transition-colors duration-200 hover:border-black/[0.13]">
      <div className="relative aspect-[1/0.91] overflow-hidden bg-[#f2f1ed]">
        <img src={productImageUrl(p.image_path)} alt={displayName} className="h-full w-full object-cover" loading="lazy" />
        <span className="absolute left-3 top-3 rounded-md bg-white/95 px-2 py-1 text-[9px] font-medium tracking-[0.02em] text-[#5f655f]">产地可溯源</span>
        <button onClick={() => setLiked(v => !v)} aria-label={liked ? `取消收藏${displayName}` : `收藏${displayName}`} className="absolute right-3 top-3 grid h-8 w-8 place-items-center rounded-full bg-white/95 text-[15px] text-[#4c554c] transition active:scale-90">
          {liked ? '♥' : '♡'}
        </button>
        <span className="absolute right-1 top-10 scale-90"><DemoBadge /></span>
      </div>
      <div className="flex flex-col gap-1.5 px-4 pb-4 pt-3.5">
        <p className="line-clamp-2 text-[14px] font-semibold leading-tight text-[#20211f]">{displayName}</p>
        <div className="flex items-center gap-1 text-[10px] font-medium tracking-[0.01em] text-[#8a8d85]"><span className="text-[#d98a37]">★</span> 4.9 <span className="text-[#c7c8c1]">·</span> 今日采摘</div>
        <div className="mt-1.5 flex items-center justify-between">
          <span className="text-[15px] font-extrabold tracking-tight text-[#171816]" style={{ fontFamily: "'Instrument Sans', 'Noto Sans SC', sans-serif" }}>
            {yuan(p.price_fen ?? 0)}
            {unitLabel && <em className="ml-1 text-[10px] not-italic font-medium text-[#94968f]">{unitLabel}</em>}
          </span>
          <button
            onClick={() => onAdd(p.sku_id)}
            disabled={adding || !p.sellable}
            aria-label={`添加${displayName}到购物车`}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-[#191a18] transition-all duration-200 active:scale-90 disabled:opacity-40"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
          </button>
        </div>
      </div>
    </article>
  )
}

function ShelfScreen({
  cart,
  cartCount,
  onCartChange,
  onCategoryChange,
  onSearchChange,
}: {
  cart: Cart | null
  cartCount: number
  onCartChange: (cart: Cart) => void
  onCategoryChange: (categoryId: string | null) => void
  onSearchChange?: (query: string) => void
}) {
  const [categories, setCategories] = useState<Category[]>([])
  const [activeCat, setActiveCat] = useState<string | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [cartOpen, setCartOpen] = useState(false)
  const [cartBusy, setCartBusy] = useState(false)
  const [cartError, setCartError] = useState<string | null>(null)
  const [addingSku, setAddingSku] = useState<string | null>(null)
  const productsRef = useRef<HTMLDivElement>(null)

  const PROMO_CARDS = [
    {
      categoryId: 'vegetable',
      tag: '绿色餐桌计划',
      title: '有机蔬菜',
      subtitle: '全场 88 折',
      image: 'https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=500&h=300&fit=crop&auto=format',
      gradient: 'from-[#173321]/85 via-[#173321]/42 to-transparent',
      tagColor: 'text-[#d9efbd]',
    },
    {
      categoryId: 'meat',
      tag: '限时会员价',
      title: '牧场鲜肉',
      subtitle: '买二减一',
      image: 'https://images.unsplash.com/photo-1603048297172-c92544798d5a?w=500&h=300&fit=crop&auto=format',
      gradient: 'from-[#4f251d]/85 via-[#4f251d]/42 to-transparent',
      tagColor: 'text-[#ffe0c5]',
    },
  ] as const

  function jumpToCategory(categoryId: string) {
    const target =
      categories.find((c) => c.id === categoryId)?.id ??
      categories.find((c) => c.id.includes(categoryId) || c.name_zh.includes(categoryId === 'vegetable' ? '蔬菜' : '肉'))?.id ??
      categoryId
    setSearch('')
    onSearchChange?.('')
    setActiveCat(target)
    onCategoryChange(target)
    requestAnimationFrame(() => {
      productsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  const loadProducts = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await listProducts({
        category_id: search ? undefined : activeCat ?? undefined,
        q: search || undefined,
        page_size: 40,
      })
      setProducts(res.items)
    } catch {
      setError('商品加载失败')
      setProducts([])
    } finally {
      setLoading(false)
    }
  }, [activeCat, search])

  useEffect(() => {
    listCategories()
      .then((cats) => {
        setCategories(cats)
        if (cats.length) {
          setActiveCat((prev) => {
            const next = prev ?? cats[0].id
            if (!prev) onCategoryChange(cats[0].id)
            return next
          })
        }
      })
      .catch(() => setError('分类加载失败'))
  }, [onCategoryChange])

  useEffect(() => { loadProducts() }, [loadProducts])

  async function handleAdd(skuId: string) {
    if (!cart) return
    setAddingSku(skuId)
    setCartError(null)
    try {
      const next = await addCartItem(skuId, 1, cart.version)
      onCartChange(next)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'STALE_STATE') {
        const fresh = await getCart()
        onCartChange(fresh)
        setCartError('购物车已更新，请重试')
      } else {
        setCartError(e instanceof Error ? e.message : '加购失败')
      }
    } finally {
      setAddingSku(null)
    }
  }

  async function handleUpdateQty(skuId: string, qty: number) {
    if (!cart) return
    setCartBusy(true)
    setCartError(null)
    try {
      const next = await patchCartItem(skuId, qty, cart.version)
      onCartChange(next)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'STALE_STATE') {
        const fresh = await getCart()
        onCartChange(fresh)
        setCartError('购物车已更新，请重试')
      } else {
        setCartError(e instanceof Error ? e.message : '更新失败')
      }
    } finally {
      setCartBusy(false)
    }
  }

  return (
    <div className="relative flex h-full flex-col overflow-hidden bg-[#fcfbf8]">
      <header className="z-10 flex-shrink-0 border-b border-black/[0.05] bg-[#fcfbf8] px-5 pb-3 pt-5">
        <div className="mb-4 flex items-center justify-between">
          <button className="flex items-center gap-1 text-[18px] font-extrabold tracking-[-0.07em] text-[#22231f]">静安区 <span className="mt-0.5 text-[11px] font-semibold text-black/35">⌄</span></button>
          <div className="flex items-center gap-2">
            <button aria-label="通知" className="grid h-9 w-9 place-items-center rounded-full bg-white text-[#626560] transition active:scale-90"><IconBell /></button>
            <button aria-label="购物车" onClick={() => setCartOpen(true)} className="relative grid h-9 w-9 place-items-center rounded-full bg-[#171716] text-white transition active:scale-90">
              <IconCart />
              {cartCount > 0 && (
                <span className="absolute -top-1 -right-1 flex h-[17px] min-w-[17px] items-center justify-center rounded-full bg-[#df7f51] px-1 text-[9px] font-extrabold text-white">
                  {cartCount}
                </span>
              )}
            </button>
          </div>
        </div>
        <div className="relative">
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[#78917d]"><IconSearch /></div>
          <input value={search} onChange={e => { setSearch(e.target.value); onSearchChange?.(e.target.value) }} placeholder="搜索有机食材与好物" className="w-full rounded-2xl bg-white py-3.5 pl-10 pr-4 text-xs font-semibold text-[#30312d] outline-none transition placeholder:text-[#9a9a91] focus:ring-2 focus:ring-[#8ebc9a]" />
        </div>
      </header>

      <div className="z-10 flex-shrink-0 px-5 pt-3">
        <div className="flex gap-2 overflow-x-auto py-3 scrollbar-hide">
          {categories.map((cat) => {
            const isActive = cat.id === activeCat
            const emoji = categoryEmoji(cat.id)
            return (
              <button
                key={cat.id}
                onClick={() => { setActiveCat(cat.id); onCategoryChange(cat.id) }}
                aria-pressed={isActive}
                className={`group relative flex w-[68px] flex-shrink-0 flex-col items-center gap-2 bg-transparent pb-1 outline-none transition duration-200 ease-out active:scale-[0.98] ${isActive ? '-translate-y-0.5' : 'hover:-translate-y-px'}`}
              >
                <span className={`grid h-[58px] w-[58px] place-items-center rounded-[20px] bg-[#f7f6f2] transition-all duration-200 ${isActive ? 'shadow-[0_5px_10px_rgba(25,24,23,0.12),0_1px_2px_rgba(25,24,23,0.06)]' : 'shadow-[0_0_0_1px_rgba(247,246,242,0.9)] group-hover:shadow-[0_3px_7px_rgba(25,24,23,0.05)]'}`}>
                  <span className={`text-[30px] leading-none transition-transform duration-200 ${isActive ? 'scale-[1.04]' : 'grayscale-[0.08] group-hover:scale-[1.02]'}`}>{emoji}</span>
                </span>
                <span className={`relative w-full truncate text-center text-[12px] font-semibold tracking-[-0.05em] transition-colors duration-200 ${isActive ? 'text-[#252622]' : 'text-[#8c8d87] group-hover:text-[#596158]'}`}>
                  {cat.name_zh || cat.name}
                  <span aria-hidden="true" className={`absolute -bottom-1.5 left-1/2 h-[2px] -translate-x-1/2 rounded-full bg-[#252622] transition-all duration-300 ${isActive ? 'w-4 opacity-100' : 'w-0 opacity-0'}`} />
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="z-10 flex-1 overflow-y-auto scrollbar-hide px-5 pt-4 pb-6">
        {!search && (
          <section className="mb-6">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-[19px] font-semibold tracking-[-0.06em] text-[#191817]">今日精选 <DemoBadge /></h2>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {PROMO_CARDS.map((card) => (
                <button
                  key={card.categoryId}
                  type="button"
                  onClick={() => jumpToCategory(card.categoryId)}
                  className="relative h-[7.25rem] overflow-hidden rounded-[20px] p-3.5 text-left text-white transition active:scale-[0.98]"
                >
                  <img
                    src={card.image}
                    alt={card.title}
                    className="absolute inset-0 h-full w-full object-cover"
                    loading="lazy"
                  />
                  <div className={`absolute inset-0 bg-gradient-to-r ${card.gradient}`} />
                  <p className={`relative text-[10px] font-semibold ${card.tagColor}`}>{card.tag}</p>
                  <p className="relative mt-1 text-sm font-bold leading-tight tracking-[-0.04em]">
                    {card.title}
                    <br />
                    {card.subtitle}
                  </p>
                </button>
              ))}
            </div>
          </section>
        )}
        <div ref={productsRef} className="mb-3 flex items-end justify-between">
          <div>
            <h2 className="text-[19px] font-semibold tracking-[-0.06em] text-[#191817]">{search ? '搜索结果' : '人气鲜品'}</h2>
            <p className="mt-0.5 text-[10px] font-medium tracking-[0.02em] text-black/40">最快 30 分钟送达</p>
          </div>
          <button className="flex items-center gap-1 rounded-full border border-black/[0.08] bg-transparent px-3.5 py-2 text-[10px] font-medium text-black/40 transition active:scale-95">综合排序⌄ <DemoBadge /></button>
        </div>
        {error && (
          <div className="mb-4 rounded-2xl bg-red-50 px-4 py-3 text-center">
            <p className="text-sm text-red-700">{error}</p>
            <button type="button" onClick={loadProducts} className="mt-2 text-xs font-semibold text-red-800 underline">重试</button>
          </div>
        )}
        {loading && <p className="py-8 text-center text-sm text-black/40">加载中…</p>}
        {!loading && !error && products.length === 0 && <p className="py-8 text-center text-sm text-black/40">暂无商品</p>}
        <div className="grid grid-cols-2 gap-3">
          {products.map(p => (
            <ProductCard key={p.sku_id} p={p} onAdd={handleAdd} adding={addingSku === p.sku_id} />
          ))}
        </div>
      </div>
      <CartDrawer open={cartOpen} cart={cart} onClose={() => setCartOpen(false)} onUpdateQty={handleUpdateQty} loading={cartBusy} error={cartError} />
    </div>
  )
}

// ── Guide floating sheets ─────────────────────────────────────
type GuideSheet = 'activity' | 'plan' | 'cart'
type GuideViewContext = {
  page: string
  category_id?: string | null
  product_id?: string | null
  activity_id?: string | null
}

const GREEN_RESET_ACTIVITY_ID = 'green_reset'
const GREEN_RESET_PRODUCT_IDS = [
  'demo:green-reset-avocado-salad',
  'demo:green-reset-fruit-platter',
  'demo:cn-minute-maid-peach-450ml-bottle',
]

function SheetCloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      onClick={onClose}
      aria-label="关闭"
      className="absolute right-3 top-3 z-10 grid h-[22px] w-[22px] place-items-center rounded-full bg-black/[0.06] text-black/40 backdrop-blur-sm transition hover:bg-black/[0.09]"
    >
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M18 6L6 18M6 6l12 12" /></svg>
    </button>
  )
}

function ChatFloatingSheet({
  children,
  onClose,
  panelRef,
  morphOrigin,
  closing,
  onMorphEnd,
  sheetKey,
}: {
  children: React.ReactNode
  onClose: () => void
  panelRef: React.RefObject<HTMLDivElement | null>
  morphOrigin: string
  closing: boolean
  onMorphEnd: () => void
  sheetKey: GuideSheet
}) {
  return (
    <div className="absolute inset-x-0 bottom-full z-10 mb-2 px-4">
      <div
        ref={panelRef}
        key={sheetKey}
        className={`guide-glass-surface relative flex flex-col overflow-hidden rounded-[24px] ${
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

function GuideSheetItemList({ itemCount, children }: { itemCount: number; children: React.ReactNode }) {
  const scrollable = itemCount > 2
  return (
    <div
      className={`space-y-2 px-4 pb-2 ${
        scrollable ? 'guide-sheet-scroll max-h-[148px] overflow-y-auto pr-1.5' : ''
      }`}
    >
      {children}
    </div>
  )
}

function ChatGuideCapsules({
  openSheet,
  onToggle,
  planCount,
  cartCount,
  capsuleRefs,
  onSwitchToMomo,
  switchBusy,
}: {
  openSheet: GuideSheet | null
  onToggle: (sheet: GuideSheet) => void
  planCount: number
  cartCount: number
  capsuleRefs: Record<GuideSheet, React.RefObject<HTMLButtonElement | null>>
  onSwitchToMomo?: () => void
  switchBusy?: boolean
}) {
  const capsuleClass = (active: boolean) =>
    `inline-flex shrink-0 items-center gap-1.5 rounded-full px-4 py-2.5 text-[13px] font-medium tracking-[-0.01em] transition-colors ${
      active
        ? 'guide-glass-surface text-[#1d1c1a]'
        : 'guide-glass-chip text-black/42'
    }`

  const countBadge = (count: number) =>
    count > 0 ? (
      <span className="grid h-[18px] min-w-[18px] place-items-center rounded-full bg-[#e23b3b] px-1 text-[10px] font-semibold leading-none text-white">
        {count}
      </span>
    ) : null

  return (
    <div className="scrollbar-hide mb-2.5 flex gap-2.5 overflow-x-auto">
      <button type="button" ref={capsuleRefs.activity} onClick={() => onToggle('activity')} className={capsuleClass(openSheet === 'activity')}>
        今日活动
      </button>
      <button type="button" ref={capsuleRefs.plan} onClick={() => onToggle('plan')} className={capsuleClass(openSheet === 'plan')} aria-label={planCount > 0 ? `采购清单 ${planCount} 件` : '采购清单'}>
        采购清单
        {countBadge(planCount)}
      </button>
      <button type="button" ref={capsuleRefs.cart} onClick={() => onToggle('cart')} className={capsuleClass(openSheet === 'cart')} aria-label={cartCount > 0 ? `购物车 ${cartCount} 件` : '购物车'}>
        购物车
        {countBadge(cartCount)}
      </button>
      <button
        type="button"
        disabled={switchBusy || !onSwitchToMomo}
        onClick={() => onSwitchToMomo?.()}
        className={`${capsuleClass(false)} disabled:opacity-45`}
      >
        <MomoAvatar size={20} />
        售后找我
      </button>
    </div>
  )
}

function PlanRowCheckbox({ checked, disabled, onToggle }: { checked: boolean; disabled: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      disabled={disabled}
      onClick={onToggle}
      className={`grid h-5 w-5 shrink-0 place-items-center rounded-full transition ${
        checked ? 'bg-[#171716] text-white' : 'bg-white/80 ring-1 ring-black/12'
      }`}
    >
      {checked && (
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12" /></svg>
      )}
    </button>
  )
}

function ActivitySheetContent({
  disabled,
  onSelect,
}: {
  disabled: boolean
  onSelect: (product: Product) => void
}) {
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all(GREEN_RESET_PRODUCT_IDS.map((skuId) => getProduct(skuId)))
      .then(setProducts)
      .catch(() => setError('活动商品暂时加载失败'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="flex flex-col pt-4">
      <h3 className="px-5 text-[14px] font-bold tracking-[-0.03em] text-[#1d1c1a]">GREEN RESET｜今天轻一点</h3>
      <p className="px-5 pb-3 pt-1 text-[11px] leading-relaxed text-black/48">今天想吃点清爽的？挑一份成品沙拉、鲜果拼盘或桃汁，让可可接着帮你搭配。</p>
      {loading && <p className="px-5 py-4 text-[11px] text-black/40">正在准备今日限定…</p>}
      {error && <p className="px-5 py-4 text-[11px] text-red-600">{error}</p>}
      {!loading && !error && (
        <GuideSheetItemList itemCount={products.length}>
          {products.map((product) => {
            const name = product.name_zh || product.name
            return (
              <button
                key={product.sku_id}
                type="button"
                aria-label={`选购${name}`}
                disabled={disabled || !product.sellable}
                onClick={() => onSelect(product)}
                className="flex w-full items-center gap-3 rounded-[18px] bg-white/65 px-2.5 py-2 text-left disabled:opacity-45"
              >
                <img src={productImageUrl(product.image_path)} alt="" className="h-11 w-11 shrink-0 rounded-xl bg-black/[0.04] object-cover" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12px] font-medium text-[#1d1c1a]">{name}</span>
                  <span className="mt-0.5 block text-[10px] text-black/40">{product.sellable ? '限定成品 · 让可可介绍' : '暂不可选'}</span>
                </span>
                <span className="shrink-0 text-[12px] font-semibold text-black/65">{yuan(product.price_fen ?? 0)}</span>
              </button>
            )
          })}
        </GuideSheetItemList>
      )}
    </div>
  )
}

function PlanEmptySheetContent() {
  return (
    <div className="flex min-h-[120px] items-center justify-center px-6 py-10">
      <p className="text-[12px] font-medium text-black/35">还没有采购清单</p>
    </div>
  )
}

function CartEmptySheetContent() {
  return (
    <div className="flex min-h-[120px] items-center justify-center px-6 py-10">
      <p className="text-[12px] font-medium text-black/35">购物车是空的</p>
    </div>
  )
}

function PlanSheetContent({
  plan,
  onToggleItem,
  confirming,
  canConfirm,
  typing,
  onConfirm,
}: {
  plan: PlanResponse
  onToggleItem: (skuId: string) => void
  confirming: boolean
  canConfirm: boolean
  typing: boolean
  onConfirm: () => void
}) {
  const gaps = plan.gaps?.filter(g => g.message) ?? []
  const total = plan.items
    .filter((item) => item.selected !== false)
    .reduce((sum, item) => sum + remainingQuantity(item) * item.unit_price_fen, 0)
  const hasConfirmable = confirmableItems(plan.items).length > 0
  return (
    <div className="flex flex-col pt-4">
      <p className="px-5 pb-2 text-[12px] font-semibold tracking-[-0.02em] text-[#1d1c1a]">采购清单</p>
      <GuideSheetItemList itemCount={plan.items.length}>
        {plan.items.map((item) => {
          const checked = item.selected !== false
          const packageUnit = item.spec_unit === 'kg' ? 'g' : item.spec_unit === 'l' ? 'ml' : item.spec_unit
          const packageAmount = (item.spec_quantity ?? 0) * (item.spec_unit === 'kg' || item.spec_unit === 'l' ? 1000 : 1)
          const requirements = item.contributions?.map(c => c.requirement) ?? [item.requirement]
          const compatible = requirements.filter(r => r?.quantity != null && r.unit === packageUnit)
          const requirementQuantity = compatible.reduce((sum, r) => sum + r!.quantity!, 0)
          const comparable = compatible.length > 0 && packageAmount > 0
          const purchased = ((item.added_quantity ?? 0) + (checked ? remainingQuantity(item) : 0)) * packageAmount
          const needed = packageUnit === 'pc' ? Math.ceil(requirementQuantity) : requirementQuantity
          const difference = purchased - needed
          const unitLabel = packageUnit === 'pc' ? '枚' : packageUnit
          return (
            <div
              key={item.sku_id}
              className={`flex items-center gap-2.5 rounded-[18px] px-2.5 py-2 transition-opacity ${
                checked ? 'bg-white/70' : 'bg-white/40 opacity-70'
              }`}
            >
              <PlanRowCheckbox checked={checked} disabled={confirming || typing} onToggle={() => onToggleItem(item.sku_id)} />
              <img src={productImageUrl(item.image_path)} alt="" className="h-11 w-11 shrink-0 rounded-xl bg-black/[0.04] object-cover" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[12px] font-medium text-[#1d1c1a]">{item.name || item.sku_id}</p>
                <p className="mt-0.5 text-[10px] text-black/38">已加购 {item.added_quantity ?? 0} 件 · 本次选购 {checked ? remainingQuantity(item) : 0} 件</p>
                {comparable && (
                  <p className="mt-0.5 text-[10px] leading-snug text-black/45">
                    需求 {requirementQuantity}{unitLabel}{packageUnit === 'pc' && needed !== requirementQuantity ? `（整枚 ${needed}）` : ''} · 采购覆盖 {purchased}{unitLabel} · {difference >= 0 ? '包装余量' : '本次未覆盖'} {Math.abs(difference)}{unitLabel}
                  </p>
                )}
                {requirements.filter(r => r?.source?.original_quantity != null).map((r, index) => (
                  <p key={index} className="mt-0.5 text-[10px] leading-snug text-black/38">
                    菜谱原需 {r!.source!.original_quantity}{r!.source!.original_unit === 'pc' ? '枚' : r!.source!.original_unit}，本规格分担 {r!.quantity}{unitLabel}
                  </p>
                ))}
                {(item.contributions?.length ?? 0) > 1 && item.contributions!.map(c => (
                  <p key={c.group_id} className="mt-0.5 text-[10px] leading-snug text-black/38">
                    {plan.targets?.find(t => t.group_id === c.group_id)?.name ?? c.group_id}：{c.requirement?.quantity ?? '用量未明确'}{c.requirement?.unit === 'pc' ? '枚' : c.requirement?.unit}
                  </p>
                ))}
              </div>
              <span className="shrink-0 text-[12px] font-medium text-black/55">{yuan(checked ? remainingQuantity(item) * item.unit_price_fen : 0)}</span>
            </div>
          )
        })}
      </GuideSheetItemList>
      {plan.items.some(item => item.role === 'required' && item.selected === false) && (
        <p className="px-5 pb-1 text-[10px] leading-snug text-black/45">未选的必需食材不会加购；当前仅采购勾选部分。</p>
      )}
      {gaps.map((g) => (
        <p key={g.gap_id} className="px-5 pb-1 text-[10px] leading-snug text-black/45">{g.message}</p>
      ))}
      <div className="flex items-center justify-between px-5 py-3">
        <span className="text-[13px] font-semibold tracking-[-0.03em] text-[#1d1c1a]">{yuan(total)}</span>
        <button
          type="button"
          disabled={confirming || typing || !canConfirm || !hasConfirmable}
          onClick={onConfirm}
          className="rounded-full bg-[#171716] px-4 py-2 text-[11px] font-semibold text-white disabled:opacity-50"
        >
          {confirming ? '处理中…' : '确认加购'}
        </button>
      </div>
    </div>
  )
}

function CartSheetContent({
  cart,
  busy,
  error,
  onUpdateQty,
  onCheckout,
}: {
  cart: Cart
  busy: boolean
  error: string | null
  onUpdateQty: (skuId: string, qty: number) => void
  onCheckout: () => void
}) {
  return (
    <div className="flex flex-col pt-4">
      <p className="px-5 pb-2 text-[12px] font-semibold tracking-[-0.02em] text-[#1d1c1a]">购物车</p>
      <GuideSheetItemList itemCount={cart.items.length}>
        {cart.items.map((item) => (
          <div key={item.sku_id} className="flex items-center gap-3 rounded-[18px] bg-white/55 px-2.5 py-2">
            <img src={productImageUrl(item.image_path)} alt="" className="h-11 w-11 shrink-0 rounded-xl bg-black/[0.04] object-cover" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[12px] font-medium text-[#1d1c1a]">{item.name}</p>
              <p className="mt-0.5 text-[10px] text-black/38">{yuan(item.line_total_fen)}</p>
            </div>
            <button type="button" disabled={busy} onClick={() => onUpdateQty(item.sku_id, item.quantity - 1)} className="grid h-6 w-6 place-items-center rounded-full bg-black/[0.05] text-sm text-black/55">−</button>
            <span className="w-4 text-center text-[12px] font-semibold text-[#1d1c1a]">{item.quantity}</span>
            <button type="button" disabled={busy} onClick={() => onUpdateQty(item.sku_id, item.quantity + 1)} className="grid h-6 w-6 place-items-center rounded-full bg-black/[0.05] text-sm text-black/55">+</button>
          </div>
        ))}
      </GuideSheetItemList>
      {error && <p className="px-5 pb-1 text-[10px] text-red-600">{error}</p>}
      <div className="flex items-center justify-between px-5 py-3">
        <span className="text-[13px] font-semibold tracking-[-0.03em] text-[#1d1c1a]">{yuan(cart.total_price_fen)}</span>
        <button
          type="button"
          disabled={busy}
          onClick={onCheckout}
          className="rounded-full bg-[#171716] px-4 py-2 text-[11px] font-semibold text-white disabled:opacity-50"
        >
          结算
        </button>
      </div>
    </div>
  )
}

// ── Chat Screen ───────────────────────────────────────────────

function ChatCheckoutSheet({
  cart,
  busy,
  error,
  onBack,
  onConfirm,
}: {
  cart: Cart
  busy: boolean
  error: string | null
  onBack: () => void
  onConfirm: () => void
}) {
  return (
    <div className="absolute inset-0 z-20 flex flex-col bg-[#fcfbf8]">
      <div className="flex flex-shrink-0 items-center gap-3 px-5 pt-4 pb-3">
        <button
          type="button"
          onClick={onBack}
          disabled={busy}
          className="grid h-9 w-9 place-items-center rounded-full bg-[#f2f1ed] text-black/55 transition active:scale-95"
          aria-label="返回"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="15 18 9 12 15 6" /></svg>
        </button>
        <p className="text-[15px] font-semibold tracking-[-0.04em] text-[#191817]">结算</p>
      </div>
      <div className="scrollbar-hide flex-1 space-y-2 overflow-y-auto px-5 py-2">
        {cart.items.map((item) => (
          <div key={item.sku_id} className="flex items-center gap-3 rounded-[22px] bg-white/80 px-3 py-3">
            <img src={productImageUrl(item.image_path)} alt="" className="h-12 w-12 rounded-2xl bg-[#f2f2f4] object-cover" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium text-[#1d1c1a]">{item.name}</p>
              <p className="mt-0.5 text-[11px] text-black/38">× {item.quantity}</p>
            </div>
            <span className="shrink-0 text-[13px] font-semibold tracking-[-0.03em] text-[#1d1c1a]">{yuan(item.line_total_fen)}</span>
          </div>
        ))}
      </div>
      <div className="flex-shrink-0 px-5 pb-5 pt-3">
        {error && <p className="mb-2 text-center text-[11px] text-red-600">{error}</p>}
        <div className="rounded-[26px] bg-[#f7f6f2] px-5 py-4">
          <div className="mb-4 flex items-end justify-between">
            <span className="text-[12px] font-medium text-black/42">合计</span>
            <span className="text-[20px] font-semibold tracking-[-0.05em] text-[#1d1c1a]">{yuan(cart.total_price_fen)}</span>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={onConfirm}
            className="w-full rounded-full bg-[#171716] py-3.5 text-[13px] font-semibold text-white transition active:scale-[.98] disabled:opacity-50"
          >
            {busy ? '结算中…' : '确认结算'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ChatCheckoutSuccess({
  order,
  onDone,
  onViewOrders,
}: {
  order: Order
  onDone: () => void
  onViewOrders: () => void
}) {
  return (
    <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-[#fcfbf8] px-8">
      <div className="w-full max-w-[280px] rounded-[28px] bg-[#f7f6f2] px-6 py-8 text-center">
        <p className="text-[12px] font-medium text-black/40">订单已提交</p>
        <p className="mt-3 text-[22px] font-semibold tracking-[-0.05em] text-[#1d1c1a]">{order.order_id}</p>
        <p className="mt-2 text-[15px] font-medium text-black/55">{yuan(order.total_fen)}</p>
        <p className="mt-4 text-[11px] leading-relaxed text-black/35">本次为模拟下单，未发货；可在订单页查看商品和成交快照</p>
      </div>
      <div className="mt-8 flex w-full max-w-[280px] flex-col gap-2">
        <button
          type="button"
          onClick={onViewOrders}
          className="w-full rounded-full bg-[#171716] py-3 text-[13px] font-semibold text-white transition active:scale-[.98]"
        >
          查看订单
        </button>
        <button
          type="button"
          onClick={onDone}
          className="w-full rounded-full bg-[#f2f1ed] py-3 text-[13px] font-medium text-black/55 transition active:scale-[.98]"
        >
          继续聊天
        </button>
      </div>
    </div>
  )
}

function ChatScreen({
  active,
  viewContext,
  openActivityOnMount,
  onCartRefresh,
  cart,
  onCartChange,
  onViewOrders,
  openingId,
  openingGuideSessionId,
  liveHandoff,
  onSwitchToMomo,
  switchBusy,
  onHandoffSwitch,
}: {
  active: boolean
  viewContext: GuideViewContext
  openActivityOnMount: boolean
  onCartRefresh: () => void
  cart: Cart | null
  onCartChange: (cart: Cart) => void
  onViewOrders: () => void
  openingId: string | null
  openingGuideSessionId: string | null
  liveHandoff?: { role: ChatRole; user: string; assistant: string; typing: boolean } | null
  onSwitchToMomo?: () => void
  switchBusy?: boolean
  onHandoffSwitch?: (
    body: { accept: boolean; target_role: ChatRole; handoff_id: string },
    userMessage: string,
    guideCallbacks: Parameters<typeof streamRoleSwitch>[2],
  ) => Promise<void>
}) {
  const [msgs, setMsgs] = useState<Msg[]>([WELCOME_MSG])
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const [restoring, setRestoring] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [stateVersion, setStateVersion] = useState(0)
  const [sessionVersion, setSessionVersion] = useState(0)
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  const [canConfirm, setCanConfirm] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [progressText, setProgressText] = useState<string | null>(null)
  const [cartBusy, setCartBusy] = useState(false)
  const [cartError, setCartError] = useState<string | null>(null)
  const [checkoutPhase, setCheckoutPhase] = useState<'checkout' | 'success' | null>(null)
  const [checkoutBusy, setCheckoutBusy] = useState(false)
  const [checkoutError, setCheckoutError] = useState<string | null>(null)
  const [placedOrder, setPlacedOrder] = useState<Order | null>(null)
  const [openSheet, setOpenSheet] = useState<GuideSheet | null>(null)
  const [selectedProductViewContext, setSelectedProductViewContext] = useState<GuideViewContext | null>(null)
  const [sheetClosing, setSheetClosing] = useState(false)
  const [sheetMorphOrigin, setSheetMorphOrigin] = useState('50% 100%')
  const bottomRef = useRef<HTMLDivElement>(null)
  const guideCapsuleActivityRef = useRef<HTMLButtonElement>(null)
  const guideCapsulePlanRef = useRef<HTMLButtonElement>(null)
  const guideCapsuleCartRef = useRef<HTMLButtonElement>(null)
  const guideSheetPanelRef = useRef<HTMLDivElement>(null)
  const streamRef = useRef<AbortController | null>(null)
  const [pendingHandoff, setPendingHandoff] = useState<{
    handoffId: string
    targetRole: ChatRole
    promptMode: string
  } | null>(null)
  const promptMarkedRef = useRef<string | null>(null)

  useEffect(() => {
    if (openActivityOnMount) setOpenSheet('activity')
  }, [openActivityOnMount])

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, typing, plan, progressText, openSheet])

  const measureGuideSheetOrigin = useCallback((sheet: GuideSheet) => {
    const capsule = sheet === 'activity'
      ? guideCapsuleActivityRef.current
      : sheet === 'plan'
        ? guideCapsulePlanRef.current
        : guideCapsuleCartRef.current
    const panel = guideSheetPanelRef.current
    if (!capsule || !panel) return
    const cap = capsule.getBoundingClientRect()
    const pan = panel.getBoundingClientRect()
    const x = cap.left + cap.width / 2 - pan.left
    const y = cap.top + cap.height / 2 - pan.top
    setSheetMorphOrigin(`${x}px ${y}px`)
  }, [])

  useLayoutEffect(() => {
    if (!openSheet || sheetClosing) return
    measureGuideSheetOrigin(openSheet)
  }, [openSheet, sheetClosing, measureGuideSheetOrigin])

  const closeGuideSheet = useCallback(() => {
    if (!openSheet) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setOpenSheet(null)
      setSheetClosing(false)
      return
    }
    setSheetClosing(true)
  }, [openSheet])

  const handleGuideSheetMorphEnd = useCallback(() => {
    setOpenSheet(null)
    setSheetClosing(false)
  }, [])

  const toggleGuideSheet = useCallback((sheet: GuideSheet) => {
    if (openSheet === sheet && !sheetClosing) {
      closeGuideSheet()
      return
    }
    setSheetClosing(false)
    setOpenSheet(sheet)
  }, [openSheet, sheetClosing, closeGuideSheet])

  const applyAuthoritativeSnapshot = useCallback((snapshot: Pick<
    SessionResponse,
    'task_id' | 'state_version' | 'session_version' | 'plan' | 'available_actions'
  >) => {
    setTaskId(snapshot.task_id ?? null)
    setStateVersion(snapshot.state_version)
    setSessionVersion(snapshot.session_version)
    const canConfirmNow = snapshot.available_actions?.includes('confirm') ?? false
    setCanConfirm(canConfirmNow && snapshot.plan?.can_confirm !== false)
    setPlan(snapshot.available_actions?.includes('modify') ? (snapshot.plan ?? null) : null)
  }, [])

  const applyTurnTerminalState = useCallback((turn: TurnResponse) => {
    setTaskId(turn.task_id)
    setStateVersion(turn.state_version)
    setSessionVersion(turn.session_version)
    const planEffect = turn.plan_effect ?? 'keep'
    if (planEffect === 'clear') {
      setPlan(null)
    } else if (planEffect === 'replace' && turn.plan) {
      setPlan(turn.plan)
    }
    const canConfirmNow = turn.available_actions != null
      ? turn.available_actions.includes('confirm')
      : turn.plan?.can_confirm !== false
    if (turn.available_actions != null) {
      setCanConfirm(current => canConfirmNow && (planEffect === 'keep' ? current : turn.plan?.can_confirm !== false))
      if (!turn.available_actions.includes('modify')) {
        setPlan(null)
      }
    }
    if (
      planEffect === 'replace'
      && turn.plan
      && turn.plan.items.length > 0
      && canConfirmNow
    ) {
      setOpenSheet('plan')
    }
    if (turn.route === 'confirm_plan' && turn.committed) {
      onCartRefresh()
    }
  }, [onCartRefresh])

  const initSession = useCallback(async (forcedSessionId?: string | null) => {
    setRestoring(true)
    setError(null)
    try {
      await ensureIdentity()
      const sid = forcedSessionId ?? getStoredSessionId()
      if (!sid) {
        setSessionId(null)
        setError('会话连接失败，请稍后再试')
        return
      }
      const session = await getGuideSession(sid, true)
      setSessionId(session.session_id)
      storeSessionId(session.session_id)
      applyAuthoritativeSnapshot(session)
      const pending = normalizePendingClarifications(session.pending_clarifications ?? [])
      const chipOptions = clarificationChipOptions(pending)
      if (session.messages?.length) {
        const restored: Msg[] = session.messages
          .filter(m => m.role === 'user' || m.role === 'assistant')
          .map(m => ({
            id: m.message_id,
            role: m.role === 'user' ? 'user' : 'ai',
            text: m.content,
          }))
        if (restored.length) {
          if (chipOptions.length || session.product_cards?.length) {
            const lastAi = restored.map((m, index) => ({ m, index })).reverse().find(entry => entry.m.role === 'ai')
            if (lastAi) {
              restored[lastAi.index] = { ...restored[lastAi.index], clarificationOptions: chipOptions,
                productCards: session.product_cards }
            }
          }
          setMsgs(restored)
        }
      }
    } catch {
      setSessionId(null)
      setError('会话恢复失败，请发起新对话')
    } finally {
      setRestoring(false)
    }
  }, [applyAuthoritativeSnapshot])

  useEffect(() => {
    if (!active || !openingGuideSessionId) return
    initSession(openingGuideSessionId)
  }, [active, openingGuideSessionId, initSession])

  const send = useCallback(async (
    text: string,
    clarificationAnswer?: ClarificationAnswer,
    turnViewContext?: GuideViewContext,
  ) => {
    if (!text.trim() || !sessionId || typing || confirming || restoring || !openingId) return
    const trimmed = text.trim()
    setMsgs(p => [...p.map(m => m.clarificationOptions ? { ...m, clarificationOptions: undefined } : m), { id: `u-${Date.now()}`, role: 'user', text: trimmed }])
    setInput('')
    setTyping(true)
    setError(null)
    setProgressText(null)
    setPendingHandoff(null)

    const requestId = newRequestId()
    const assistantId = `a-${requestId}`
    let assistantText = ''
    setMsgs(p => [...p, { id: assistantId, role: 'ai', text: '' }])

    streamRef.current?.abort()
    const ac = new AbortController()
    streamRef.current = ac

    try {
      const result = await sendOpeningTurnStream(
        openingId,
        'keke',
        trimmed,
        requestId,
        taskId,
        stateVersion,
        sessionVersion,
        turnViewContext ?? selectedProductViewContext ?? viewContext,
        {
          signal: ac.signal,
          onProgress: (event) => {
            const phase = typeof event.payload?.phase === 'string' ? event.payload.phase : null
            setProgressText(progressPhaseLabel(phase))
          },
          onAnswerDelta: (event) => {
            const payload = event.payload
            const delta = typeof payload?.delta === 'string'
              ? payload.delta
              : typeof payload?.text === 'string'
                ? payload.text
                : typeof payload?.content === 'string'
                  ? payload.content
                  : ''
            if (!delta && !payload?.replace) return
            assistantText = payload?.replace === true ? delta : assistantText + delta
            setMsgs(p => p.map(m => m.id === assistantId ? { ...m, text: assistantText } : m))
          },
          onRoutePrompt: (message, route) => {
            assistantText = message
            setMsgs(p => p.map(m => m.id === assistantId ? { ...m, text: message } : m))
            if (route.handoff_id && route.target_role) {
              setPendingHandoff({
                handoffId: route.handoff_id,
                targetRole: route.target_role,
                promptMode: route.prompt_mode ?? 'automatic',
              })
            }
          },
        },
        plan ? {
          plan_id: plan.plan_id,
          plan_version: plan.plan_version,
          selected_items: confirmableItems(plan.items),
        } : undefined,
        undefined,
        clarificationAnswer,
      )
      if (result.kind === 'route_only') {
        return
      }
      const turn = result.turn
      const finalText = turn.message || assistantText
      const clarifications = normalizePendingClarifications(
        turn.pending_clarifications ?? (turn.pending_clarification ? [turn.pending_clarification] : []),
      )
      const chipOptions = clarificationChipOptions(clarifications)
      setMsgs(p => p.map(m => m.id === assistantId
        ? { ...m, text: finalText, clarificationOptions: chipOptions.length ? chipOptions : undefined,
            productCards: turn.product_cards }
        : m))
      applyTurnTerminalState(turn)
    } catch (e) {
      if (!ac.signal.aborted) {
        setError(e instanceof Error ? e.message : '发送失败')
      }
      if (!assistantText) {
        setMsgs(p => p.filter(m => m.id !== assistantId))
      }
    } finally {
      setTyping(false)
      setProgressText(null)
    }
  }, [sessionId, taskId, stateVersion, sessionVersion, typing, confirming, restoring, viewContext, selectedProductViewContext, plan, applyTurnTerminalState, openingId])

  const handleSelectActivityProduct = useCallback((product: Product) => {
    const productViewContext: GuideViewContext = {
      page: 'product',
      category_id: null,
      product_id: product.sku_id,
      activity_id: GREEN_RESET_ACTIVITY_ID,
    }
    setSelectedProductViewContext(productViewContext)
    void send(
      `我想看看 GREEN RESET｜今天轻一点活动里的「${product.name_zh || product.name}」，请可可帮我介绍一下。`,
      undefined,
      productViewContext,
    )
  }, [send])

  useEffect(() => {
    if (!openingId || !pendingHandoff || pendingHandoff.promptMode !== 'automatic') return
    if (promptMarkedRef.current === pendingHandoff.handoffId) return
    promptMarkedRef.current = pendingHandoff.handoffId
    markPromptDisplayed(openingId, pendingHandoff.handoffId).catch(() => {})
  }, [openingId, pendingHandoff])

  async function respondHandoff(accept: boolean) {
    if (!pendingHandoff || !openingId) return
    const lastUser = [...msgs].reverse().find(m => m.role === 'user')
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
    setError(null)
    try {
      let assistantText = ''
      const assistantId = `handoff-${Date.now()}`
      if (targetRole === 'keke') {
        setMsgs(p => [...p, { id: assistantId, role: 'ai', text: '' }])
      }
      await onHandoffSwitch(
        { accept: true, target_role: targetRole, handoff_id: handoffId },
        userMessage,
        {
          onProgress: (event) => {
            const phase = typeof event.payload?.phase === 'string' ? event.payload.phase : null
            setProgressText(progressPhaseLabel(phase))
          },
          onAnswerDelta: (event) => {
            const payload = event.payload
            const delta = typeof payload?.delta === 'string'
              ? payload.delta
              : typeof payload?.text === 'string'
                ? payload.text
                : ''
            if (!delta) return
            assistantText += delta
            setMsgs(p => p.map(m => (m.id === assistantId ? { ...m, text: assistantText } : m)))
          },
          onMercuryCompleted: (finalText) => {
            assistantText = finalText
          },
        },
      )
      if (targetRole === 'keke' && assistantText) {
        setMsgs(p => p.map(m => (m.id === assistantId ? { ...m, text: assistantText } : m)))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '切换失败')
    } finally {
      setTyping(false)
      setProgressText(null)
    }
  }

  async function handleNewChat() {
    streamRef.current?.abort()
    clearStoredSessionId()
    setMsgs([WELCOME_MSG])
    setPlan(null)
    setCanConfirm(false)
    setTaskId(null)
    setStateVersion(0)
    setSessionVersion(0)
    setSessionId(null)
    setSelectedProductViewContext(null)
    setPendingHandoff(null)
    if (openingGuideSessionId) {
      await initSession(openingGuideSessionId)
    }
  }

  async function handleCheckoutConfirm() {
    if (!cart || cart.items.length === 0 || checkoutBusy) return
    setCheckoutBusy(true)
    setCheckoutError(null)
    try {
      const result = await checkoutCart(cart.version)
      onCartChange(result.cart)
      setPlacedOrder(result.order)
      setCheckoutPhase('success')
    } catch (e) {
      if (e instanceof ApiError && e.code === 'STALE_STATE') {
        const fresh = await getCart()
        onCartChange(fresh)
        setCheckoutError('购物车已更新，请重试')
      } else {
        setCheckoutError(e instanceof Error ? e.message : '结算失败')
      }
    } finally {
      setCheckoutBusy(false)
    }
  }

  async function handleConfirm() {
    if (!plan || !taskId || confirming || typing || !canConfirm) return
    setConfirming(true)
    setError(null)
    try {
      const result = await confirmPlan(
        taskId,
        plan.plan_id,
        plan.plan_version,
        stateVersion,
        sessionVersion,
        confirmableItems(plan.items),
        newRequestId(),
      )
      setStateVersion(result.state_version)
      setSessionVersion(result.session_version)
      setPlan(null)
      setCanConfirm(false)
      setOpenSheet(null)
      onCartRefresh()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'STALE_STATE' && sessionId) {
        try {
          const session = await getGuideSession(sessionId, false)
          applyAuthoritativeSnapshot(session)
          setError('状态已更新，请重试确认')
        } catch {
          setError(e instanceof Error ? e.message : '确认失败')
        }
      } else {
        setError(e instanceof Error ? e.message : '确认失败')
      }
    } finally {
      setConfirming(false)
    }
  }

  async function handleTogglePlanItem(skuId: string) {
    if (!plan || !taskId || confirming || typing) return
    setConfirming(true)
    setError(null)
    try {
      const revision = await revisePlan(
        taskId,
        plan,
        stateVersion,
        sessionVersion,
        plan.items.map(item => ({
          sku_id: item.sku_id,
          quantity: item.quantity,
          selected: item.sku_id === skuId ? item.selected === false : item.selected !== false,
        })),
      )
      const { state_version, session_version, ...revisedPlan } = revision
      setPlan({ ...plan, ...revisedPlan })
      setStateVersion(state_version)
      setSessionVersion(session_version)
      setCanConfirm(revision.can_confirm)
    } catch (e) {
      setError(e instanceof Error ? e.message : '清单修改失败')
    } finally {
      setConfirming(false)
    }
  }

  const hasPlan = !!plan
  const cartCount = checkoutPhase === 'success' ? 0 : cartItemCount(cart)
  const planItemCount = hasPlan ? plan.items.length : 0

  return (
    <section
      className={`guide-chat-panel chat-panel-enter relative flex h-[min(71vh,650px)] max-h-full w-full min-h-[min(500px,71vh)] flex-shrink-0 flex-col overflow-hidden rounded-t-[38px] font-sans ${
        active ? '' : 'hidden'
      }`}
      aria-hidden={!active}
    >
      <div
        className={`guide-chat-scroll scrollbar-hide relative z-0 min-h-0 flex-1 space-y-5 overflow-y-auto px-6 pb-5 ${
          progressText ? 'pt-[7.75rem]' : 'pt-[6.75rem]'
        }`}
      >
        {restoring && <p className="text-center text-sm text-black/40">正在连接可可…</p>}
        {error && <p className="text-center text-xs text-red-600">{error}</p>}
        {msgs.map(msg => (
          <div key={msg.id} className={`flex items-end gap-2.5 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
            {msg.role === 'ai' && <KekeAvatar size={26} />}
            <div className={`flex max-w-[82%] flex-col gap-2.5 ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
              {msg.text ? (
                <div
                  className={`px-4 py-3 text-[13px] font-medium leading-[1.7] tracking-[-0.015em] ${
                    msg.role === 'ai' ? 'guide-glass-bubble' : ''
                  }`}
                  style={{
                    borderRadius: msg.role === 'user' ? '24px 24px 8px 24px' : '24px 24px 24px 8px',
                    background: msg.role === 'user' ? '#171716' : undefined,
                    color: msg.role === 'user' ? '#fff' : '#292825',
                  }}>
                  {formatText(stripDuplicateClarificationOptions(msg.text, msg.clarificationOptions?.map(option => option.label) ?? msg.suggestions))}
                </div>
              ) : msg.role === 'ai' && typing ? (
                <div
                  className="guide-glass-bubble ai-loading-bubble px-4 py-3 text-[13px] font-medium leading-[1.7] tracking-[-0.015em]"
                  style={{
                    borderRadius: '24px 24px 24px 8px',
                    color: '#292825',
                  }}>
                  <span className="ai-loading-ellipsis" aria-label="可可正在输入">
                    <span className="ai-loading-ellipsis__dot" aria-hidden="true">.</span>
                    <span className="ai-loading-ellipsis__dot" aria-hidden="true">.</span>
                    <span className="ai-loading-ellipsis__dot" aria-hidden="true">.</span>
                  </span>
                </div>
              ) : null}
              {!!msg.productCards?.length && (
                <section aria-label="可乐候选" className="flex w-full flex-col gap-2">
                  {msg.productCards.map(card => (
                    <div key={card.ref} className="guide-glass-bubble rounded-2xl px-4 py-3">
                      <p className="text-[12px] font-semibold leading-5">{card.name}</p>
                      <p className="mt-1 text-[11px] text-black/55">
                        每{card.packaging === 'can' ? '罐' : '瓶'} {card.item_volume_ml}ml · {card.pack_count}{card.packaging === 'can' ? '罐' : '瓶'}/包
                        {' · '}共 {card.total_volume_ml}ml
                      </p>
                      <p className="mt-1 text-[12px] font-semibold">
                        {yuan(card.price_fen)}/包 <span className="font-normal text-black/55">· {card.price_per_litre_yuan.toFixed(2)} 元/升</span>
                      </p>
                      <button disabled={typing || confirming || restoring}
                        onClick={() => send(`选择「${card.name}」（候选 ${card.ref}）生成采购清单`)}
                        className="mt-2 rounded-full bg-[#eac867] px-3 py-1.5 text-[11px] font-medium disabled:opacity-40">
                        选这款，生成清单
                      </button>
                    </div>
                  ))}
                  <div className="flex flex-wrap gap-1.5">
                    {['只看可口可乐', '只看百事可乐', '只看罐装', '只看瓶装', '只看单件装', '只看多件装', '取消可乐筛选条件'].map(label => (
                      <button key={label} disabled={typing || confirming || restoring}
                        onClick={() => send(`${label}，重新比较可乐`)}
                        className="guide-glass-chip rounded-full px-3 py-2 text-[11px] text-black/60 disabled:opacity-40">{label}</button>
                    ))}
                  </div>
                  <p className="text-[10px] text-black/45">模拟门店报价；选择后生成清单，明确确认才加购。</p>
                </section>
              )}
              {msg.clarificationOptions && msg.role === 'ai' && !typing && !confirming && (
                <div className="flex w-full flex-col gap-1.5">
                  {msg.clarificationOptions.map((option, i) => (
                    <button
                      key={option.question_id + ':' + option.option_id + ':' + i}
                      onClick={() => send(option.label, {
                        question_id: option.question_id,
                        option_id: option.option_id,
                      })}
                      className="guide-glass-chip rounded-full px-4 py-2.5 text-left text-[12px] font-medium text-black/55 transition active:scale-[.98]"
                    >
                      <span className="mr-2 text-[10px] font-semibold text-[#d79b58]">✦</span>
                      {option.label}
                    </button>
                  ))}
                </div>
              )}
              {msg.suggestions && msg.role === 'ai' && !typing && !confirming && (
                <div className="flex w-full flex-col gap-1.5">
                  {msg.suggestions.map((s, i) => (
                    <button key={i} onClick={() => send(s)} className="guide-glass-chip rounded-full px-4 py-2.5 text-left text-[12px] font-medium text-black/55 transition active:scale-[.98]">
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
                    {pendingHandoff.targetRole === 'momo' ? '找墨墨' : '找可可'}
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
        {liveHandoff?.role === 'keke' && (
          <div className="space-y-5">
            <div className="flex justify-end">
              <div className="guide-glass-bubble-user max-w-[85%] rounded-[22px] px-4 py-3 text-[13px] leading-relaxed text-[#1d1c1a]">
                {liveHandoff.user}
              </div>
            </div>
            <div className="flex justify-start">
              <div className="guide-glass-bubble-ai max-w-[90%] rounded-[22px] px-4 py-3 text-[13px] leading-relaxed text-[#1d1c1a]">
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
            className="guide-glass-icon-btn pointer-events-auto absolute right-5 top-1/2 z-10 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full text-black/45 transition hover:bg-white/70 active:scale-95"
            aria-label="发起新对话">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
          </button>
          <div className="guide-glass-header-pill pointer-events-auto relative z-10 inline-flex items-center gap-2.5 rounded-full py-2 pl-2 pr-5">
            <KekeAvatar size={36} animated />
            <p className="text-[15px] font-semibold tracking-[-0.04em] text-[#191817]">可可</p>
          </div>
        </div>
        {progressText && (
          <p className="mt-1 text-center text-[10px] text-black/40">{progressText}</p>
        )}
      </div>

      <div className="relative z-10 flex-shrink-0 px-5 pb-4 pt-2">
        {openSheet && !checkoutPhase && (
          <ChatFloatingSheet
            sheetKey={openSheet}
            panelRef={guideSheetPanelRef}
            morphOrigin={sheetMorphOrigin}
            closing={sheetClosing}
            onMorphEnd={handleGuideSheetMorphEnd}
            onClose={closeGuideSheet}
          >
            {openSheet === 'activity' && (
              <ActivitySheetContent
                disabled={typing || restoring || !sessionId || !openingId}
                onSelect={handleSelectActivityProduct}
              />
            )}
            {openSheet === 'plan' && (
              hasPlan
                ? (
                  <PlanSheetContent
                    plan={plan}
                    onToggleItem={handleTogglePlanItem}
                    confirming={confirming}
                    canConfirm={canConfirm}
                    typing={typing}
                    onConfirm={handleConfirm}
                  />
                )
                : <PlanEmptySheetContent />
            )}
            {openSheet === 'cart' && (
              cart && cart.items.length > 0 && checkoutPhase !== 'success'
                ? (
                  <CartSheetContent
                    cart={cart}
                    busy={cartBusy}
                    error={cartError}
                    onCheckout={() => {
                      setCheckoutError(null)
                      setOpenSheet(null)
                      setCheckoutPhase('checkout')
                    }}
                    onUpdateQty={async (skuId, qty) => {
                      setCartBusy(true)
                      setCartError(null)
                      try {
                        const next = await patchCartItem(skuId, qty, cart.version)
                        onCartChange(next)
                      } catch (e) {
                        if (e instanceof ApiError && e.code === 'STALE_STATE') {
                          const fresh = await getCart()
                          onCartChange(fresh)
                          setCartError('购物车已更新，请重试')
                        } else {
                          setCartError(e instanceof Error ? e.message : '更新失败')
                        }
                      } finally {
                        setCartBusy(false)
                      }
                    }}
                  />
                )
                : <CartEmptySheetContent />
            )}
          </ChatFloatingSheet>
        )}
        <ChatGuideCapsules
          openSheet={openSheet}
          onToggle={toggleGuideSheet}
          planCount={planItemCount}
          cartCount={cartCount}
          capsuleRefs={{
            activity: guideCapsuleActivityRef,
            plan: guideCapsulePlanRef,
            cart: guideCapsuleCartRef,
          }}
          onSwitchToMomo={onSwitchToMomo}
          switchBusy={switchBusy}
        />
        <div className="guide-glass-surface flex items-center gap-2 rounded-[28px] px-4 py-2.5">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') send(input) }}
            placeholder="问问可可吧…"
            disabled={restoring}
            className="min-w-0 flex-1 bg-transparent text-[13px] font-medium text-[#1d1c1a] outline-none placeholder:text-black/30"
          />
          <button onClick={() => send(input)} disabled={!input.trim() || !sessionId || typing || confirming || restoring}
            className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full transition-all active:scale-90 ${input.trim() && !typing && !confirming && !restoring ? 'bg-[#171716]' : 'bg-[#eeece7]'}`}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="white"><path d="M2 21L23 12 2 3v7l15 2-15 2z" /></svg>
          </button>
        </div>
      </div>

      {checkoutPhase === 'checkout' && cart && cart.items.length > 0 && (
        <ChatCheckoutSheet
          cart={cart}
          busy={checkoutBusy}
          error={checkoutError}
          onBack={() => {
            if (!checkoutBusy) {
              setCheckoutPhase(null)
              setCheckoutError(null)
            }
          }}
          onConfirm={handleCheckoutConfirm}
        />
      )}
      {checkoutPhase === 'success' && placedOrder && (
        <ChatCheckoutSuccess
          order={placedOrder}
          onDone={() => {
            setCheckoutPhase(null)
            setPlacedOrder(null)
            setCheckoutError(null)
          }}
          onViewOrders={() => {
            setCheckoutPhase(null)
            setPlacedOrder(null)
            setCheckoutError(null)
            onViewOrders()
          }}
        />
      )}
    </section>
  )
}

// ── Orders Screen ─────────────────────────────────────────────
function OrdersScreen() {
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listOrders()
      .then(({ items }) => setOrders(items))
      .catch((err) => setError(err instanceof Error ? err.message : '订单加载失败'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="flex h-full flex-col bg-[#fcfbf8]">
      <div className="flex-shrink-0 px-6 pt-10 pb-4">
        <h2 className="flex items-center gap-2 text-[26px] font-semibold tracking-[-0.07em] text-[#191817]">我的订单 <DemoBadge /></h2>
      </div>
      <div className="scrollbar-hide flex-1 space-y-3 overflow-y-auto px-5 pb-5">
        {loading && <p className="py-8 text-center text-[12px] text-black/40">正在加载订单…</p>}
        {error && <p className="py-8 text-center text-[12px] text-red-600">订单加载失败：{error}</p>}
        {!loading && !error && orders.length === 0 && (
          <p className="py-8 text-center text-[12px] text-black/40">还没有订单</p>
        )}
        {!loading && !error && orders.map((order) => (
          <article key={order.order_id} className="w-full rounded-[26px] bg-[#f7f6f2] p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2"><span className="text-[13px] font-semibold tracking-[-0.02em] text-[#252421]">{order.order_id}</span><span className="text-[10px] font-medium text-black/32">{new Date(order.created_at).toLocaleString('zh-CN')}</span></div>
              <span className="rounded-full bg-[#f7e8a7] px-2.5 py-1 text-[10px] font-medium text-[#735a13]">{order.status === 'paid' ? '模拟下单，未发货' : order.status}</span>
            </div>
            <p className="text-[12px] leading-relaxed text-black/52">{order.items.map(item => `${item.product_name} × ${item.quantity}`).join(' · ')}</p>
            <div className="flex items-center justify-between">
              <span className="mt-3 text-[10px] font-medium text-black/28">共 {order.items.length} 项商品</span>
              <span className="mt-3 text-[14px] font-semibold tracking-[-0.03em] text-[#1d1c1a]">¥{(order.total_fen / 100).toFixed(2)}</span>
            </div>
          </article>
        ))}
      </div>
    </div>
  )
}

// ── Profile Screen ────────────────────────────────────────────
function ProfileScreen() {
  const menuItems = [
    { label: '收货地址', icon: '📍' }, { label: '优惠券', icon: '🎟️' },
    { label: '会员中心', icon: '⭐' }, { label: '消息通知', icon: '🔔' },
    { label: '帮助与反馈', icon: '💬' }, { label: '关于 Ceres', icon: '🌿' },
  ]
  return (
    <div className="flex h-full flex-col bg-[#fcfbf8]">
      <div className="flex-shrink-0 px-6 pt-10 pb-5">
        <h2 className="flex items-center gap-2 text-[26px] font-semibold tracking-[-0.07em] text-[#191817]">个人中心 <DemoBadge /></h2>
      </div>
      <div className="mx-5 flex flex-shrink-0 items-center gap-4 rounded-[30px] bg-[#f2f1ed] p-4">
        <div className="grid h-14 w-14 place-items-center rounded-[20px] bg-[#f6df91] text-[22px]">C</div>
        <div className="min-w-0 flex-1"><p className="text-[16px] font-semibold tracking-[-0.04em] text-[#1d1c1a]">Ceres 会员</p><p className="mt-1 text-[11px] font-medium text-black/38">138 **** 8888</p></div>
        <span className="rounded-full bg-white/75 px-2.5 py-1 text-[10px] font-medium text-[#6e581a]">绿金会员</span>
      </div>
      <div className="mx-5 mt-3 flex flex-shrink-0 rounded-[25px] bg-[#f7f6f2] px-2 py-3">
        {[['12', '订单数'], ['3', '优惠券'], ['286', '积分']].map(([val, label]) => (
          <button key={label} className="flex-1 border-r border-black/[.06] last:border-0">
            <p className="text-[18px] font-semibold tracking-[-0.04em] text-[#1d1c1a]">{val}</p>
            <p className="mt-0.5 text-[10px] font-medium text-black/35">{label}</p>
          </button>
        ))}
      </div>
      <div className="scrollbar-hide mx-5 mt-5 flex-1 space-y-1.5 overflow-y-auto pb-5">
        <p className="px-2 pb-1 text-[10px] font-medium tracking-[0.12em] text-black/30">ACCOUNT</p>
        {menuItems.map(item => (
          <button key={item.label}
            className="flex w-full items-center gap-3 rounded-[20px] bg-[#f7f6f2] px-4 py-3.5 text-left transition hover:bg-[#f2f1ed] active:scale-[.985]">
            <span className="grid h-8 w-8 place-items-center rounded-xl bg-white/75 text-[15px]">{item.icon}</span>
            <span className="flex-1 text-[13px] font-medium text-[#302f2b]">{item.label}</span>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="rgba(0,0,0,.25)" strokeWidth="2" strokeLinecap="round"><polyline points="9 18 15 12 9 6" /></svg>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Bottom Nav ────────────────────────────────────────────────
type ViewState = 'home' | 'shelf' | 'keke' | 'orders' | 'momo' | 'profile'

interface NavItem {
  id: string
  label: string
  icon: (active: boolean) => React.ReactNode
  isKeke?: boolean
  isMomo?: boolean
}

function BottomNav({ view, onTap }: { view: ViewState; onTap: (id: string) => void }) {
  const onShelfCtx = view === 'shelf' || view === 'keke'
  const onOrdersCtx = view === 'orders' || view === 'momo'

  const tab2: NavItem = onShelfCtx
    ? { id: 'keke',  label: view === 'keke' ? '自己逛逛' : '问问可可', isKeke: true,  icon: () => <KekeAvatar size={20} /> }
    : { id: 'shelf', label: '商品',     isKeke: false, icon: (a) => <IconGrid filled={a} /> }

  const tab3: NavItem = onOrdersCtx
    ? { id: 'momo',  label: view === 'momo' ? '我再逛逛' : '问问墨墨', isMomo: true,  icon: () => <MomoAvatar size={20} /> }
    : { id: 'orders', label: '订单', icon: (a) => <IconOrders filled={a} /> }

  const tabs: NavItem[] = [
    { id: 'home',    label: '主页',   icon: (a) => <IconHome filled={a} /> },
    tab2,
    tab3,
    { id: 'profile', label: '个人中心', icon: (a) => <IconUser filled={a} /> },
  ]

  function isActive(id: string) {
    if (id === 'home')    return view === 'home'
    if (id === 'shelf')   return view === 'shelf'
    if (id === 'keke')    return view === 'keke'
    if (id === 'momo')    return view === 'momo'
    if (id === 'orders')  return view === 'orders'
    if (id === 'profile') return view === 'profile'
    return false
  }

  return (
    <div className="relative z-20 flex-shrink-0 px-5 pb-5 pt-3">
      <div className="flex items-center justify-between gap-1.5 rounded-full border border-white/90 bg-white/90 px-2 py-2 backdrop-blur-xl"
        style={{ boxShadow: '0 10px 26px rgba(56,72,54,0.16), 0 2px 0 rgba(190,185,170,0.18)' }}>
        {tabs.map(tab => {
          const active = isActive(tab.id)
          const isKeke = !!tab.isKeke
          const isMomo = !!tab.isMomo
          const expanded = active || isKeke || isMomo
          return (
            <button key={tab.id} onClick={() => onTap(tab.id)}
              className="flex h-10 items-center justify-center transition-all duration-300 ease-out active:scale-90"
              style={{
                borderRadius: 999,
                gap: expanded ? 6 : 0,
                padding: expanded ? (isKeke || isMomo ? '7px 14px 7px 9px' : '7px 14px') : '9px',
                background: isMomo
                  ? (active ? '#E9C96F' : '#FFF3C9')
                  : isKeke
                  ? (active ? '#E9C96F' : '#FFF3C9')
                  : (active ? '#39714B' : 'transparent'),
                color: active
                  ? (isMomo || isKeke ? '#4E3D12' : 'white')
                  : (isMomo || isKeke ? '#9D7B22' : '#91A097'),
                boxShadow: isMomo || isKeke
                  ? (active ? '0 4px 10px rgba(191,151,52,0.24)' : 'inset 0 0 0 1px rgba(220,185,75,0.22)')
                  : 'none',
              }}>
              {tab.icon(active && !isKeke && !isMomo)}
              <span className="text-xs font-extrabold whitespace-nowrap overflow-hidden transition-all duration-300"
                style={{ maxWidth: expanded ? 84 : 0, opacity: expanded ? 1 : 0 }}>
                {tab.label}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────
export default function App() {
  const [view, setView] = useState<ViewState>('home')
  const [cart, setCart] = useState<Cart | null>(null)
  const [activeCategoryId, setActiveCategoryId] = useState<string | null>(null)
  const [shelfSearch, setShelfSearch] = useState('')
  const [guideActivityId, setGuideActivityId] = useState<string | null>(null)
  const [opening, setOpening] = useState<OpeningView | null>(null)
  const [openingError, setOpeningError] = useState<string | null>(null)
  const [roleSwitchBusy, setRoleSwitchBusy] = useState(false)
  const [liveHandoff, setLiveHandoff] = useState<{
    role: ChatRole
    user: string
    assistant: string
    typing: boolean
  } | null>(null)
  const cartCount = cartItemCount(cart)
  const chatOverlayOpen = view === 'keke' || view === 'momo'
  const chatRole: ChatRole = view === 'momo' ? 'momo' : 'keke'

  const refreshCart = useCallback(async () => {
    try {
      await ensureIdentity()
      const data = await getCart()
      setCart(data)
    } catch {
      /* cart may be unavailable before bootstrap */
    }
  }, [])

  useEffect(() => { refreshCart() }, [refreshCart])

  const guideViewContext: GuideViewContext = guideActivityId
    ? { page: 'activity', category_id: null, activity_id: guideActivityId }
    : shelfSearch.trim()
      ? { page: 'search', category_id: null as string | null }
      : view === 'shelf' || view === 'keke'
        ? { page: 'category', category_id: activeCategoryId }
        : { page: 'home', category_id: null as string | null }

  useEffect(() => {
    if (!chatOverlayOpen) return
    let cancelled = false
    setOpeningError(null)
    ensureOpening(chatRole, guideViewContext)
      .then((next) => {
        if (!cancelled) setOpening(next)
      })
      .catch((err) => {
        if (!cancelled) {
          setOpening(null)
          setOpeningError(err instanceof Error ? err.message : '聊天连接失败')
        }
      })
    return () => {
      cancelled = true
    }
  }, [chatOverlayOpen, chatRole, guideViewContext.page, guideViewContext.category_id, guideViewContext.activity_id])

  const handleFixedRoleSwitch = useCallback(async (target: ChatRole) => {
    if (!opening || roleSwitchBusy) return
    setRoleSwitchBusy(true)
    setLiveHandoff(null)
    try {
      const next = await fixedRoleSwitch(opening.opening_id, target)
      setOpening(next)
      setView(target === 'momo' ? 'momo' : 'keke')
    } catch (err) {
      setOpeningError(err instanceof Error ? err.message : '切换失败')
    } finally {
      setRoleSwitchBusy(false)
    }
  }, [opening, roleSwitchBusy])

  const handleHandoffSwitch = useCallback(async (
    body: { accept: boolean; target_role: ChatRole; handoff_id: string },
    userMessage: string,
    guideCallbacks: Parameters<typeof streamRoleSwitch>[2],
  ) => {
    if (!opening) return
    let assistantAcc = ''
    await streamRoleSwitch(opening.opening_id, body, {
      ...guideCallbacks,
      onMercuryDelta: (chunk) => {
        assistantAcc += chunk
        guideCallbacks?.onMercuryDelta?.(chunk)
      },
      onMercuryCompleted: (finalText) => {
        assistantAcc = finalText
        guideCallbacks?.onMercuryCompleted?.(finalText)
      },
    }, body.target_role)
    const next = await fetchOpening(opening.opening_id)
    setOpening(next)
    setView(body.target_role === 'momo' ? 'momo' : 'keke')
    setLiveHandoff({
      role: body.target_role,
      user: userMessage,
      assistant: assistantAcc,
      typing: false,
    })
  }, [opening])

  function handleNavTap(id: string) {
    if (id === 'home')    { setView('home'); return }
    if (id === 'orders')  { setView('orders'); return }
    if (id === 'profile') { setView('profile'); return }
    if (id === 'shelf') setView('shelf')
    if (id === 'keke')  { setView(v => v === 'keke' ? 'shelf' : 'keke') }
    if (id === 'momo')  { setView(v => v === 'momo' ? 'orders' : 'momo') }
  }

  function handleGreenReset() {
    setGuideActivityId(GREEN_RESET_ACTIVITY_ID)
    setView('keke')
  }

  return (
    <main className="box-border min-h-dvh bg-[#eaf1ed] p-0 sm:p-8" style={{ fontFamily: "'Noto Sans SC', 'Manrope', system-ui, sans-serif" }}>
      <div className="relative mx-auto flex h-dvh w-full max-w-[430px] flex-col overflow-hidden bg-[#F5F5F7] sm:h-[min(860px,calc(100dvh-4rem))] sm:rounded-[32px] sm:shadow-[0_24px_70px_rgba(38,64,51,0.16)]">
        <div className="flex-1 overflow-hidden flex flex-col">
          {view === 'home' && (
            <LandingScreen
              onGoShelf={() => { setGuideActivityId(null); setView('shelf') }}
              onGreenReset={handleGreenReset}
            />
          )}
          {(view === 'shelf' || view === 'keke') && (
            <ShelfScreen
              cart={cart}
              cartCount={cartCount}
              onCartChange={setCart}
              onCategoryChange={setActiveCategoryId}
              onSearchChange={setShelfSearch}
            />
          )}
          {(view === 'orders' || view === 'momo') && <OrdersScreen />}
          {view === 'profile' && <ProfileScreen />}
        </div>

        <BottomNav view={view} onTap={handleNavTap} />
        {chatOverlayOpen && (
          <div className="absolute inset-x-0 bottom-[82px] top-0 z-10 flex flex-col justify-end bg-[#18261b]/20 backdrop-blur-[1px]">
            {openingError && (
              <p className="pointer-events-none absolute inset-x-0 top-24 z-30 text-center text-[11px] text-red-600">
                {openingError}
              </p>
            )}
            <div className="relative flex w-full flex-col justify-end">
            <ChatScreen
              active={chatRole === 'keke'}
              viewContext={guideViewContext}
              openActivityOnMount={guideViewContext.page === 'activity'}
              onCartRefresh={refreshCart}
              cart={cart}
              onCartChange={setCart}
              onViewOrders={() => setView('orders')}
              openingId={opening?.opening_id ?? null}
              openingGuideSessionId={opening?.guide_session_id ?? null}
              liveHandoff={liveHandoff}
              onSwitchToMomo={() => handleFixedRoleSwitch('momo')}
              switchBusy={roleSwitchBusy || !opening}
              onHandoffSwitch={handleHandoffSwitch}
            />
            <MercuryChat
              active={chatRole === 'momo'}
              visible={chatOverlayOpen}
              openingId={opening?.opening_id ?? null}
              mercurySessionId={opening?.mercury_session_id ?? null}
              liveHandoff={liveHandoff}
              onSwitchToKeke={() => handleFixedRoleSwitch('keke')}
              switchBusy={roleSwitchBusy || !opening}
              onHandoffSwitch={handleHandoffSwitch}
            />
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
