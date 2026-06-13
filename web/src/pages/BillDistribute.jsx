import { useState, useEffect, useMemo, useRef, useCallback, forwardRef, useImperativeHandle } from 'react'
import { motion, animate, useMotionValue, useTransform, useSpring } from 'framer-motion'
import * as Dialog from '@radix-ui/react-dialog'
import { ChevronLeft, Pencil, X, Check, Undo2, PartyPopper, Scissors, RotateCcw, Merge } from 'lucide-react'
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

// ── Cards model ───────────────────────────────────────────────────────────────
// One ordered, flat deck of "cards". Each card is a 1/den fraction of one unit of
// a transaction, owned by a person or null (still in the deck). Order is the deck
// order: deck[0] is the top card. Persisted as
// BillItemAssignment{unit_count, debtors, denominator}.

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

const CARD_W = 220
const POSE_SPRING = { type: 'spring', stiffness: 340, damping: 26 }

// ── PileCard ──────────────────────────────────────────────────────────────────
// Every visible card is the SAME component, keyed by id. When the deck shifts a
// card's depth, the same element's motion values spring to the new pose — so a
// card promoted to the top glides up smoothly instead of remounting (no flash,
// no jump). Only the top card is draggable. New cards grow/scatter in (mitosis),
// the top flies into a person on drop, and swiping/«вниз» flings it to the back.
const PileCard = forwardRef(function PileCard(
  { card, depth, isTop, tx, currency, remaining, resolveDrop, onAssign, onDefer, onRename }, ref,
) {
  const nodeRef = useRef(null)
  const dragging = useRef(false)
  const x = useMotionValue((depth % 2 ? 1 : -1) * depth * 14) // small scatter-in
  const y = useMotionValue(0)
  const scale = useMotionValue(0.5)
  const opacity = useMotionValue(0)
  const tilt = useMotionValue(0)
  const lean = useSpring(useTransform(x, [-220, 220], [-22, 22]), { stiffness: 260, damping: 18, mass: 0.6 })
  const rotate = useTransform([lean, tilt], ([l, t]) => l + t)

  // Grow/settle in.
  useEffect(() => {
    const c = animate(opacity, 1, { duration: 0.22 })
    return () => c.stop()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Spring to the resting pose for the current depth (skip while the top is held).
  // Also restore opacity — a card sent to the bottom was faded out by flingDown,
  // so when it re-poses at the back of the deck it must fade back in (otherwise
  // it stays invisible and looks like it vanished).
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
    animate(x, dir * 480, { type: 'spring', stiffness: 200, damping: 28 })
    animate(opacity, 0, { duration: 0.32, onComplete: onDefer })
  }
  const absorb = (cb) => {
    animate(scale, 0.45, { duration: 0.16 })
    animate(opacity, 0.3, { duration: 0.18, onComplete: cb })
  }
  useImperativeHandle(ref, () => ({ flingDown, absorb }), [onDefer]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleDragEnd = (_e, info) => {
    dragging.current = false
    const drop = resolveDrop(info.point)
    if (drop) {
      const r = nodeRef.current?.getBoundingClientRect()
      if (r) {
        const cx = r.left + r.width / 2
        const cy = r.top + r.height / 2
        const tcx = drop.rect.left + drop.rect.width / 2
        const tcy = drop.rect.top + drop.rect.height / 2
        animate(x, x.get() + (tcx - cx), { type: 'spring', stiffness: 240, damping: 26 })
        animate(y, y.get() + (tcy - cy), { type: 'spring', stiffness: 240, damping: 26 })
      }
      animate(scale, 0.18, { duration: 0.3 })
      animate(opacity, 0, { duration: 0.34, onComplete: () => onAssign(drop.personId) })
      return
    }
    if (Math.abs(info.offset.x) > 90) { flingDown(Math.sign(info.offset.x) || 1); return }
    springHome()
  }

  const wrap = { position: 'absolute', left: '50%', top: 8, width: CARD_W, marginLeft: -CARD_W / 2, zIndex: 40 - depth }
  const unitPrice = card.den > 1 ? piecesCost(tx?.unit_price_minor || 0, 1, card.den) : (tx?.unit_price_minor || 0)
  return (
    <motion.div
      ref={nodeRef}
      drag={isTop}
      dragMomentum={false}
      onDragStart={() => { dragging.current = true; animate(scale, 1.06, { duration: 0.12 }) }}
      onDragEnd={handleDragEnd}
      style={{ ...wrap, x, y, scale, opacity, rotate, background: cardGradient(card.txId), pointerEvents: isTop ? 'auto' : 'none' }}
      className={`select-none rounded-2xl px-4 py-5 shadow-xl shadow-black/50 text-black ${isTop ? 'touch-none cursor-grab' : ''}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold text-sm leading-tight line-clamp-2">{tx?.item_name}</div>
        {isTop && (
          <button
            onClick={(e) => { e.stopPropagation(); onRename(card.txId, tx?.item_name || '') }}
            className="shrink-0 opacity-70 hover:opacity-100"
          ><Pencil size={13} /></button>
        )}
      </div>
      <div className="text-3xl font-bold tabular-nums my-2">{fracLabel(card.den)}</div>
      <div className="text-[11px] opacity-80 tabular-nums">
        {formatMinor(unitPrice, currency)}{isTop ? ` · ${remaining} в колоде` : ''}
      </div>
    </motion.div>
  )
})

// ── Person slot (drop target) ───────────────────────────────────────────────────

function PersonSlot({ person, total, count, currency, registerRef, onOpen }) {
  return (
    <motion.button
      layout
      ref={(el) => registerRef(person.id, el)}
      onClick={onOpen}
      className={`rounded-2xl p-3 text-left transition-colors border ${
        count > 0 ? 'border-spotify-light-gray bg-spotify-gray' : 'border-dashed border-spotify-light-gray bg-spotify-dark'
      }`}
    >
      <div className="text-white text-sm font-medium truncate">{person.display_name}</div>
      <div className="text-[11px] text-spotify-text">{count > 0 ? `${count} поз.` : 'пусто'}</div>
      {total > 0 && (
        <div className="text-gold text-sm font-semibold tabular-nums mt-0.5">{formatMinor(total, currency)}</div>
      )}
    </motion.button>
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

  const topCardRef = useRef(null)
  const slotRefs = useRef({})
  const registerRef = useCallback((id, el) => {
    if (el) slotRefs.current[id] = el
    else delete slotRefs.current[id]
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
    for (const p of participants) stat[p.id] = { total: 0, lines: {} }
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
    return stat
  }, [participants, cards, txById])

  const personLines = useCallback((pid) => {
    const lines = personStats[pid]?.lines || {}
    return Object.entries(lines).map(([txId, ln]) => ({
      txId, name: txById[txId]?.item_name || '?', amount: ln.amount, portion: ln.parts.join(' + '),
    }))
  }, [personStats, txById])

  const personCount = useCallback((pid) => Object.keys(personStats[pid]?.lines || {}).length, [personStats])

  // ── Card ops ──
  const assignTop = useCallback((personId) => {
    if (!top) return
    mutate((prev) => prev.map((c) => (c.id === top.id ? { ...c, owner: personId } : c)))
  }, [top, mutate])

  const deferTop = useCallback(() => {
    if (!top) return
    mutate((prev) => { const card = prev.find((c) => c.id === top.id); return [...prev.filter((c) => c.id !== top.id), card] })
  }, [top, mutate])

  // Mitosis: replace the top card with N children of 1/(den·N) at the same spot.
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

  // Glue back: recombine a position's loose pieces into whole units + one reduced
  // fraction. Run an "absorb" shrink on the top card first so it reads as fusing.
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

  const mergeTop = useCallback(() => {
    if (!top) return
    const txId = top.txId
    if (topCardRef.current?.absorb) topCardRef.current.absorb(() => doMerge(txId))
    else doMerge(txId)
  }, [top, doMerge])

  const resolveDrop = useCallback((point) => {
    for (const [pid, el] of Object.entries(slotRefs.current)) {
      const r = el?.getBoundingClientRect?.()
      if (r && point.x >= r.left && point.x <= r.right && point.y >= r.top && point.y <= r.bottom) {
        return { personId: pid, rect: r }
      }
    }
    return null
  }, [])

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
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="px-4 pt-6 pb-44">
      <div className="flex items-center justify-between mb-3">
        <button onClick={onBack} className="text-spotify-text text-sm inline-flex items-center gap-1 hover:text-white">
          <ChevronLeft size={16} /> Назад
        </button>
        <span className="text-[11px] text-spotify-text">{saving ? 'сохраняю…' : 'сохранено'}</span>
      </div>

      <h2 className="text-white text-xl font-bold">{bill.name}</h2>
      <p className="text-spotify-text text-sm mb-4">
        Тащи верхнюю карту на человека · смахни вбок — уйдёт вниз колоды
      </p>

      {/* People grid (drop targets) */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-5">
        {participants.map((p) => (
          <PersonSlot
            key={p.id}
            person={p}
            total={personStats[p.id]?.total || 0}
            count={personCount(p.id)}
            currency={currency}
            registerRef={registerRef}
            onOpen={() => setOpenPerson(p.id)}
          />
        ))}
      </div>

      {/* Card pile */}
      {remaining === 0 ? (
        <div className="text-center text-spotify-text text-sm py-10 bg-spotify-dark rounded-xl">
          Все карточки разложены 🎉
        </div>
      ) : (
        <div className="relative mx-auto" style={{ height: 200, maxWidth: CARD_W }}>
          {deck.slice(0, 4).map((card, i) => (
            <PileCard
              key={card.id}
              ref={i === 0 ? topCardRef : undefined}
              card={card}
              depth={i}
              isTop={i === 0}
              tx={txById[card.txId]}
              currency={currency}
              remaining={remaining}
              resolveDrop={resolveDrop}
              onAssign={assignTop}
              onDefer={deferTop}
              onRename={(txId, name) => setRenaming({ txId, name })}
            />
          ))}
        </div>
      )}

      {/* Bottom action bar (floats above the app's nav) */}
      <div className="fixed inset-x-0 bottom-28 z-30 px-4">
        <div className="max-w-md mx-auto">
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
                  onClick={() => splitTop(n)}
                  className="text-xs px-2.5 py-1.5 rounded-lg bg-spotify-gray text-white hover:bg-spotify-light-gray transition-colors"
                >÷{n}</button>
              ))}
              {canMerge && (
                <button
                  onClick={mergeTop}
                  className="text-xs px-2.5 py-1.5 rounded-lg bg-indigo/20 text-indigo hover:bg-indigo/30 transition-colors inline-flex items-center gap-1"
                ><Merge size={12} /> собрать</button>
              )}
              <button
                onClick={() => (topCardRef.current ? topCardRef.current.flingDown(-1) : deferTop())}
                className="text-xs px-2.5 py-1.5 rounded-lg bg-spotify-gray text-spotify-text hover:text-white inline-flex items-center gap-1"
              ><RotateCcw size={12} /> вниз</button>
            </div>
          )}
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
    </motion.div>
  )
}
