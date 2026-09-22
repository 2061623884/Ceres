# Plan: Ceres — Home Redesign + Context-Sensitive Nav

## Context

The user wants a dynamic nav bar that swaps Tab 2 based on the current screen context:

- **When NOT on shelf** → `[主页, 商品, 订单, 个人中心]`
- **When ON shelf** → `[主页, 问问可可, 订单, 个人中心]` ← Tab 2 becomes Keke AI

This enables the "看着商品询问AI导购" (browse products + ask AI) UX pattern: the user browses the shelf, then taps Tab 2 which has transformed into 问问可可, opening the AI chat in the same context without losing their place.

Additionally, Tab 1 (首页) is redesigned from a product shelf into a new landing screen: cartoon mascot + daily mood + activity cards.

---

## State Machine

Single `viewState` string drives everything:

```
'home'              → LandingScreen   | nav: [主页*, 商品,  订单,  个人中心]
'shelf'             → ShelfScreen     | nav: [主页,  可可*†, 订单,  个人中心]  ← Tab2 = 可可
'keke'              → ChatScreen      | nav: [主页,  可可*, 订单,  个人中心]   ← Tab2 active
'orders'            → OrdersScreen    | nav: [主页,  商品,  订单*, 个人中心]
'profile'           → ProfileScreen   | nav: [主页,  商品,  订单,  个人中心*]
```
`*` = active (expanded pill). `†` = Tab2 label/icon becomes 可可 while on shelf.

### Nav tap logic

| Tap | Current state | Result |
|---|---|---|
| Tab 1 主页 | any | → `'home'` |
| Tab 2 商品/可可 | `'home'`, `'orders'`, `'profile'` | → `'shelf'` |
| Tab 2 商品/可可 | `'shelf'` | → `'keke'` |
| Tab 2 商品/可可 | `'keke'` | → `'keke'` (already active) |
| Tab 3 订单 | any | → `'orders'` |
| Tab 4 个人中心 | any | → `'profile'` |

Tab 2's label and icon swap dynamically:
- `viewState === 'shelf' || viewState === 'keke'` → show KekeAvatar + "问问可可" (purple)
- otherwise → show IconGrid + "商品" (green when active)

---

## Changes to `src/App.tsx`

### 1. Replace `Tab` type + `activeTab` state

```ts
type ViewState = 'home' | 'shelf' | 'keke' | 'orders' | 'profile'
const [view, setView] = useState<ViewState>('home')
```

### 2. Compute nav tab 2 dynamically

```ts
const onShelfContext = view === 'shelf' || view === 'keke'

const NAV_TAB2 = onShelfContext
  ? { id: 'keke',  label: '问问可可', isKeke: true,  icon: ... }
  : { id: 'shelf', label: '商品',     isKeke: false, icon: ... }
```

Build the 4-item tab array at render time with `NAV_TAB2` at index 1.

### 3. BottomNav tap handler

```ts
function handleNavTap(id: string) {
  if (id === 'home')    setView('home')
  if (id === 'orders')  setView('orders')
  if (id === 'profile') setView('profile')
  if (id === 'shelf')   setView('shelf')  // Tab2 when not on shelf context
  if (id === 'keke')    setView('keke')   // Tab2 when on shelf context
}
```

Active tab highlight logic:
- Tab 1 active when `view === 'home'`
- Tab 2 active when `view === 'shelf' || view === 'keke'`
- Tab 3 active when `view === 'orders'`
- Tab 4 active when `view === 'profile'`

### 4. Screen render switch

```tsx
{view === 'home'    && <LandingScreen onGoShelf={() => setView('shelf')} />}
{view === 'shelf'   && <ShelfScreen cartCount={cartCount} onAdd={...} />}
{view === 'keke'    && <ChatScreen onAddToCart={...} />}
{view === 'orders'  && <OrdersScreen />}
{view === 'profile' && <ProfileScreen />}
```

`ShelfScreen` and `ChatScreen` are siblings sharing the same `view` slot — no back button needed since Tab 2 itself is the toggle.

### 5. New `LandingScreen` (首页)

Inspired by image-10 wellness app, adapted for Ceres brand:

**Background**: soft mint `#EFF7F1`

**Layout:**
```
[avatar] Hi 🌿 Ceres 用户        [🔔 bell]
早上好，今天吃点什么？  (bold 22px)

      [CeresMascot size=110, centered]
   ╭─ speech bubble: "今天想吃什么？" ─╮

今天心情怎么样？
[ 😡 ]  [ 😕 ]  [ 😐 ]  [ 🙂 ]  [ 😍 ]
(tappable, activeMood state, selected = green ring)

活动
┌──────────────┐  ┌──────────────┐
│  减脂餐      │  │  生鲜采买    │
│  [SVG bowl]  │  │  [SVG basket]│
│  健康轻食    │  │  当季备货    │
└──────────────┘  └──────────────┘
```

**Activity card tap**: both call `onGoShelf()` → `setView('shelf')`

**Illustration SVGs (inline in LandingScreen):**

`DietBowlSVG` — ~110×110: white bowl on a plate circle, green leafy mound fill, 2 red cherry tomatoes, yellow lemon wedge slice, small 4-pointed star sparkles in #FFD166. Soft shadow circle underneath.

`BasketSVG` — ~110×110: tan wicker basket body with crosshatch weave lines, orange carrot peeking over the rim (green feathery top), dark leafy greens overflowing left side, small radish, same star sparkles.

Both in a flat, slightly chunky illustration style matching the Ceres mascot.

### 6. Rename `HomeScreen` → `ShelfScreen`

Same component body, renamed. Remove any back-button prop (not needed since nav handles navigation).

---

## Files Modified

- `src/App.tsx` only

## Verification

1. App loads → 首页 shows mascot + mood emojis + 2 activity cards; nav = [主页*, 商品, 订单, 个人中心]
2. Tap "生鲜采买" card → shelf opens; nav changes to [主页, 可可†, 订单, 个人中心] (Tab2 now purple Keke)
3. Tap Tab2 (可可) while on shelf → chat screen opens; Tab2 stays active/highlighted
4. Tap Tab1 (主页) from chat → returns home; nav reverts to [主页*, 商品, 订单, 个人中心]
5. Tap Tab2 (商品) from home → shelf again; Tab2 becomes 可可
6. Tap Tab3 订单 / Tab4 我的 from anywhere → correct screens; nav shows 商品 at Tab2
7. Mood emoji tap shows selected state (green ring highlight)
8. All 4 nav pill expansions animate correctly
