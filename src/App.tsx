import { useState, useRef, useEffect } from 'react'

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

// ── Products & Categories ─────────────────────────────────────
const CATEGORY_SYSTEM = [
  { id: 'veg',   label: '蔬菜豆制品', icon: '🥬', sub: ['全部', '叶菜根茎', '葱姜蒜', '菌菇', '豆制品'] },
  { id: 'meat',  label: '肉禽蛋水产', icon: '🥩', sub: ['全部', '猪肉', '牛羊肉', '禽类', '蛋类', '水产制品'] },
  { id: 'dairy', label: '乳品饮料',   icon: '🥛', sub: ['全部', '乳品豆奶', '包装水', '茶饮汽水'] },
  { id: 'grain', label: '粮油干货',   icon: '🌾', sub: ['全部', '米面', '食用油', '干货坚果'] },
  { id: 'sauce', label: '调味品',     icon: '🧂', sub: ['全部', '基础调味', '火锅底料蘸料'] },
  { id: 'bake',  label: '烘焙原料',   icon: '🧁', sub: ['全部', '粉类', '糖与发酵', '烘焙乳脂', '香精辅料'] },
]

const PRODUCTS = [
  { id: 1,  name: '新鲜嫩姜',       price: 19.05, unit: '500g', img: 'https://images.unsplash.com/photo-1603048297172-c92544798d5a?w=400&h=400&fit=crop&auto=format', catId: 'veg' },
  { id: 2,  name: '有机西兰花',     price: 12.50, unit: '350g', img: 'https://images.unsplash.com/photo-1584868642973-82fdc39c0249?w=400&h=400&fit=crop&auto=format', catId: 'veg' },
  { id: 3,  name: '红甜椒',         price: 14.80, unit: '2个',  img: 'https://images.unsplash.com/photo-1563565375-f3fdfdbefa83?w=400&h=400&fit=crop&auto=format', catId: 'veg' },
  { id: 4,  name: '口蘑菌菇',       price: 11.90, unit: '200g', img: 'https://images.unsplash.com/photo-1518977676601-b53f82aba655?w=400&h=400&fit=crop&auto=format', catId: 'veg' },
  { id: 5,  name: '鲜嫩鸡胸',       price: 19.01, unit: '300g', img: 'https://images.unsplash.com/photo-1604503468506-a8da13d11d36?w=400&h=400&fit=crop&auto=format', catId: 'meat' },
  { id: 6,  name: '鸡蛋 10枚',      price: 22.80, unit: '盒装', img: 'https://images.unsplash.com/photo-1518569656558-1f25e69d2049?w=400&h=400&fit=crop&auto=format', catId: 'meat' },
  { id: 7,  name: '三文鱼',         price: 68.00, unit: '300g', img: 'https://images.unsplash.com/photo-1519708227418-c8fd9a32b7a2?w=400&h=400&fit=crop&auto=format', catId: 'meat' },
  { id: 8,  name: '纯牛奶',         price: 14.90, unit: '1L',   img: 'https://images.unsplash.com/photo-1550583724-b2692b85b150?w=400&h=400&fit=crop&auto=format', catId: 'dairy' },
  { id: 9,  name: '草莓',           price: 28.00, unit: '500g', img: 'https://images.unsplash.com/photo-1464965911861-746a04b4bca6?w=400&h=400&fit=crop&auto=format', catId: 'veg' },
  { id: 10, name: 'ManiLife 花生酱', price: 38.90, unit: '230g', img: 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400&h=400&fit=crop&auto=format', catId: 'grain' },
]

// ── Chat ──────────────────────────────────────────────────────
type Role = 'user' | 'ai'
interface Msg { id: number; role: Role; text: string; suggestions?: string[] }

const INITIAL_MSGS: Msg[] = [{
  id: 0, role: 'ai',
  text: '嗨！我是可可 🌿\n你的专属导购小助手！告诉我今天想吃什么，我来帮你搞定～',
  suggestions: ['今晚做红烧肉', '减脂餐计划', '家里有小孩', '来点零食'],
}]

function simulateReply(text: string): Msg {
  let reply = ''
  let suggestions: string[] = []
  if (text.includes('减脂') || text.includes('健康')) {
    reply = '减脂吃对很重要！🥦\n\n推荐：\n**西兰花** ¥12.50 — 高纤维低卡\n**三文鱼** ¥68.00 — 优质Omega-3\n**红甜椒** ¥14.80 — 维C爆棚'
    suggestions = ['一键加购', '还有其他推荐', '需要食谱吗']
  } else if (text.includes('红烧') || text.includes('肉')) {
    reply = '红烧肉！好主意 🤤\n\n备料：\n**鸡胸肉** ¥19.01\n**生姜** ¥19.05 — 去腥必备\n\n要我发完整食谱吗？'
    suggestions = ['发完整食谱', '还需要什么配料', '推荐酱油品牌']
  } else if (text.includes('零食')) {
    reply = '精选好货 🍓\n\n**花生酱** ¥38.90 — 无添加\n**草莓** ¥28.00 — 今日新鲜到货\n\n经典组合！加购吗？'
    suggestions = ['加入购物车', '还有饮料吗', '有优惠券吗']
  } else if (text.includes('小孩') || text.includes('儿童')) {
    reply = '给小朋友选，营养均衡最重要 👶\n\n**鸡蛋** ¥22.80 — 蛋白质\n**牛奶** ¥14.90 — 补钙\n**草莓** ¥28.00 — 小朋友最爱'
    suggestions = ['全部加购', '有机选项吗', '推荐儿童零食']
  } else {
    reply = `明白啦！「${text}」\n\n告诉我用餐人数和预算，可可帮你精准推荐食材组合～`
    suggestions = ['2人份，预算100', '素食为主', '荤素搭配']
  }
  return { id: Date.now(), role: 'ai', text: reply, suggestions }
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

// ── Landing Screen ────────────────────────────────────────────
const MOODS: { id: CeresMood; label: string; emoji: string }[] = [
  { id: 'angry', label: '烦躁', emoji: '😡' }, { id: 'sad', label: '低气压', emoji: '😕' }, { id: 'calm', label: '平静', emoji: '😐' }, { id: 'pleased', label: '不错', emoji: '🙂' }, { id: 'happy', label: '超开心', emoji: '😍' },
]

function LandingScreen({ onGoShelf }: { onGoShelf: () => void }) {
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
        <h2 className="mb-3 text-[18px] font-bold tracking-[-0.04em] text-[#34463a]">今日心情</h2>
        <div className="flex items-center justify-between">
          {MOODS.map(mood => {
            const selected = activeMood === mood.id
            return <button key={mood.id} aria-label={mood.label} onClick={() => { setActiveMood(mood.id); setMoodMotion(n => n + 1) }} className="grid h-[55px] w-[55px] place-items-center bg-transparent text-[43px] leading-none transition-transform active:scale-90" style={{ transform: selected ? 'translateY(-4px) scale(1.12)' : undefined, filter: selected ? 'drop-shadow(0 5px 5px rgba(49,86,60,0.24))' : 'drop-shadow(0 2px 3px rgba(67,75,57,0.10))' }}>{mood.emoji}</button>
          })}
        </div>
      </section>

      <section className="shrink-0 px-5 pb-8 pt-3">
        <div className="mb-3 flex items-center justify-between"><h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-[-0.02em] text-[#26372c]"><span className="h-2 w-2 rounded-full bg-[#d6bded]"/>为你准备</h2><button className="text-[11px] font-semibold text-[#477950]">查看全部 ↗</button></div>
        <div className="grid grid-cols-2 gap-3">
          <button onClick={onGoShelf} className="relative h-[178px] overflow-hidden rounded-[25px] border-2 border-white bg-[#f3b18e] p-4 text-left shadow-[0_5px_0_#d7876c] transition-transform active:translate-y-1 active:shadow-none"><div aria-hidden="true" className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-[#f9e58d]"/><div aria-hidden="true" className="absolute -left-8 bottom-4 h-12 w-16 rotate-[-25deg] rounded-full bg-[#cf92e8]/60"/><span className="relative text-[10px] font-semibold text-[#7f3328]">轻盈计划</span><p className="relative mt-1 text-lg font-bold leading-none tracking-[-0.04em] text-[#522d27]">减脂餐</p><p className="relative mt-1 max-w-[95px] text-[10px] font-medium leading-snug text-[#794f45]">健康轻食食材推荐</p><div className="absolute -bottom-5 right-[-3px] scale-[0.86]"><DietBowlSVG /></div></button>
          <button onClick={onGoShelf} className="relative h-[178px] overflow-hidden rounded-[25px] border-2 border-white bg-[#c3e493] p-4 text-left shadow-[0_5px_0_#90b567] transition-transform active:translate-y-1 active:shadow-none"><div aria-hidden="true" className="absolute -left-5 -top-5 h-20 w-20 rounded-full bg-[#f7e666]"/><div aria-hidden="true" className="absolute right-4 top-12 h-12 w-5 rotate-[35deg] rounded-full bg-[#bca8ec]/70"/><span className="relative text-[10px] font-semibold text-[#356234]">当季鲜选</span><p className="relative mt-1 text-lg font-bold leading-none tracking-[-0.04em] text-[#244c2c]">生鲜采买</p><p className="relative mt-1 max-w-[95px] text-[10px] font-medium leading-snug text-[#527151]">当季食材一键备货</p><div className="absolute -bottom-5 right-[-4px] scale-[0.86]"><BasketSVG /></div></button>
        </div>
      </section>
      </div>
    </div>
  )
}

// ── Shelf Screen ──────────────────────────────────────────────
function ProductCard({ p, onAdd }: { p: typeof PRODUCTS[0]; onAdd: () => void }) {
  const [added, setAdded] = useState(false)
  const [liked, setLiked] = useState(false)
  function handle() {
    setAdded(true); onAdd()
    setTimeout(() => setAdded(false), 1400)
  }
  return (
    <article className="group flex flex-col overflow-hidden rounded-[22px] border border-black/[0.06] bg-white transition-colors duration-200 hover:border-black/[0.13]">
      <div className="relative aspect-[1/0.91] overflow-hidden bg-[#f2f2f4]">
        <img src={p.img} alt={p.name} className="h-full w-full object-cover" loading="lazy" />
        <span className="absolute left-3 top-3 rounded-md bg-white/95 px-2 py-1 text-[9px] font-medium tracking-[0.02em] text-[#5f655f]">产地可溯源</span>
        <button onClick={() => setLiked(v => !v)} aria-label={liked ? `取消收藏${p.name}` : `收藏${p.name}`} className="absolute right-3 top-3 grid h-8 w-8 place-items-center rounded-full bg-white/95 text-[15px] text-[#4c554c] transition active:scale-90">{liked ? '♥' : '♡'}</button>
      </div>
      <div className="flex flex-col gap-1.5 px-4 pb-4 pt-3.5">
        <p className="line-clamp-2 text-[14px] font-semibold leading-tight text-[#20211f]">{p.name}</p>
        <div className="flex items-center gap-1 text-[10px] font-medium tracking-[0.01em] text-[#8a8d85]"><span className="text-[#d98a37]">★</span> 4.9 <span className="text-[#c7c8c1]">·</span> 今日采摘</div>
        <div className="mt-1.5 flex items-center justify-between">
          <span className="text-[15px] font-extrabold tracking-tight text-[#171816]" style={{ fontFamily: "'Instrument Sans', 'Noto Sans SC', sans-serif" }}>
            ¥{p.price.toFixed(2)}
            <em className="ml-1 text-[10px] not-italic font-medium text-[#94968f]">/{p.unit}</em>
          </span>
          <button
            onClick={handle}
            aria-label={`添加${p.name}到购物车`}
            className={`flex h-8 w-8 items-center justify-center rounded-full transition-all duration-200 active:scale-90 ${added ? 'bg-[#f3e7c9]' : 'bg-[#191a18]'}`}
          >
            {added
              ? <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#16A34A" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12" /></svg>
              : <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
            }
          </button>
        </div>
      </div>
    </article>
  )
}

function ShelfScreen({ cartCount, onAdd }: { cartCount: number; onAdd: () => void }) {
  const [activeCat, setActiveCat] = useState(CATEGORY_SYSTEM[0].id)
  const [activeSub, setActiveSub] = useState('全部')
  const [search, setSearch] = useState('')
  const catData = CATEGORY_SYSTEM.find(c => c.id === activeCat)!

  return (
    <div className="flex h-full flex-col overflow-hidden bg-[#f5f5f7]">
      <header className="z-10 flex-shrink-0 border-b border-black/[0.05] bg-[#f5f5f7] px-5 pb-3 pt-5">
        <div className="mb-4 flex items-center justify-between">
          <button className="flex items-center gap-1 text-[18px] font-extrabold tracking-[-0.07em] text-[#22231f]">静安区 <span className="mt-0.5 text-[11px] font-semibold text-black/35">⌄</span></button>
          <div className="flex items-center gap-2">
            <button aria-label="通知" className="grid h-9 w-9 place-items-center rounded-full bg-white text-[#626560] transition active:scale-90"><IconBell /></button>
            <button aria-label="购物车" className="relative grid h-9 w-9 place-items-center rounded-full bg-[#1d1d1f] text-white transition active:scale-90">
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
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索有机食材与好物" className="w-full rounded-2xl bg-white py-3.5 pl-10 pr-4 text-xs font-semibold text-[#30312d] outline-none transition placeholder:text-[#9a9a91] focus:ring-2 focus:ring-[#8ebc9a]" />
        </div>
      </header>

      <div className="z-10 flex-shrink-0 px-5 pt-3">
        <div className="flex gap-2 overflow-x-auto py-3 scrollbar-hide">
          {CATEGORY_SYSTEM.map((cat) => {
            const isActive = cat.id === activeCat
            return (
              <button
                key={cat.id}
                onClick={() => { setActiveCat(cat.id); setActiveSub('全部') }}
                aria-pressed={isActive}
                className={`group relative flex w-[68px] flex-shrink-0 flex-col items-center gap-2 bg-transparent pb-1 outline-none transition duration-200 ease-out active:scale-[0.98] focus-visible:rounded-2xl focus-visible:ring-2 focus-visible:ring-[#78917d] focus-visible:ring-offset-2 focus-visible:ring-offset-[#f5f5f7] ${isActive ? '-translate-y-0.5' : 'hover:-translate-y-px'}`}
              >
                <span className={`grid h-[58px] w-[58px] place-items-center rounded-[20px] bg-[#f5f5f7] transition-all duration-200 ${isActive ? 'shadow-[0_5px_10px_rgba(29,29,31,0.12),0_1px_2px_rgba(29,29,31,0.06)]' : 'shadow-[0_0_0_1px_rgba(245,245,247,0.6)] group-hover:shadow-[0_3px_7px_rgba(29,29,31,0.05)]'}`}>
                  <span className={`text-[30px] leading-none transition-transform duration-200 ${isActive ? 'scale-[1.04]' : 'grayscale-[0.08] group-hover:scale-[1.02]'}`}>
                    {cat.icon}
                  </span>
                </span>
                <span className={`relative w-full truncate text-center text-[12px] font-semibold tracking-[-0.05em] transition-colors duration-200 ${isActive ? 'text-[#252622]' : 'text-[#8c8d87] group-hover:text-[#596158]'}`}>
                  {cat.label.replace('蔬菜豆制品', '蔬菜').replace('肉禽蛋水产', '肉蛋').replace('乳品饮料', '乳品')}
                  <span aria-hidden="true" className={`absolute -bottom-1.5 left-1/2 h-[2px] -translate-x-1/2 rounded-full bg-[#252622] transition-all duration-300 ${isActive ? 'w-4 opacity-100' : 'w-0 opacity-0'}`} />
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="z-10 flex-shrink-0 px-5 pt-2">
        <div className="flex gap-2 overflow-x-auto scrollbar-hide pb-2">
          {catData.sub.map(sub => {
            const isActive = sub === activeSub
            return (
              <button key={sub} onClick={() => setActiveSub(sub)} className={`flex-shrink-0 rounded-full px-3.5 py-2 text-[11px] font-semibold transition duration-200 active:scale-95 ${isActive ? 'bg-[#1d1d1f] text-white' : 'border border-black/[0.08] bg-transparent text-[#73746e]'}`}>
                {sub === '全部' ? '全部好物' : sub}
              </button>
            )
          })}
        </div>
      </div>

      <div className="z-10 flex-1 overflow-y-auto scrollbar-hide px-5 pt-4 pb-6">
        {!search && activeSub === '全部' && (
          <section className="mb-6">
            <div className="mb-3 flex items-center justify-between"><h2 className="text-[19px] font-semibold tracking-[-0.06em] text-[#202124]">今日精选</h2><button aria-label="查看今日精选" className="grid h-8 w-8 place-items-center rounded-full bg-white text-sm text-[#1d1d1f] transition active:scale-90">→</button></div>
            <div className="grid grid-cols-2 gap-3">
              <div className="relative h-[7.25rem] overflow-hidden rounded-[20px] bg-[#31533a] p-3.5 text-white"><img src="https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=500&h=300&fit=crop&auto=format" alt="新鲜有机蔬菜" className="absolute inset-0 h-full w-full object-cover"/><div className="absolute inset-0 bg-gradient-to-r from-[#173321]/85 via-[#173321]/42 to-transparent"/><p className="relative text-[10px] font-semibold text-[#d9efbd]">绿色餐桌计划</p><p className="relative mt-1 text-sm font-bold leading-tight tracking-[-0.04em]">有机蔬菜<br/>全场 88 折</p></div>
              <div className="relative h-[7.25rem] overflow-hidden rounded-[20px] bg-[#754434] p-3.5 text-white"><img src="https://images.unsplash.com/photo-1603048297172-c92544798d5a?w=500&h=300&fit=crop&auto=format" alt="新鲜生姜与肉类食材" className="absolute inset-0 h-full w-full object-cover"/><div className="absolute inset-0 bg-gradient-to-r from-[#4f251d]/85 via-[#4f251d]/42 to-transparent"/><p className="relative text-[10px] font-semibold text-[#ffe0c5]">限时会员价</p><p className="relative mt-1 text-sm font-bold leading-tight tracking-[-0.04em]">牧场鲜肉<br/>买二减一</p></div>
            </div>
          </section>
        )}
        <div className="mb-3 flex items-end justify-between"><div><h2 className="text-[19px] font-semibold tracking-[-0.06em] text-[#202124]">{search ? '搜索结果' : '人气鲜品'}</h2><p className="mt-0.5 text-[10px] font-medium tracking-[0.02em] text-[#7c7c80]">最快 30 分钟送达</p></div><button className="rounded-full border border-black/[0.08] bg-transparent px-3.5 py-2 text-[10px] font-medium text-[#505055] transition active:scale-95">综合排序⌄</button></div>
        <div className="grid grid-cols-2 gap-3">
          {PRODUCTS.filter(p =>
            p.catId === activeCat && (!search || p.name.includes(search))
          ).map(p => (
            <ProductCard key={p.id} p={p} onAdd={onAdd} />
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Chat Screen ───────────────────────────────────────────────
function ChatScreen() {
  const [msgs, setMsgs] = useState<Msg[]>(INITIAL_MSGS)
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, typing])

  function send(text: string) {
    if (!text.trim()) return
    setMsgs(p => [...p, { id: Date.now(), role: 'user', text: text.trim() }])
    setInput('')
    setTyping(true)
    setTimeout(() => {
      setTyping(false)
      setMsgs(p => [...p, simulateReply(text)])
    }, 900 + Math.random() * 600)
  }

  return (
    <section className="chat-panel-enter flex h-[min(71vh,650px)] min-h-[500px] flex-col overflow-hidden rounded-t-[38px] bg-[#fcfbf8] font-sans shadow-[0_-20px_60px_rgba(40,36,29,0.12)]">
      <div className="flex justify-center bg-[#f7f5f0] pt-3 pb-1.5" aria-hidden="true"><span className="h-1 w-10 rounded-full bg-black/[.12]" /></div>
      {/* Header */}
      <div className="flex flex-shrink-0 items-center gap-3 bg-[#f7f5f0] px-6 pt-2 pb-5">
        <KekeAvatar size={40} animated />
        <div>
          <p className="text-[15px] font-semibold tracking-[-0.04em] text-[#191817]">可可</p>
        </div>
        <button
          onClick={() => { setMsgs(INITIAL_MSGS); setInput('') }}
          className="ml-auto grid h-9 w-9 place-items-center rounded-full bg-white/70 text-black/48 transition hover:bg-white active:scale-95"
          aria-label="发起新对话">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
        </button>
      </div>

      {/* Messages */}
      <div className="scrollbar-hide flex-1 space-y-5 overflow-y-auto px-6 py-5">
        <div className="text-center text-[10px] font-medium tracking-[0.08em] text-black/25">今天 · 14:32</div>
        {msgs.map(msg => (
          <div key={msg.id} className={`flex items-end gap-2.5 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
            {msg.role === 'ai' && <KekeAvatar size={26} />}
            <div className={`flex max-w-[82%] flex-col gap-2.5 ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
              <div className="px-4 py-3 text-[13px] font-medium leading-[1.7] tracking-[-0.015em]"
                style={{
                  borderRadius: msg.role === 'user' ? '24px 24px 8px 24px' : '24px 24px 24px 8px',
                  background: msg.role === 'user' ? '#171716' : '#f2f1ed',
                  color: msg.role === 'user' ? '#fff' : '#292825',
                }}>
                {formatText(msg.text)}
              </div>
              {msg.suggestions && msg.role === 'ai' && (
                <div className="flex w-full flex-col gap-1.5">
                  {msg.suggestions.map((s, i) => (
                    <button key={i} onClick={() => send(s)} className="rounded-full bg-[#f5f4f0] px-4 py-2.5 text-left text-[12px] font-medium text-black/55 transition hover:bg-[#eceae4] active:scale-[.98]">
                      <span className="mr-2 text-[10px] font-semibold text-[#d79b58]">✦</span>
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {typing && (
          <div className="flex items-end gap-2.5">
            <KekeAvatar size={26} />
            <div className="flex gap-1 rounded-[22px] rounded-bl-[8px] bg-[#f2f1ed] px-4 py-3">
              {[0, 1, 2].map(i => (
                <span key={i} className="typing-dot h-1.5 w-1.5 rounded-full bg-black/30" style={{ animationDelay: `${i * 0.2}s` }} />
              ))}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex-shrink-0 bg-[#f7f5f0] px-5 py-4">
        <div className="flex items-center gap-2 rounded-[28px] bg-white px-4 py-2.5 shadow-[0_1px_0_rgba(0,0,0,.03)]">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') send(input) }}
            placeholder="问问可可吧…"
            className="min-w-0 flex-1 bg-transparent text-[13px] font-medium text-[#1d1c1a] outline-none placeholder:text-black/30"
          />
          <button onClick={() => send(input)} disabled={!input.trim() || typing}
            className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full transition-all active:scale-90 ${input.trim() && !typing ? 'bg-[#171716]' : 'bg-[#eeece7]'}`}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="white"><path d="M2 21L23 12 2 3v7l15 2-15 2z" /></svg>
          </button>
        </div>
      </div>
    </section>
  )
}

// ── Orders Screen ─────────────────────────────────────────────
const ORDERS = [
  { id: '#CE2406', date: '今天 14:32', status: '配送中', items: ['有机西兰花 × 2', '三文鱼 × 1'], total: 88.50 },
  { id: '#CE2405', date: '昨天 10:15', status: '已完成', items: ['草莓 × 1', '牛奶 × 2'], total: 57.80 },
  { id: '#CE2404', date: '2天前 19:08', status: '已完成', items: ['鸡蛋 × 1', '红甜椒 × 2', '生姜 × 1'], total: 67.65 },
]

function OrdersScreen() {
  return (
    <div className="flex h-full flex-col bg-[#fcfbf8]">
      <div className="flex-shrink-0 px-6 pt-10 pb-4">
        <div className="flex items-end justify-between"><h2 className="text-[26px] font-semibold tracking-[-0.07em] text-[#191817]">我的订单</h2><span className="mb-1 text-[11px] font-medium text-black/35">近 30 天</span></div>
      </div>
      <div className="scrollbar-hide flex-1 space-y-3 overflow-y-auto px-5 pb-5">
        <div className="rounded-[30px] bg-[#f2f1ed] p-5">
          <div className="flex items-center justify-between">
            <div><p className="text-[11px] font-medium text-black/40">当前进度</p><p className="mt-1 text-[17px] font-semibold tracking-[-0.045em] text-[#1d1c1a]">配送员正在路上</p></div>
            <span className="rounded-full bg-[#f7e8a7] px-3 py-1.5 text-[10px] font-semibold text-[#735a13]">预计 16:10</span>
          </div>
          <div className="mt-5 flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#30302c]" /><span className="h-[2px] flex-1 bg-[#30302c]" /><span className="h-2 w-2 rounded-full bg-[#30302c]" /><span className="h-[2px] flex-1 bg-black/[.09]" /><span className="h-2 w-2 rounded-full bg-black/[.12]" /></div>
          <div className="mt-2 flex justify-between text-[10px] font-medium text-black/35"><span>已接单</span><span>备货完成</span><span>送达</span></div>
        </div>
        <div className="px-2 pt-1 text-[10px] font-medium tracking-[0.12em] text-black/30">RECENT ORDERS</div>
        {ORDERS.map((order, index) => (
          <button key={order.id} className="w-full rounded-[26px] bg-[#f7f6f2] p-4 text-left transition hover:bg-[#f2f1ed] active:scale-[.985]">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2"><span className="text-[13px] font-semibold tracking-[-0.02em] text-[#252421]">{order.id}</span><span className="text-[10px] font-medium text-black/32">{order.date}</span></div>
              <span className={`rounded-full px-2.5 py-1 text-[10px] font-medium ${order.status === '配送中' ? 'bg-[#f7e8a7] text-[#735a13]' : 'bg-white/70 text-black/38'}`}>
                {order.status}
              </span>
            </div>
            <p className="text-[12px] leading-relaxed text-black/52">{order.items.join(' · ')}</p>
            <div className="flex items-center justify-between">
              <span className="mt-3 text-[10px] font-medium text-black/28">{index === 0 ? '查看配送详情' : '查看订单详情'} →</span>
              <span className="mt-3 text-[14px] font-semibold tracking-[-0.03em] text-[#1d1c1a]">¥{order.total.toFixed(2)}</span>
            </div>
          </button>
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
        <h2 className="text-[26px] font-semibold tracking-[-0.07em] text-[#191817]">个人中心</h2>
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
type ViewState = 'home' | 'shelf' | 'keke' | 'orders' | 'profile'

interface NavItem {
  id: string
  label: string
  icon: (active: boolean) => React.ReactNode
  isKeke?: boolean
}

function BottomNav({ view, onTap }: { view: ViewState; onTap: (id: string) => void }) {
  const onShelfCtx = view === 'shelf' || view === 'keke'

  const tab2: NavItem = onShelfCtx
    ? { id: 'keke',  label: view === 'keke' ? '自己逛逛' : '问问可可', isKeke: true,  icon: () => <KekeAvatar size={20} /> }
    : { id: 'shelf', label: '商品',     isKeke: false, icon: (a) => <IconGrid filled={a} /> }

  const tabs: NavItem[] = [
    { id: 'home',    label: '主页',   icon: (a) => <IconHome filled={a} /> },
    tab2,
    { id: 'orders',  label: '订单',   icon: (a) => <IconOrders filled={a} /> },
    { id: 'profile', label: '个人中心', icon: (a) => <IconUser filled={a} /> },
  ]

  function isActive(id: string) {
    if (id === 'home')    return view === 'home'
    if (id === 'shelf')   return view === 'shelf'
    if (id === 'keke')    return view === 'keke'
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
          const expanded = active || isKeke
          return (
            <button key={tab.id} onClick={() => onTap(tab.id)}
              className="flex h-10 items-center justify-center transition-all duration-300 ease-out active:scale-90"
              style={{
                borderRadius: 999,
                gap: expanded ? 6 : 0,
                padding: expanded ? (isKeke ? '7px 14px 7px 9px' : '7px 14px') : '9px',
                background: isKeke
                  ? (active ? '#E9C96F' : '#FFF3C9')
                  : (active ? '#39714B' : 'transparent'),
                color: active
                  ? (isKeke ? '#4E3D12' : 'white')
                  : (isKeke ? '#9D7B22' : '#91A097'),
                boxShadow: isKeke ? (active ? '0 4px 10px rgba(191,151,52,0.24)' : 'inset 0 0 0 1px rgba(220,185,75,0.22)') : 'none',
              }}>
              {tab.icon(active && !isKeke)}
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
  const [cartCount, setCartCount] = useState(2)

  function handleNavTap(id: string) {
    if (id === 'home')    { setView('home'); return }
    if (id === 'orders')  { setView('orders'); return }
    if (id === 'profile') { setView('profile'); return }
    // Tab 2 context-sensitive
    if (id === 'shelf') setView('shelf')
    if (id === 'keke')  { setView(v => v === 'keke' ? 'shelf' : 'keke') }
  }

  return (
    <main className="min-h-screen bg-[#eaf1ed] p-0 sm:p-8" style={{ fontFamily: "'Noto Sans SC', 'Manrope', system-ui, sans-serif" }}>
      <div className="relative mx-auto flex min-h-screen w-full max-w-[430px] flex-col overflow-hidden bg-[#F5F5F7] sm:min-h-[min(860px,calc(100vh-64px))] sm:rounded-[32px] sm:shadow-[0_24px_70px_rgba(38,64,51,0.16)]"
        style={{
          height: '100dvh',
        }}>
        {/* Screen */}
        <div className="flex-1 overflow-hidden flex flex-col">
          {view === 'home'    && <LandingScreen onGoShelf={() => setView('shelf')} />}
          {(view === 'shelf' || view === 'keke') && <ShelfScreen cartCount={cartCount} onAdd={() => setCartCount(c => c + 1)} />}
          {view === 'orders'  && <OrdersScreen />}
          {view === 'profile' && <ProfileScreen />}
        </div>

        {/* Bottom nav */}
        <BottomNav view={view} onTap={handleNavTap} />
        {view === 'keke' && (
          <div className="absolute inset-x-0 bottom-[82px] top-0 z-10 flex flex-col justify-end bg-[#18261b]/20 backdrop-blur-[1px]">
            <ChatScreen />
          </div>
        )}
      </div>
    </main>
  )
}
