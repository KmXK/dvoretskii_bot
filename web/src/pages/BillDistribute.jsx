import { useState, useEffect, useLayoutEffect, useMemo, useRef, useCallback, forwardRef, useImperativeHandle } from 'react'
import { motion, animate, useMotionValue, useTransform, useSpring, AnimatePresence } from 'framer-motion'
import * as Dialog from '@radix-ui/react-dialog'
import { ChevronLeft, Pencil, X, Check, Undo2, PartyPopper, Scissors, RotateCcw, Merge, Trash2, ListChecks, Users } from 'lucide-react'
import { api } from '../api/client'

// ── Money ─────────────────────────────────────────────────────────────────────

const CURRENCY_SYMBOLS = { BYN: 'р', RUB: '₽', USD: '$', EUR: '€', UAH: '₴' }
const CURRENCY_PREFIX = new Set(['USD', 'EUR'])

function formatMinor(minor, currency = 'BYN') {
  const sign = minor < 0 ? '-' : ''
  const abs = Math.abs(minor)
  const rubles = Math.floor(abs / 100)
  const kop = abs % 100
  const amt = kop === 0 ? `${rubles}` : `${rubles}.${String(kop).padStart(2, '0')}`
  const sym = CURRENCY_SYMBOLS[currency] || currency
  return CURRENCY_PREFIX.has(currency) ? `${sign}${sym}${amt}` : `${sign}${amt} ${sym}`
}

// Match steward/helpers/bills_money.compute_bill_debts (half-up).
function piecesCost(unitPrice, count, den) {
  return Math.floor((unitPrice * count + Math.floor(den / 2)) / den)
}

const fracLabel = (den) => (den > 1 ? `1/${den}` : '1 шт')

const gcd = (a, b) => { a = Math.abs(a); b = Math.abs(b); while (b) { [a, b] = [b, a % b] } return a || 1 }
const lcm = (a, b) => (a / gcd(a, b)) * b

function hueFor(txId) {
  let h = 0
  for (let i = 0; i < txId.length; i++) h = (h * 31 + txId.charCodeAt(i)) % 360
  return h
}
function cardGradient(txId) {
  const hue = hueFor(txId)
  return `linear-gradient(135deg, hsl(${hue} 70% 64%), hsl(${hue} 72% 52%))`
}

// Приглушённый персональный цвет ноды по id человека.
function personTint(pid) {
  const hue = hueFor(pid)
  return { bg: `hsl(${hue} 42% 26%)`, border: `hsl(${hue} 55% 52%)`, fg: `hsl(${hue} 70% 86%)` }
}

// Короткий алиас для ноды: первое слово, обрезанное — чтобы все ноды были одного
// размера независимо от длины ника.
function nodeAlias(name) {
  const first = (name || '?').trim().split(/\s+/)[0] || '?'
  return first.length > 9 ? `${first.slice(0, 8)}…` : first
}

// ── Cards model ───────────────────────────────────────────────────────────────
// One ordered, flat deck of "cards". Each card is a 1/den fraction of one unit of
// a transaction, owned by a person or null (still in the deck). deck[0] is the top.

let _seq = 0
const nextId = () => `pc${++_seq}`

function billToCards(bill) {
  const cards = []
  for (const tx of bill.transactions) {
    let covered = 0
    for (const asg of tx.assignments || []) {
      const den = asg.denominator || 1
      const debtors = asg.debtors || []
      if (debtors.length === 0) {
        for (let k = 0; k < asg.unit_count; k++) cards.push({ id: nextId(), txId: tx.id, den, owner: null })
        covered += asg.unit_count / den
      } else if (debtors.length === 1) {
        for (let k = 0; k < asg.unit_count; k++) cards.push({ id: nextId(), txId: tx.id, den, owner: debtors[0] })
        covered += asg.unit_count / den
      } else {
        const subDen = den * debtors.length
        for (const d of debtors) {
          for (let k = 0; k < asg.unit_count; k++) cards.push({ id: nextId(), txId: tx.id, den: subDen, owner: d })
        }
        covered += asg.unit_count / den
      }
    }
    const remainder = Math.round(tx.quantity - covered)
    for (let k = 0; k < Math.max(0, remainder); k++) cards.push({ id: nextId(), txId: tx.id, den: 1, owner: null })
  }
  return cards
}

function groupAssignments(cards) {
  const g = {}
  for (const c of cards) {
    const key = `${c.owner || ''}|${c.den}`
    if (!g[key]) g[key] = { owner: c.owner, den: c.den, count: 0 }
    g[key].count += 1
  }
  return Object.values(g).map((x) => ({
    unit_count: x.count, debtors: x.owner ? [x.owner] : [], denominator: x.den,
  }))
}

const CARD_W = 150
const CARD_H = 128
const POSE_SPRING = { type: 'spring', stiffness: 340, damping: 26 }
const DRAG_SCALE = 0.72 // карта уменьшается при подъёме, чтобы видеть ноды

// ── Фон: дрейфующие частицы (антураж меню) ─────────────────────────────────────

function ParticleField() {
  const ref = useRef(null)
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const dpr = window.devicePixelRatio || 1
    let raf = 0
    let dots = []
    const seed = () => {
      const w = canvas.width = canvas.offsetWidth * dpr
      const h = canvas.height = canvas.offsetHeight * dpr
      const n = 34
      dots = Array.from({ length: n }, () => ({
        x: Math.random() * w, y: Math.random() * h,
        r: (Math.random() * 1.6 + 0.5) * dpr,
        vx: (Math.random() - 0.5) * 0.12 * dpr,
        vy: (Math.random() - 0.5) * 0.12 * dpr,
        a: Math.random() * 0.35 + 0.08,
        gold: Math.random() > 0.5,
      }))
    }
    seed()
    const tick = () => {
      const w = canvas.width, h = canvas.height
      ctx.clearRect(0, 0, w, h)
      for (const d of dots) {
        d.x += d.vx; d.y += d.vy
        if (d.x < 0) d.x += w; if (d.x > w) d.x -= w
        if (d.y < 0) d.y += h; if (d.y > h) d.y -= h
        ctx.beginPath()
        ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2)
        ctx.fillStyle = d.gold ? `rgba(214,178,112,${d.a})` : `rgba(129,140,248,${d.a})`
        ctx.fill()
      }
      raf = requestAnimationFrame(tick)
    }
    tick()
    window.addEventListener('resize', seed)
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', seed) }
  }, [])
  return <canvas ref={ref} className="absolute inset-0 w-full h-full pointer-events-none opacity-70" />
}

// ── Визуал карты (общий для колоды и FX) ───────────────────────────────────────

function CardFace({ tx, den, currency, footer, onRename }) {
  const unitPrice = den > 1 ? piecesCost(tx?.unit_price_minor || 0, 1, den) : (tx?.unit_price_minor || 0)
  return (
    <>
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold text-sm leading-tight line-clamp-2">{tx?.item_name}</div>
        {onRename && (
          <button onClick={onRename} className="shrink-0 opacity-70 hover:opacity-100"><Pencil size={13} /></button>
        )}
      </div>
      <div className="text-3xl font-bold tabular-nums my-2">{fracLabel(den)}</div>
      <div className="text-[11px] opacity-80 tabular-nums">
        {formatMinor(unitPrice, currency)}{footer ? ` · ${footer}` : ''}
      </div>
    </>
  )
}

// ── PileCard ──────────────────────────────────────────────────────────────────
// Все видимые карты — один компонент, keyed by id; смена глубины спрингует тот же
// элемент (без ремоунта/вспышки). Тащится только верхняя; при отпускании летит в
// ближайшую ноду графа.

const PileCard = forwardRef(function PileCard(
  { card, depth, isTop, draggable, dimmed, anchor, tx, currency, remaining, resolveDrop,
    onAssign, onDefer, onSplit, onMerge, onRename, onDragStartCard, onDragMoveCard, onDragEndCard }, ref,
) {
  const nodeRef = useRef(null)
  const dragging = useRef(false)
  const x = useMotionValue((depth % 2 ? 1 : -1) * depth * 12)
  const y = useMotionValue(0)
  const scale = useMotionValue(0.5)
  const opacity = useMotionValue(0)
  const tilt = useMotionValue(0)
  const lean = useSpring(useTransform(x, [-220, 220], [-22, 22]), { stiffness: 260, damping: 18, mass: 0.6 })
  const rotate = useTransform([lean, tilt], ([l, t]) => l + t)

  useEffect(() => {
    const c = animate(opacity, 1, { duration: 0.22 })
    return () => c.stop()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (isTop && dragging.current) return
    const cs = animate(scale, isTop ? 1 : 1 - depth * 0.05, POSE_SPRING)
    const ct = animate(tilt, isTop ? 0 : (depth % 2 ? 1 : -1) * depth * 2, POSE_SPRING)
    const cy = animate(y, depth * 9, POSE_SPRING)
    const cx = animate(x, 0, POSE_SPRING)
    const co = animate(opacity, 1, POSE_SPRING)
    return () => { cs.stop(); ct.stop(); cy.stop(); cx.stop(); co.stop() }
  }, [depth, isTop]) // eslint-disable-line react-hooks/exhaustive-deps

  // Полупрозрачность при наведении на ноду — видно, кому отдаёшь.
  useEffect(() => {
    if (!dragging.current) return
    const c = animate(opacity, dimmed ? 0.4 : 1, { duration: 0.16 })
    return () => c.stop()
  }, [dimmed]) // eslint-disable-line react-hooks/exhaustive-deps

  const springHome = () => {
    animate(x, 0, { type: 'spring', stiffness: 300, damping: 24 })
    animate(y, depth * 9, { type: 'spring', stiffness: 300, damping: 24 })
    animate(scale, 1, { type: 'spring', stiffness: 300, damping: 20 })
    animate(opacity, 1, { duration: 0.2 })
  }

  const flingDown = (dir = -1) => {
    animate(x, dir * 460, { type: 'spring', stiffness: 200, damping: 28 })
    animate(opacity, 0, { duration: 0.32, onComplete: onDefer })
  }
  const absorb = (cb) => {
    animate(scale, 0.45, { duration: 0.16 })
    animate(opacity, 0.3, { duration: 0.18, onComplete: cb })
  }
  useImperativeHandle(ref, () => ({ flingDown, absorb }), [onDefer]) // eslint-disable-line react-hooks/exhaustive-deps

  const flyToRect = (rect, cb) => {
    const r = nodeRef.current?.getBoundingClientRect()
    if (r) {
      const cx = r.left + r.width / 2
      const cy = r.top + r.height / 2
      const tcx = rect.left + rect.width / 2
      const tcy = rect.top + rect.height / 2
      animate(x, x.get() + (tcx - cx), { type: 'spring', stiffness: 240, damping: 26 })
      animate(y, y.get() + (tcy - cy), { type: 'spring', stiffness: 240, damping: 26 })
    }
    animate(scale, 0.16, { duration: 0.3 })
    animate(opacity, 0, { duration: 0.34, onComplete: cb })
  }

  const handleDragEnd = (_e, info) => {
    dragging.current = false
    const drop = resolveDrop(info.point)
    onDragEndCard?.(drop)
    if (drop && (drop.kind === 'person' || drop.kind === 'defer')) {
      flyToRect(drop.rect, () => (drop.kind === 'defer' ? onDefer() : onAssign(drop.personId)))
      return
    }
    // делить/собрать: карта возвращается в колоду, действие запускает анимацию
    springHome()
    if (drop?.kind === 'split') onSplit?.()
    else if (drop?.kind === 'merge') onMerge?.()
  }

  const wrap = {
    position: 'absolute', left: anchor.x, top: anchor.y,
    width: CARD_W, marginLeft: -CARD_W / 2, marginTop: -CARD_H / 2, zIndex: 40 - depth,
  }
  return (
    <motion.div
      ref={nodeRef}
      drag={draggable}
      dragMomentum={false}
      onDragStart={() => { dragging.current = true; onDragStartCard?.(); animate(scale, DRAG_SCALE, { type: 'spring', stiffness: 300, damping: 22 }) }}
      onDrag={(_e, info) => onDragMoveCard?.(info.point)}
      onDragEnd={handleDragEnd}
      style={{ ...wrap, x, y, scale, opacity, rotate, background: cardGradient(card.txId), pointerEvents: draggable ? 'auto' : 'none' }}
      className={`select-none rounded-2xl px-4 py-5 shadow-xl shadow-black/50 text-black ${draggable ? 'touch-none cursor-grab' : ''}`}
    >
      <CardFace
        tx={tx}
        den={card.den}
        currency={currency}
        footer={isTop ? `${remaining} в колоде` : ''}
        onRename={isTop ? (e) => { e.stopPropagation(); onRename(card.txId, tx?.item_name || '') } : null}
      />
    </motion.div>
  )
})

// ── FX-слой: митоз и склейка ────────────────────────────────────────────────────

function FxLayer({ fx, tx, currency, anchor, onDone }) {
  const n = fx.type === 'split' ? fx.n : fx.count
  useEffect(() => {
    const t = setTimeout(onDone, fx.type === 'split' ? 560 + n * 110 : 520 + n * 110)
    return () => clearTimeout(t)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const base = {
    position: 'absolute', left: anchor.x, top: anchor.y, width: CARD_W,
    marginLeft: -CARD_W / 2, marginTop: -CARD_H / 2, background: cardGradient(fx.txId),
  }

  if (fx.type === 'split') {
    const childDen = fx.den * n
    // карта делится и по одной (последовательно) карты «возвращаются» в колоду
    return (
      <div className="absolute inset-0 z-[55] pointer-events-none">
        {Array.from({ length: n }).map((_, i) => {
          const spread = i - (n - 1) / 2
          return (
            <motion.div
              key={i}
              initial={{ x: 0, y: -10, scale: 1.1, rotate: 0, opacity: i === 0 ? 1 : 0 }}
              animate={{
                x: [spread * 70, spread * 70, 0],
                y: [-10, -10, 0],
                scale: [1.1, 1.1, 1],
                rotate: [spread * 10, spread * 10, 0],
                opacity: [1, 1, 1],
              }}
              transition={{ duration: 0.5, delay: i * 0.11, times: [0, 0.35, 1], ease: 'easeInOut' }}
              style={{ ...base, zIndex: 60 - i }}
              className="rounded-2xl px-4 py-5 shadow-xl shadow-black/50 text-black"
            >
              <CardFace tx={tx} den={childDen} currency={currency} />
            </motion.div>
          )
        })}
      </div>
    )
  }

  // merge: куски по одному слетаются к центру и сливаются в одну карту
  return (
    <div className="absolute inset-0 z-[55] pointer-events-none">
      {Array.from({ length: n }).map((_, i) => {
        const spread = i - (n - 1) / 2
        const last = i === n - 1
        return (
          <motion.div
            key={i}
            initial={{ x: spread * 70, y: spread % 2 ? -14 : 14, scale: 0.96, rotate: spread * 7, opacity: 1 }}
            animate={{
              x: 0, y: 0,
              scale: last ? [0.96, 1.12, 1] : 0.6,
              rotate: 0,
              opacity: last ? 1 : 0,
            }}
            transition={{ duration: 0.45, delay: last ? n * 0.1 : i * 0.1, ease: 'easeInOut' }}
            style={{ ...base, zIndex: last ? 62 : 56 + i }}
            className="rounded-2xl px-4 py-5 shadow-xl shadow-black/50 text-black"
          >
            <CardFace tx={tx} den={fx.den} currency={currency} />
          </motion.div>
        )
      })}
    </div>
  )
}

// ── Граф: люди + ноды-действия ──────────────────────────────────────────────────
// Детерминированная адаптивная раскладка (без хаотичной физики): люди — сеткой в
// верхней зоне, не наезжают, размер считается от ширины (масштабируется на мелкие
// экраны). Лёгкое CSS-«дыхание». Тап = открыть человека (нода не таскается, так
// что тап не перехватывается). Линии-веер от карты к людям.

const SPECIAL_ICON = { split: Scissors, defer: RotateCcw, merge: Merge }

function GraphField({ slots, actions, hub, nodeW, nodeH, activeId, absorbId, stats, currency, registerRef, onTapNode }) {
  const hotId = activeId || absorbId
  const scaleAnim = (id) => ({
    animate: { scale: absorbId === id ? [1, 1.7, 1] : activeId === id ? 1.45 : 1 },
    transition: absorbId === id
      ? { duration: 0.46, times: [0, 0.45, 1], ease: 'easeOut' }
      : { type: 'spring', stiffness: 300, damping: 18 },
  })
  return (
    <div className="absolute inset-0">
      <svg className="absolute inset-0 w-full h-full pointer-events-none">
        {slots.map((s) => {
          const hot = hotId === s.id
          return (
            <line key={s.id} x1={hub.x} y1={hub.y} x2={s.x} y2={s.y}
              stroke={hot ? 'rgba(214,178,112,0.9)' : 'rgba(255,255,255,0.10)'} strokeWidth={hot ? 2.5 : 1} />
          )
        })}
      </svg>

      {slots.map((s, i) => {
        const active = activeId === s.id
        const absorbing = absorbId === s.id
        const hot = active || absorbing
        const st = stats[s.id] || { total: 0, count: 0 }
        const tint = personTint(s.id)
        return (
          <div
            key={s.id}
            ref={(el) => registerRef(s.id, el)}
            style={{ position: 'absolute', left: s.x, top: s.y, width: nodeW, height: nodeH, marginLeft: -nodeW / 2, marginTop: -nodeH / 2, transition: 'left .35s ease, top .35s ease' }}
          >
            <div style={{ width: nodeW, height: nodeH, willChange: 'transform', animation: `bill-node-float ${5 + (i % 4)}s ease-in-out ${(i % 5) * 0.4}s infinite` }}>
              <motion.button
                type="button"
                onClick={() => onTapNode(s.id)}
                {...scaleAnim(s.id)}
                style={{
                  width: nodeW, height: nodeH,
                  background: hot ? undefined : tint.bg,
                  borderColor: hot ? undefined : tint.border,
                  color: hot ? undefined : tint.fg,
                }}
                className={`rounded-2xl border flex flex-col items-center justify-center text-center leading-tight shadow-lg shadow-black/40 ${hot ? 'bg-gold text-black border-gold z-10' : ''}`}
              >
                <span className="font-semibold text-xs truncate max-w-full px-1">{nodeAlias(s.person.display_name)}</span>
                {st.total > 0 && <span className="text-[10px] mt-0.5 tabular-nums opacity-90">{formatMinor(st.total, currency)}</span>}
              </motion.button>
            </div>
          </div>
        )
      })}

      {/* ноды-действия: делить · вниз · собрать */}
      {actions.map((s) => {
        const Icon = SPECIAL_ICON[s.icon] || RotateCcw
        const hot = activeId === s.id || absorbId === s.id
        return (
          <div
            key={s.id}
            ref={(el) => registerRef(s.id, el)}
            style={{ position: 'absolute', left: s.x, top: s.y, width: nodeW, height: nodeH, marginLeft: -nodeW / 2, marginTop: -nodeH / 2 }}
          >
            <motion.div
              {...scaleAnim(s.id)}
              style={{ width: nodeW, height: nodeH }}
              className={`rounded-2xl border flex flex-col items-center justify-center shadow-lg shadow-black/40 ${
                hot ? 'bg-indigo text-white border-indigo' : 'bg-spotify-dark/90 text-spotify-text border-white/15 border-dashed'
              }`}
            >
              <Icon size={15} />
              <span className="text-[10px] mt-0.5">{s.label}</span>
            </motion.div>
          </div>
        )
      })}
    </div>
  )
}

// ── Per-person sheet ────────────────────────────────────────────────────────────

function PersonSheet({ open, onClose, person, lines, currency, total, onRemove }) {
  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed bottom-0 left-1/2 -translate-x-1/2 z-50 w-full max-w-md
          bg-spotify-black rounded-t-2xl p-5 max-h-[80vh] overflow-y-auto">
          <Dialog.Title className="text-white text-lg font-bold mb-1">{person?.display_name}</Dialog.Title>
          <div className="text-gold font-semibold tabular-nums mb-1">{formatMinor(total, currency)}</div>
          {lines.length > 0 && (
            <div className="text-[11px] text-spotify-text/70 mb-3 inline-flex items-center gap-1">
              <Undo2 size={12} /> смахни позицию вбок — вернётся в колоду
            </div>
          )}
          <div className="space-y-2">
            {lines.length === 0 && <div className="text-spotify-text text-sm py-4 text-center">Пока ничего не досталось</div>}
            {lines.map((ln) => (
              <motion.div
                key={ln.txId}
                drag="x"
                dragSnapToOrigin
                dragElastic={0.7}
                onDragEnd={(_e, info) => { if (Math.abs(info.offset.x) > 110) onRemove(ln.txId) }}
                whileDrag={{ scale: 1.02, cursor: 'grabbing' }}
                className="flex items-center justify-between bg-spotify-gray rounded-lg px-3 py-2.5 cursor-grab touch-pan-y"
                style={{ touchAction: 'pan-y' }}
              >
                <div className="min-w-0">
                  <div className="text-white text-sm truncate">{ln.name}</div>
                  <div className="text-[11px] text-spotify-text tabular-nums">{ln.portion} · {formatMinor(ln.amount, currency)}</div>
                </div>
                <Undo2 size={15} className="ml-2 shrink-0 text-spotify-text/50" />
              </motion.div>
            ))}
          </div>
          <button onClick={onClose} className="mt-4 w-full bg-spotify-gray text-white rounded-lg py-2">Закрыть</button>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

const SPLIT_OPTIONS = [2, 3, 4]

// ── Main board ──────────────────────────────────────────────────────────────────

export default function BillDistribute({ bill, persons, onBack, onChange, onEditPositions, onManagePeople }) {
  const personsById = useMemo(() => Object.fromEntries(persons.map((p) => [p.id, p])), [persons])
  const participants = useMemo(
    () => bill.participants.map((id) => personsById[id]).filter(Boolean),
    [bill.participants, personsById],
  )
  const txById = useMemo(() => Object.fromEntries(bill.transactions.map((t) => [t.id, t])), [bill.transactions])
  const currency = bill.currency

  const [cards, setCards] = useState(() => billToCards(bill))
  const [openPerson, setOpenPerson] = useState(null)
  const [renaming, setRenaming] = useState(null)
  const [finishing, setFinishing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [fx, setFx] = useState(null)
  const [activeNode, setActiveNode] = useState(null)
  const [absorb, setAbsorb] = useState(null)
  const [splitPrompt, setSplitPrompt] = useState(false)

  const topCardRef = useRef(null)
  const nodeRefs = useRef({})
  const registerRef = useCallback((id, el) => {
    if (el) nodeRefs.current[id] = el
    else delete nodeRefs.current[id]
  }, [])

  // ── Размер игрового поля ──
  // Поле занимает весь экран (без видимой рамки) и НЕ скроллится: высота
  // считается так, чтобы поле кончалось прямо над нижней панелью (иначе появлялся
  // скролл, из-за которого «съезжали» зоны попадания).
  const boardRef = useRef(null)
  const [boardSize, setBoardSize] = useState(340)
  const [boardH, setBoardH] = useState(420)
  useLayoutEffect(() => {
    const el = boardRef.current
    if (!el) return
    const measure = () => {
      setBoardSize(Math.round(el.clientWidth))
      const top = el.getBoundingClientRect().top
      setBoardH(Math.max(380, Math.round(window.innerHeight - top - 120)))
    }
    window.scrollTo(0, 0)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    window.addEventListener('resize', measure)
    return () => { ro.disconnect(); window.removeEventListener('resize', measure) }
  }, [])

  useEffect(() => { setCards(billToCards(bill)) }, [bill.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Debounced auto-save ──
  const saveTimer = useRef(null)
  const buildBody = useCallback((src) => {
    const byTx = {}
    for (const c of src) (byTx[c.txId] = byTx[c.txId] || []).push(c)
    return { transactions: bill.transactions.map((tx) => ({ id: tx.id, assignments: groupAssignments(byTx[tx.id] || []) })) }
  }, [bill.transactions])

  const queueSave = useCallback((next) => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(async () => {
      setSaving(true)
      try { await api.put(`/api/bills/${bill.id}/distribution`, buildBody(next)) }
      catch { /* keep local; retry on next change */ }
      finally { setSaving(false) }
    }, 600)
  }, [bill.id, buildBody])

  useEffect(() => () => { if (saveTimer.current) clearTimeout(saveTimer.current) }, [])

  const mutate = useCallback((updater) => {
    setCards((prev) => { const next = updater(prev); queueSave(next); return next })
  }, [queueSave])

  // ── Derived ──
  const deck = useMemo(() => cards.filter((c) => c.owner === null), [cards])
  const top = deck[0] || null
  const remaining = deck.length
  const topLoose = useMemo(() => (top ? deck.filter((c) => c.txId === top.txId) : []), [deck, top])
  const topLooseCount = topLoose.length
  // «Собрать» нужно только если карта реально разделена (есть доли), а не просто
  // несколько целых одинаковых карт.
  const canMerge = topLooseCount >= 2 && topLoose.some((c) => c.den > 1)

  const personStats = useMemo(() => {
    const stat = {}
    for (const p of participants) stat[p.id] = { total: 0, count: 0, lines: {} }
    const byKey = {}
    for (const c of cards) {
      if (!c.owner || !stat[c.owner]) continue
      const key = `${c.owner}|${c.txId}|${c.den}`
      byKey[key] = (byKey[key] || 0) + 1
    }
    for (const [key, count] of Object.entries(byKey)) {
      const [owner, txId, denStr] = key.split('|')
      const den = Number(denStr)
      const amount = piecesCost(txById[txId]?.unit_price_minor || 0, count, den)
      stat[owner].total += amount
      const line = (stat[owner].lines[txId] = stat[owner].lines[txId] || { amount: 0, parts: [] })
      line.amount += amount
      line.parts.push(den > 1 ? `${count}/${den}` : `${count} шт`)
    }
    for (const pid of Object.keys(stat)) stat[pid].count = Object.keys(stat[pid].lines).length
    return stat
  }, [participants, cards, txById])

  const personLines = useCallback((pid) => {
    const lines = personStats[pid]?.lines || {}
    return Object.entries(lines).map(([txId, ln]) => ({
      txId, name: txById[txId]?.item_name || '?', amount: ln.amount, portion: ln.parts.join(' + '),
    }))
  }, [personStats, txById])

  const personCount = useCallback((pid) => personStats[pid]?.count || 0, [personStats])

  // ── Адаптивная раскладка: люди сеткой сверху, ряд действий, карта у низа ──
  // Размер нод считается от ширины → масштабируется на маленькие экраны. Ничего
  // не наезжает (детерминированные слоты), низ занят картой и действиями.
  const layout = useMemo(() => {
    const W = boardSize
    const H = boardH
    const N = participants.length
    const nodeW = Math.round(Math.min(96, Math.max(58, W / 4.6)))
    const nodeH = Math.round(nodeW * 0.6)
    const gapX = Math.max(8, Math.round(nodeW * 0.16))
    const gapY = Math.max(10, Math.round(nodeH * 0.34))
    const cols = Math.max(1, Math.min(N, 4, Math.floor((W - 8) / (nodeW + gapX))))
    const rows = Math.max(1, Math.ceil(N / cols))
    const zoneTop = nodeH / 2 + 6
    const zoneH = H * 0.60
    const gridH = rows * nodeH + (rows - 1) * gapY
    const startY = zoneTop + Math.max(0, (zoneH - gridH) / 2)
    const slots = participants.map((p, i) => {
      const r = Math.floor(i / cols)
      const rowCount = Math.min(cols, N - r * cols)
      const rowW = rowCount * nodeW + (rowCount - 1) * gapX
      const c = i - r * cols
      return {
        id: p.id, person: p,
        x: (W - rowW) / 2 + nodeW / 2 + c * (nodeW + gapX),
        y: startY + r * (nodeH + gapY),
      }
    })
    const acts = [
      { id: '__split__', icon: 'split', label: 'делить' },
      { id: '__defer__', icon: 'defer', label: 'вниз' },
    ]
    if (canMerge) acts.push({ id: '__merge__', icon: 'merge', label: 'собрать' })
    const an = acts.length
    const actGap = Math.max(12, gapX)
    const actW = an * nodeW + (an - 1) * actGap
    const actY = H * 0.70
    const actions = acts.map((s, i) => ({ ...s, x: (W - actW) / 2 + nodeW / 2 + i * (nodeW + actGap), y: actY }))
    const hub = { x: W / 2, y: H * 0.88 }
    return { nodeW, nodeH, slots, actions, hub, capture: Math.max(56, nodeW * 0.95) }
  }, [participants, boardSize, boardH, canMerge])

  const SPECIAL_KIND = { __defer__: 'defer', __split__: 'split', __merge__: 'merge' }

  const nearestNode = useCallback((point) => {
    let best = null
    let bestD = layout.capture
    for (const [id, el] of Object.entries(nodeRefs.current)) {
      const r = el?.getBoundingClientRect?.()
      if (!r) continue
      const ncx = r.left + r.width / 2
      const ncy = r.top + r.height / 2
      const d = Math.hypot(point.x - ncx, point.y - ncy)
      if (d < bestD) { bestD = d; best = { id, rect: r } }
    }
    if (!best) return null
    const kind = SPECIAL_KIND[best.id]
    if (kind) return { kind, rect: best.rect, id: best.id }
    return { kind: 'person', personId: best.id, rect: best.rect, id: best.id }
  }, [layout.capture]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Card ops ──
  const pulseAbsorb = useCallback((id) => {
    setActiveNode(null)
    setAbsorb(id)
    setTimeout(() => setAbsorb((cur) => (cur === id ? null : cur)), 480)
  }, [])

  const assignTop = useCallback((personId) => {
    if (!top) return
    pulseAbsorb(personId)
    mutate((prev) => prev.map((c) => (c.id === top.id ? { ...c, owner: personId } : c)))
  }, [top, mutate, pulseAbsorb])

  const deferTop = useCallback(() => {
    if (!top) return
    pulseAbsorb('__defer__')
    mutate((prev) => { const card = prev.find((c) => c.id === top.id); return [...prev.filter((c) => c.id !== top.id), card] })
  }, [top, mutate, pulseAbsorb])

  const splitTop = useCallback((n) => {
    if (!top) return
    mutate((prev) => {
      const idx = prev.findIndex((c) => c.id === top.id)
      if (idx === -1) return prev
      const fresh = Array.from({ length: n }, () => ({ id: nextId(), txId: top.txId, den: top.den * n, owner: null }))
      const next = [...prev]
      next.splice(idx, 1, ...fresh)
      return next
    })
  }, [top, mutate])

  const doMerge = useCallback((txId) => {
    mutate((prev) => {
      const loose = prev.filter((c) => c.txId === txId && c.owner === null)
      if (loose.length < 2) return prev
      const L = loose.reduce((m, c) => lcm(m, c.den), 1)
      const totalNum = loose.reduce((s, c) => s + L / c.den, 0)
      const whole = Math.floor(totalNum / L)
      const remNum = totalNum - whole * L
      const g = remNum ? gcd(remNum, L) : 1
      const rNum = remNum ? remNum / g : 0
      const rDen = remNum ? L / g : 1
      const rebuilt = []
      for (let i = 0; i < whole; i++) rebuilt.push({ id: nextId(), txId, den: 1, owner: null })
      for (let i = 0; i < rNum; i++) rebuilt.push({ id: nextId(), txId, den: rDen, owner: null })
      if (rebuilt.length >= loose.length) return prev
      const firstIdx = prev.findIndex((c) => c.txId === txId && c.owner === null)
      const without = prev.filter((c) => !(c.txId === txId && c.owner === null))
      without.splice(Math.min(firstIdx, without.length), 0, ...rebuilt)
      return without
    })
  }, [mutate])

  // FX-обёртки: показать анимацию деления/склейки, затем закоммитить.
  const startSplit = useCallback((n) => {
    if (!top || fx) return
    setFx({ type: 'split', txId: top.txId, den: top.den, n })
  }, [top, fx])

  const startMerge = useCallback(() => {
    if (!top || !canMerge || fx) return
    setFx({ type: 'merge', txId: top.txId, den: top.den, count: Math.min(topLooseCount, 5) })
  }, [top, canMerge, fx, topLooseCount])

  const fxDone = useCallback(() => {
    setFx((cur) => {
      if (!cur) return null
      if (cur.type === 'split') splitTop(cur.n)
      else doMerge(cur.txId)
      return null
    })
  }, [splitTop, doMerge])

  const returnLine = useCallback((txId, personId) => {
    mutate((prev) => prev.map((c) => (c.txId === txId && c.owner === personId ? { ...c, owner: null } : c)))
  }, [mutate])

  // ── Rename ──
  const submitRename = useCallback(async () => {
    if (!renaming) return
    const name = renaming.name.trim()
    setRenaming(null)
    if (!name || name === txById[renaming.txId]?.item_name) return
    try { await api.patch(`/api/bills/${bill.id}/transactions/${renaming.txId}`, { item_name: name }); onChange?.() }
    catch { /* noop */ }
  }, [renaming, bill.id, txById, onChange])

  // ── Delete bill ──
  const removeBill = useCallback(async () => {
    try { await api.delete(`/api/bills/${bill.id}`); onChange?.(); onBack() }
    catch { setConfirmDelete(false) }
  }, [bill.id, onChange, onBack])

  // ── Finalize ──
  const finalize = useCallback(async () => {
    setSaving(true)
    try {
      if (saveTimer.current) clearTimeout(saveTimer.current)
      await api.put(`/api/bills/${bill.id}/distribution`, buildBody(cards))
      await api.put(`/api/bills/${bill.id}/finalize`)
      onChange?.()
      onBack()
    } catch { /* noop */ } finally { setSaving(false) }
  }, [bill.id, buildBody, cards, onBack, onChange])

  // ── Finish summary ──
  if (finishing) {
    const filled = participants.filter((p) => personCount(p.id) > 0)
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="px-4 pt-6 pb-8">
        <button onClick={() => setFinishing(false)} className="text-spotify-text text-sm mb-3 inline-flex items-center gap-1 hover:text-white">
          <ChevronLeft size={16} /> К доске
        </button>
        <h2 className="text-white text-xl font-bold mb-1 inline-flex items-center gap-2"><PartyPopper size={20} className="text-gold" /> Кто что взял</h2>
        <p className="text-spotify-text text-sm mb-4">Проверьте — потом счёт станет итоговым.</p>
        <div className="space-y-3 mb-5">
          {filled.map((p) => (
            <div key={p.id} className="bg-spotify-dark rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="text-white font-medium">{p.display_name}</div>
                <div className="text-gold font-semibold tabular-nums">{formatMinor(personStats[p.id].total, currency)}</div>
              </div>
              <div className="space-y-1">
                {personLines(p.id).map((ln) => (
                  <div key={ln.txId} className="text-xs text-spotify-text flex justify-between">
                    <span className="truncate mr-2">{ln.name} · {ln.portion}</span>
                    <span className="tabular-nums shrink-0">{formatMinor(ln.amount, currency)}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <button onClick={() => setFinishing(false)} className="flex-1 bg-spotify-gray text-white rounded-xl py-3">Переделать</button>
          <button onClick={finalize} disabled={saving} className="flex-1 bg-gold text-black font-semibold rounded-xl py-3 disabled:opacity-50 hover:bg-gold-2 transition-colors">
            {saving ? '...' : 'Сохранить итог'}
          </button>
        </div>
      </motion.div>
    )
  }

  // ── Board ──
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="px-4 pt-6 pb-4 overflow-hidden">
      <div className="flex items-center justify-between mb-2">
        <button onClick={onBack} className="text-spotify-text text-sm inline-flex items-center gap-1 hover:text-white">
          <ChevronLeft size={16} /> Назад
        </button>
        <div className="flex items-center gap-3">
          {onManagePeople && (
            <button onClick={onManagePeople} className="text-spotify-text text-sm inline-flex items-center gap-1 hover:text-white" title="Изменить состав">
              <Users size={15} /> Люди
            </button>
          )}
          {onEditPositions && (
            <button onClick={onEditPositions} className="text-spotify-text text-sm inline-flex items-center gap-1 hover:text-white" title="Назад к позициям">
              <ListChecks size={15} /> Позиции
            </button>
          )}
          <button onClick={() => setConfirmDelete(true)} className="text-spotify-text/70 hover:text-red-400" title="Удалить счёт"><Trash2 size={17} /></button>
        </div>
      </div>

      <h2 className="text-white text-xl font-bold">{bill.name}</h2>
      <p className="text-spotify-text text-sm mb-3">
        Тащи карту на человека · на ноду снизу — делить, отложить, собрать
      </p>

      {/* Игровое поле во весь экран: частицы + граф + колода (без рамки) */}
      <div ref={boardRef} className="relative w-full" style={{ height: boardH }}>
        <ParticleField />

        <GraphField
          slots={layout.slots}
          actions={layout.actions}
          hub={layout.hub}
          nodeW={layout.nodeW}
          nodeH={layout.nodeH}
          activeId={activeNode}
          absorbId={absorb}
          stats={personStats}
          currency={currency}
          registerRef={registerRef}
          onTapNode={(id) => { if (!SPECIAL_KIND[id]) setOpenPerson(id) }}
        />

        {/* колода у низа — слой пропускает клики мимо карты к нодам */}
        {remaining > 0 && (
          <div className="absolute inset-0 pointer-events-none">
            {deck.slice(0, 4).map((card, i) => (
              <PileCard
                key={card.id}
                ref={i === 0 ? topCardRef : undefined}
                card={card}
                depth={i}
                isTop={i === 0}
                draggable={i === 0 && !fx}
                dimmed={i === 0 && !!activeNode}
                anchor={layout.hub}
                tx={txById[card.txId]}
                currency={currency}
                remaining={remaining}
                resolveDrop={nearestNode}
                onAssign={assignTop}
                onDefer={deferTop}
                onSplit={() => setSplitPrompt(true)}
                onMerge={startMerge}
                onRename={(txId, name) => setRenaming({ txId, name })}
                onDragStartCard={() => setActiveNode(null)}
                onDragMoveCard={(point) => setActiveNode(nearestNode(point)?.id || null)}
                onDragEndCard={() => setActiveNode(null)}
              />
            ))}
          </div>
        )}

        {fx && <FxLayer fx={fx} tx={txById[fx.txId]} currency={currency} anchor={layout.hub} onDone={fxDone} />}
      </div>

      {/* Нижняя панель — только завершение (делить/вниз/собрать теперь ноды) */}
      {remaining === 0 && (
        <div className="fixed inset-x-0 bottom-28 z-30 px-4">
          <div className="max-w-md mx-auto">
            <button
              onClick={() => setFinishing(true)}
              className="block w-full bg-gold text-black font-semibold rounded-xl py-3 shadow-lg shadow-black/40 hover:bg-gold-2 transition-colors"
            >Завершить →</button>
          </div>
        </div>
      )}

      <PersonSheet
        open={!!openPerson}
        onClose={() => setOpenPerson(null)}
        person={openPerson ? personsById[openPerson] : null}
        currency={currency}
        total={openPerson ? personStats[openPerson]?.total || 0 : 0}
        lines={openPerson ? personLines(openPerson) : []}
        onRemove={(txId) => returnLine(txId, openPerson)}
      />

      {/* На сколько разделить (после сброса карты на ноду «делить») */}
      <Dialog.Root open={splitPrompt} onOpenChange={(v) => !v && setSplitPrompt(false)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
          <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50
            bg-spotify-black rounded-2xl p-5 w-[calc(100%-2rem)] max-w-xs text-center">
            <Dialog.Title className="text-white text-base font-bold mb-1">На сколько разделить?</Dialog.Title>
            <p className="text-spotify-text text-xs mb-4">Карта превратится в доли и вернётся в колоду</p>
            <div className="flex justify-center gap-2">
              {SPLIT_OPTIONS.map((n) => (
                <button
                  key={n}
                  onClick={() => { setSplitPrompt(false); startSplit(n) }}
                  className="flex-1 py-3 rounded-xl bg-spotify-gray text-white text-lg font-bold hover:bg-spotify-light-gray transition-colors"
                >÷{n}</button>
              ))}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <Dialog.Root open={!!renaming} onOpenChange={(v) => !v && setRenaming(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
          <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50
            bg-spotify-black rounded-2xl p-5 w-[calc(100%-2rem)] max-w-sm">
            <Dialog.Title className="text-white text-base font-bold mb-3">Название позиции</Dialog.Title>
            <input
              autoFocus
              value={renaming?.name || ''}
              onChange={(e) => setRenaming((r) => ({ ...r, name: e.target.value }))}
              onKeyDown={(e) => e.key === 'Enter' && submitRename()}
              className="w-full bg-spotify-gray rounded-lg px-3 py-2 text-white text-sm outline-none mb-3"
            />
            <div className="flex gap-2">
              <button onClick={() => setRenaming(null)} className="flex-1 bg-spotify-gray text-white rounded-lg py-2 inline-flex items-center justify-center gap-1"><X size={16} /> Отмена</button>
              <button onClick={submitRename} className="flex-1 bg-gold text-black rounded-lg py-2 font-medium inline-flex items-center justify-center gap-1 hover:bg-gold-2 transition-colors"><Check size={16} /> Ок</button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <AnimatePresence>
        {confirmDelete && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
            onClick={() => setConfirmDelete(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="bg-spotify-black rounded-2xl p-5 w-full max-w-sm"
            >
              <h3 className="text-white font-bold text-lg mb-1">Удалить счёт?</h3>
              <p className="text-spotify-text text-sm mb-4">«{bill.name}» удалится целиком. Это не отменить.</p>
              <div className="flex gap-2">
                <button onClick={() => setConfirmDelete(false)} className="flex-1 bg-spotify-gray text-white rounded-xl py-2.5">Отмена</button>
                <button onClick={removeBill} className="flex-1 bg-red-500/90 text-white rounded-xl py-2.5 font-medium inline-flex items-center justify-center gap-1.5"><Trash2 size={16} /> Удалить</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
