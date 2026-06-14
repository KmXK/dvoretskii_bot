import { useState, useEffect, useMemo, useRef, useCallback, forwardRef, useImperativeHandle } from 'react'
import { motion, animate, useMotionValue, useTransform, useSpring, AnimatePresence } from 'framer-motion'
import * as Dialog from '@radix-ui/react-dialog'
import { ChevronLeft, Pencil, X, Check, Undo2, PartyPopper, Scissors, RotateCcw, Merge, Network, Trash2 } from 'lucide-react'
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

function initials(name) {
  return (name || '?').trim().slice(0, 1).toUpperCase()
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

const CARD_W = 200
const CARD_MT = -84 // ≈ half card height, для центровки в доске
const POSE_SPRING = { type: 'spring', stiffness: 340, damping: 26 }
const CAPTURE = 82 // радиус захвата ноды при перетаскивании

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
  { card, depth, isTop, draggable, tx, currency, remaining, resolveDrop,
    onAssign, onDefer, onRename, onDragStartCard, onDragMoveCard, onDragEndCard }, ref,
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

  const springHome = () => {
    animate(x, 0, { type: 'spring', stiffness: 300, damping: 24 })
    animate(y, depth * 9, { type: 'spring', stiffness: 300, damping: 24 })
    animate(scale, 1, { type: 'spring', stiffness: 300, damping: 20 })
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
    onDragEndCard?.()
    const drop = resolveDrop(info.point)
    if (drop) {
      flyToRect(drop.rect, () => (drop.kind === 'defer' ? onDefer() : onAssign(drop.personId)))
      return
    }
    springHome()
  }

  const wrap = {
    position: 'absolute', left: '50%', top: '50%',
    width: CARD_W, marginLeft: -CARD_W / 2, marginTop: CARD_MT, zIndex: 40 - depth,
  }
  return (
    <motion.div
      ref={nodeRef}
      drag={draggable}
      dragMomentum={false}
      onDragStart={() => { dragging.current = true; onDragStartCard?.(); animate(scale, 1.06, { duration: 0.12 }) }}
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

function FxLayer({ fx, tx, currency, onDone }) {
  useEffect(() => {
    const t = setTimeout(onDone, fx.type === 'split' ? 680 : 600)
    return () => clearTimeout(t)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const base = {
    position: 'absolute', left: '50%', top: '50%', width: CARD_W,
    marginLeft: -CARD_W / 2, marginTop: CARD_MT, background: cardGradient(fx.txId),
  }

  if (fx.type === 'split') {
    const n = fx.n
    const childDen = fx.den * n
    return (
      <div className="absolute inset-0 z-[55] pointer-events-none">
        {Array.from({ length: n }).map((_, i) => {
          const spread = i - (n - 1) / 2
          return (
            <motion.div
              key={i}
              initial={{ x: 0, y: 0, scale: 1, rotate: 0, opacity: i === 0 ? 1 : 0 }}
              animate={{
                x: [0, spread * 64, spread * 14],
                y: [0, -12, 0],
                scale: [1, 1.12, 1],
                rotate: [0, spread * 9, spread * 2.5],
                opacity: 1,
              }}
              transition={{ duration: 0.62, times: [0, 0.5, 1], ease: 'easeOut' }}
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

  // merge: куски сходятся к центру и сливаются
  const count = fx.count
  return (
    <div className="absolute inset-0 z-[55] pointer-events-none">
      {Array.from({ length: count }).map((_, i) => {
        const spread = i - (count - 1) / 2
        const last = i === count - 1
        return (
          <motion.div
            key={i}
            initial={{ x: spread * 56, y: spread % 2 ? -8 : 8, scale: 0.96, rotate: spread * 6, opacity: 1 }}
            animate={{
              x: 0, y: 0,
              scale: last ? [0.96, 1.1, 1] : 0.7,
              rotate: 0,
              opacity: last ? 1 : 0,
            }}
            transition={{ duration: 0.55, ease: 'easeInOut' }}
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

// ── Радиальный граф людей ────────────────────────────────────────────────────────

function RadialGraph({ layout, nodeSize, activeId, interactive, stats, currency, registerRef, onTapNode }) {
  const { cx, cy, nodes, defer, size } = layout
  return (
    <div className="absolute inset-0">
      <svg width={size} height={size} className="absolute inset-0 pointer-events-none">
        {[...nodes, defer].map((nd) => {
          const active = activeId === nd.id
          return (
            <line
              key={nd.id}
              x1={cx} y1={cy} x2={nd.x} y2={nd.y}
              stroke={active ? 'rgba(214,178,112,0.9)' : 'rgba(255,255,255,0.16)'}
              strokeWidth={active ? 2 : 1}
            />
          )
        })}
      </svg>

      {nodes.map((nd, i) => {
        const active = activeId === nd.id
        const st = stats[nd.id] || { total: 0, count: 0 }
        return (
          <div
            key={nd.id}
            ref={(el) => registerRef(nd.id, el)}
            style={{ position: 'absolute', left: nd.x, top: nd.y, width: nodeSize, height: nodeSize, marginLeft: -nodeSize / 2, marginTop: -nodeSize / 2 }}
            className="flex items-center justify-center"
          >
            <motion.button
              type="button"
              disabled={!interactive}
              onClick={() => interactive && onTapNode(nd.id)}
              animate={{
                y: [0, i % 2 ? -3 : 3, 0],
                x: [0, i % 3 ? 2 : -2, 0],
                scale: active ? 1.32 : 1,
              }}
              transition={{
                y: { repeat: Infinity, duration: 3 + (i % 3), ease: 'easeInOut' },
                x: { repeat: Infinity, duration: 4 + (i % 2), ease: 'easeInOut' },
                scale: { type: 'spring', stiffness: 320, damping: 20 },
              }}
              style={{ width: nodeSize, height: nodeSize, pointerEvents: interactive ? 'auto' : 'none' }}
              className={`rounded-full flex flex-col items-center justify-center border text-center leading-none transition-colors ${
                active
                  ? 'bg-gold text-black border-gold shadow-lg shadow-gold/30'
                  : st.count > 0
                    ? 'bg-spotify-gray text-white border-spotify-light-gray'
                    : 'bg-spotify-dark/90 text-spotify-text border-white/15'
              }`}
            >
              <span className="font-semibold text-xs px-1 truncate max-w-full">{initials(nd.person.display_name)}</span>
              {st.total > 0 && <span className="text-[9px] mt-0.5 tabular-nums opacity-90">{formatMinor(st.total, currency)}</span>}
            </motion.button>
          </div>
        )
      })}

      {/* нижняя нода — сброс вниз колоды */}
      <div
        ref={(el) => registerRef(defer.id, el)}
        style={{ position: 'absolute', left: defer.x, top: defer.y, width: nodeSize, height: nodeSize, marginLeft: -nodeSize / 2, marginTop: -nodeSize / 2 }}
        className="flex items-center justify-center"
      >
        <motion.div
          animate={{ scale: activeId === defer.id ? 1.32 : 1 }}
          transition={{ type: 'spring', stiffness: 320, damping: 20 }}
          style={{ width: nodeSize, height: nodeSize }}
          className={`rounded-full flex flex-col items-center justify-center border ${
            activeId === defer.id ? 'bg-indigo text-white border-indigo' : 'bg-spotify-dark/90 text-spotify-text border-white/15 border-dashed'
          }`}
        >
          <RotateCcw size={16} />
          <span className="text-[9px] mt-0.5">вниз</span>
        </motion.div>
      </div>
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
          <div className="text-gold font-semibold tabular-nums mb-3">{formatMinor(total, currency)}</div>
          <div className="space-y-2">
            {lines.length === 0 && <div className="text-spotify-text text-sm py-4 text-center">Пока ничего не досталось</div>}
            {lines.map((ln) => (
              <div key={ln.txId} className="flex items-center justify-between bg-spotify-gray rounded-lg px-3 py-2">
                <div className="min-w-0">
                  <div className="text-white text-sm truncate">{ln.name}</div>
                  <div className="text-[11px] text-spotify-text tabular-nums">{ln.portion} · {formatMinor(ln.amount, currency)}</div>
                </div>
                <button onClick={() => onRemove(ln.txId)} className="ml-2 shrink-0 inline-flex items-center gap-1 text-xs text-red-400">
                  <Undo2 size={14} /> вернуть
                </button>
              </div>
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

export default function BillDistribute({ bill, persons, onBack, onChange }) {
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
  const [dragging, setDragging] = useState(false)
  const [showGraph, setShowGraph] = useState(false)
  const [activeNode, setActiveNode] = useState(null)

  const topCardRef = useRef(null)
  const nodeRefs = useRef({})
  const registerRef = useCallback((id, el) => {
    if (el) nodeRefs.current[id] = el
    else delete nodeRefs.current[id]
  }, [])

  // ── Размер доски ──
  const boardRef = useRef(null)
  const [boardSize, setBoardSize] = useState(340)
  useEffect(() => {
    const el = boardRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setBoardSize(Math.round(el.clientWidth)))
    ro.observe(el)
    setBoardSize(Math.round(el.clientWidth))
    return () => ro.disconnect()
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
  const topLooseCount = top ? deck.filter((c) => c.txId === top.txId).length : 0
  const canMerge = topLooseCount >= 2

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

  // ── Раскладка графа ──
  const layout = useMemo(() => {
    const size = boardSize
    const cx = size / 2
    const cy = size / 2
    const R = size * 0.45
    const N = participants.length
    const GAP = 90
    const start = 90 + GAP / 2
    const span = 360 - GAP
    const nodes = participants.map((p, i) => {
      const deg = N === 1 ? 270 : start + (span * (i + 1)) / (N + 1)
      const rad = (deg * Math.PI) / 180
      return { id: p.id, person: p, x: cx + R * Math.cos(rad), y: cy + R * Math.sin(rad) }
    })
    return { size, cx, cy, nodes, defer: { id: '__defer__', x: cx, y: cy + R } }
  }, [participants, boardSize])

  const nodeSize = participants.length > 8 ? 46 : participants.length > 6 ? 52 : 60

  const nearestNode = useCallback((point) => {
    let best = null
    let bestD = CAPTURE
    for (const [id, el] of Object.entries(nodeRefs.current)) {
      const r = el?.getBoundingClientRect?.()
      if (!r) continue
      const ncx = r.left + r.width / 2
      const ncy = r.top + r.height / 2
      const d = Math.hypot(point.x - ncx, point.y - ncy)
      if (d < bestD) { bestD = d; best = { id, rect: r } }
    }
    if (!best) return null
    if (best.id === '__defer__') return { kind: 'defer', rect: best.rect, id: best.id }
    return { kind: 'person', personId: best.id, rect: best.rect, id: best.id }
  }, [])

  // ── Card ops ──
  const assignTop = useCallback((personId) => {
    setActiveNode(null)
    if (!top) return
    mutate((prev) => prev.map((c) => (c.id === top.id ? { ...c, owner: personId } : c)))
  }, [top, mutate])

  const deferTop = useCallback(() => {
    setActiveNode(null)
    if (!top) return
    mutate((prev) => { const card = prev.find((c) => c.id === top.id); return [...prev.filter((c) => c.id !== top.id), card] })
  }, [top, mutate])

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

  const graphVisible = dragging || showGraph

  // ── Board ──
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="px-4 pt-6 pb-44">
      <div className="flex items-center justify-between mb-2">
        <button onClick={onBack} className="text-spotify-text text-sm inline-flex items-center gap-1 hover:text-white">
          <ChevronLeft size={16} /> Назад
        </button>
        <div className="flex items-center gap-3">
          <span className="text-[11px] text-spotify-text">{saving ? 'сохраняю…' : 'сохранено'}</span>
          <button onClick={() => setConfirmDelete(true)} className="text-spotify-text/70 hover:text-red-400" title="Удалить счёт"><Trash2 size={17} /></button>
        </div>
      </div>

      <h2 className="text-white text-xl font-bold">{bill.name}</h2>
      <p className="text-spotify-text text-sm mb-3">
        Тащи карту к человеку · вниз по центру — отложить
      </p>

      {/* Доска: частицы + граф + колода */}
      <div ref={boardRef} className="relative mx-auto w-full overflow-hidden rounded-3xl bg-spotify-dark/40" style={{ maxWidth: 360, height: boardSize }}>
        <ParticleField />

        {remaining === 0 && !graphVisible ? (
          <div className="absolute inset-0 flex items-center justify-center text-spotify-text text-sm">
            Все карточки разложены 🎉
          </div>
        ) : null}

        {graphVisible && (
          <RadialGraph
            layout={layout}
            nodeSize={nodeSize}
            activeId={activeNode}
            interactive={!dragging}
            stats={personStats}
            currency={currency}
            registerRef={registerRef}
            onTapNode={(id) => { if (id !== '__defer__') setOpenPerson(id) }}
          />
        )}

        {/* колода по центру */}
        {remaining > 0 && (
          <div className="absolute inset-0">
            {deck.slice(0, 4).map((card, i) => (
              <PileCard
                key={card.id}
                ref={i === 0 ? topCardRef : undefined}
                card={card}
                depth={i}
                isTop={i === 0}
                draggable={i === 0 && !fx}
                tx={txById[card.txId]}
                currency={currency}
                remaining={remaining}
                resolveDrop={nearestNode}
                onAssign={assignTop}
                onDefer={deferTop}
                onRename={(txId, name) => setRenaming({ txId, name })}
                onDragStartCard={() => { setDragging(true); setActiveNode(null) }}
                onDragMoveCard={(point) => setActiveNode(nearestNode(point)?.id || null)}
                onDragEndCard={() => { setDragging(false); setActiveNode(null) }}
              />
            ))}
          </div>
        )}

        {fx && <FxLayer fx={fx} tx={txById[fx.txId]} currency={currency} onDone={fxDone} />}
      </div>

      {/* Нижняя панель */}
      <div className="fixed inset-x-0 bottom-28 z-30 px-4">
        <div className="max-w-md mx-auto space-y-2">
          {remaining === 0 ? (
            <button
              onClick={() => setFinishing(true)}
              className="block w-full bg-gold text-black font-semibold rounded-xl py-3 shadow-lg shadow-black/40 hover:bg-gold-2 transition-colors"
            >Завершить →</button>
          ) : (
            <div className="flex items-center justify-center flex-wrap gap-2 bg-spotify-dark/90 backdrop-blur rounded-2xl px-3 py-2.5 shadow-lg shadow-black/40">
              <span className="inline-flex items-center gap-1 text-[11px] text-spotify-text mr-1"><Scissors size={12} /> делить</span>
              {SPLIT_OPTIONS.map((n) => (
                <button
                  key={n}
                  onClick={() => startSplit(n)}
                  disabled={!!fx}
                  className="text-xs px-2.5 py-1.5 rounded-lg bg-spotify-gray text-white hover:bg-spotify-light-gray disabled:opacity-50 transition-colors"
                >÷{n}</button>
              ))}
              {canMerge && (
                <button
                  onClick={startMerge}
                  disabled={!!fx}
                  className="text-xs px-2.5 py-1.5 rounded-lg bg-indigo/20 text-indigo hover:bg-indigo/30 disabled:opacity-50 transition-colors inline-flex items-center gap-1"
                ><Merge size={12} /> собрать</button>
              )}
              <button
                onClick={() => (topCardRef.current ? topCardRef.current.flingDown(-1) : deferTop())}
                className="text-xs px-2.5 py-1.5 rounded-lg bg-spotify-gray text-spotify-text hover:text-white inline-flex items-center gap-1"
              ><RotateCcw size={12} /> вниз</button>
            </div>
          )}
          <button
            onClick={() => setShowGraph((v) => !v)}
            className={`w-full rounded-xl py-2 text-sm inline-flex items-center justify-center gap-1.5 transition-colors ${
              showGraph ? 'bg-gold/20 text-gold' : 'bg-spotify-dark/80 text-spotify-text hover:text-white'
            }`}
          ><Network size={14} /> {showGraph ? 'Скрыть граф' : 'Показать граф'}</button>
        </div>
      </div>

      <PersonSheet
        open={!!openPerson}
        onClose={() => setOpenPerson(null)}
        person={openPerson ? personsById[openPerson] : null}
        currency={currency}
        total={openPerson ? personStats[openPerson]?.total || 0 : 0}
        lines={openPerson ? personLines(openPerson) : []}
        onRemove={(txId) => returnLine(txId, openPerson)}
      />

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
