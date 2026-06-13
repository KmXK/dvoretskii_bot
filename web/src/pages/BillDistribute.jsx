import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { motion, useMotionValue, useTransform, useSpring } from 'framer-motion'
import * as Dialog from '@radix-ui/react-dialog'
import { ChevronLeft, Pencil, X, Check, Undo2, PartyPopper, Scissors, RotateCcw } from 'lucide-react'
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

// Stable per-position colour so a deck of the same item shares a tint, and
// different positions read as different "suits".
function hueFor(txId) {
  let h = 0
  for (let i = 0; i < txId.length; i++) h = (h * 31 + txId.charCodeAt(i)) % 360
  return h
}
function cardGradient(txId, depth = 0) {
  const hue = hueFor(txId)
  const l = 64 - depth * 5
  return `linear-gradient(135deg, hsl(${hue} 70% ${l}%), hsl(${hue} 72% ${l - 12}%))`
}

// ── Cards model ───────────────────────────────────────────────────────────────
// One ordered, flat deck of "cards". Each card is a 1/den fraction of one unit of
// a transaction, owned by a person or null (still in the deck). The deck preserves
// order so the top card is deck[0]; deferring sends a card to the bottom and
// splitting drops the copies right under the top. Persisted as
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
const CARD_W = 220

// Top card of the pile: draggable with physics — it leans into the drag
// direction (x→rotate) and the lean is spring-damped, plus a touch of vertical
// lean, so the card feels weighted rather than rigidly pinned to the cursor.
function TopCard({ card, tx, currency, remaining, onDragEnd, onRename }) {
  const x = useMotionValue(0)
  const y = useMotionValue(0)
  const rotateX = useTransform(x, [-220, 220], [-22, 22])
  const rotateY = useTransform(y, [-220, 220], [4, -4])
  const rotateRaw = useTransform([rotateX, rotateY], ([rx, ry]) => rx + ry)
  const rotate = useSpring(rotateRaw, { stiffness: 260, damping: 18, mass: 0.6 })

  return (
    <motion.div
      drag
      dragSnapToOrigin
      onDragEnd={onDragEnd}
      whileDrag={{ scale: 1.06, cursor: 'grabbing' }}
      dragTransition={{ bounceStiffness: 320, bounceDamping: 22 }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      style={{ x, y, rotate, background: cardGradient(card.txId, 0) }}
      className="touch-none select-none cursor-grab rounded-2xl px-4 py-5 shadow-xl shadow-black/50 text-black"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold text-sm leading-tight line-clamp-2">{tx?.item_name}</div>
        <button
          onClick={(e) => { e.stopPropagation(); onRename(card.txId, tx?.item_name || '') }}
          className="shrink-0 opacity-70 hover:opacity-100"
        ><Pencil size={13} /></button>
      </div>
      <div className="text-3xl font-bold tabular-nums my-2">{fracLabel(card.den)}</div>
      <div className="text-[11px] opacity-80 tabular-nums">
        {formatMinor(card.den > 1 ? piecesCost(tx?.unit_price_minor || 0, 1, card.den) : (tx?.unit_price_minor || 0), currency)}
        {' · '}{remaining} в колоде
      </div>
    </motion.div>
  )
}

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

  // ── Card ops (operate on the top card) ──
  const assignTop = useCallback((personId) => {
    if (!top) return
    mutate((prev) => prev.map((c) => (c.id === top.id ? { ...c, owner: personId } : c)))
  }, [top, mutate])

  const deferTop = useCallback(() => {
    if (!top) return
    mutate((prev) => { const rest = prev.filter((c) => c.id !== top.id); return [...rest, prev.find((c) => c.id === top.id)] })
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

  const onTopDragEnd = useCallback((_e, info) => {
    const { x, y } = info.point
    for (const [pid, el] of Object.entries(slotRefs.current)) {
      const r = el?.getBoundingClientRect?.()
      if (r && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) { assignTop(pid); return }
    }
    if (Math.abs(info.offset.x) > 90) deferTop()
  }, [assignTop, deferTop])

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

  const remaining = deck.length

  // ── Board ──
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="px-4 pt-6 pb-8">
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
        <div className="text-center text-spotify-text text-sm py-8 bg-spotify-dark rounded-xl mb-5">
          Все карточки разложены 🎉
        </div>
      ) : (
        <>
          <div className="relative mx-auto mb-3" style={{ height: 200, maxWidth: CARD_W }}>
            {deck.slice(0, 4).map((card, i) => {
              const tx = txById[card.txId]
              const isTop = i === 0
              // Centre with marginLeft (not a transform) so framer's drag x/y and
              // dragSnapToOrigin don't fight the centring.
              const wrap = { position: 'absolute', left: '50%', top: 8, width: CARD_W, marginLeft: -CARD_W / 2, zIndex: 40 - i }
              if (isTop) {
                return (
                  <div key={card.id} style={wrap}>
                    <TopCard
                      card={card}
                      tx={tx}
                      currency={currency}
                      remaining={remaining}
                      onDragEnd={onTopDragEnd}
                      onRename={(txId, name) => setRenaming({ txId, name })}
                    />
                  </div>
                )
              }
              return (
                <motion.div
                  key={card.id}
                  layout
                  initial={false}
                  animate={{ y: i * 8, scale: 1 - i * 0.05, rotate: (i % 2 ? 1 : -1) * i * 1.5 }}
                  style={{ ...wrap, background: cardGradient(card.txId, i) }}
                  className="pointer-events-none rounded-2xl px-4 py-5 shadow-lg shadow-black/40 text-black/80 h-[150px]"
                >
                  <div className="font-semibold text-sm leading-tight line-clamp-2">{tx?.item_name}</div>
                  <div className="text-2xl font-bold tabular-nums my-2 opacity-70">{fracLabel(card.den)}</div>
                </motion.div>
              )
            })}
          </div>

          {/* Top-card controls */}
          <div className="flex items-center justify-center gap-2 mb-5">
            <span className="inline-flex items-center gap-1 text-[11px] text-spotify-text mr-1"><Scissors size={12} /> делить</span>
            {SPLIT_OPTIONS.map((n) => (
              <button
                key={n}
                onClick={() => splitTop(n)}
                className="text-xs px-2.5 py-1 rounded-lg bg-spotify-gray text-white hover:bg-spotify-light-gray transition-colors"
              >÷{n}</button>
            ))}
            <button
              onClick={deferTop}
              className="ml-1 text-xs px-2.5 py-1 rounded-lg bg-spotify-gray text-spotify-text hover:text-white inline-flex items-center gap-1"
            ><RotateCcw size={12} /> вниз</button>
          </div>
        </>
      )}

      {/* Finish (inline — never behind the bottom nav) */}
      {remaining === 0 && (
        <button
          onClick={() => setFinishing(true)}
          className="block w-full bg-gold text-black font-semibold rounded-xl py-3 hover:bg-gold-2 transition-colors"
        >Завершить →</button>
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
