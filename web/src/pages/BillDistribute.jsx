import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import * as Dialog from '@radix-ui/react-dialog'
import { ChevronLeft, Pencil, X, Check, Undo2, PartyPopper } from 'lucide-react'
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

// ── Slot ↔ assignment conversion ───────────────────────────────────────────────
// Whole-unit model: each transaction owns `quantity` slots, each holding one
// person_id or null. Fractions ("разделить на N") arrive in iteration 3.

function billToSlots(bill) {
  const slots = {}
  for (const tx of bill.transactions) {
    const arr = new Array(tx.quantity).fill(null)
    let i = 0
    for (const asg of tx.assignments || []) {
      const owner = asg.debtors && asg.debtors.length ? asg.debtors[0] : null
      for (let k = 0; k < asg.unit_count && i < arr.length; k++, i++) arr[i] = owner
    }
    slots[tx.id] = arr
  }
  return slots
}

function slotsToAssignments(arr) {
  const byPerson = {}
  let unassigned = 0
  for (const pid of arr) {
    if (pid) byPerson[pid] = (byPerson[pid] || 0) + 1
    else unassigned += 1
  }
  const out = Object.entries(byPerson).map(([pid, c]) => ({ unit_count: c, debtors: [pid] }))
  if (unassigned > 0) out.push({ unit_count: unassigned, debtors: [] })
  return out
}

// ── Draggable unit card ─────────────────────────────────────────────────────────

function UnitCard({ tx, currency, onDropOnPerson }) {
  const handleDragEnd = useCallback((_e, info) => {
    onDropOnPerson(tx.id, info.point.x, info.point.y)
  }, [tx.id, onDropOnPerson])

  return (
    <motion.button
      layout
      drag
      dragSnapToOrigin
      onDragEnd={handleDragEnd}
      whileDrag={{ scale: 1.12, zIndex: 60, cursor: 'grabbing' }}
      whileTap={{ scale: 1.05 }}
      dragElastic={0.18}
      dragTransition={{ bounceStiffness: 600, bounceDamping: 28 }}
      initial={{ opacity: 0, scale: 0.6 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.5 }}
      className="relative touch-none select-none cursor-grab rounded-xl bg-gradient-to-br from-gold to-gold-2
        text-black px-3 py-2 shadow-lg shadow-black/40 text-left min-w-[88px]"
    >
      <div className="text-xs font-semibold leading-tight line-clamp-2">{tx.item_name}</div>
      <div className="text-[10px] opacity-80 tabular-nums">{formatMinor(tx.unit_price_minor, currency)}</div>
    </motion.button>
  )
}

// ── Person slot (drop target) ───────────────────────────────────────────────────

function PersonSlot({ person, total, count, currency, registerRef, hot, onOpen }) {
  return (
    <motion.button
      layout
      ref={(el) => registerRef(person.id, el)}
      onClick={onOpen}
      animate={hot ? { scale: 1.04 } : { scale: 1 }}
      className={`rounded-2xl p-3 text-left transition-colors border ${
        hot ? 'border-gold bg-gold/15' : count > 0 ? 'border-spotify-light-gray bg-spotify-gray' : 'border-dashed border-spotify-light-gray bg-spotify-dark'
      }`}
    >
      <div className="text-white text-sm font-medium truncate">{person.display_name}</div>
      <div className="text-[11px] text-spotify-text">
        {count > 0 ? `${count} поз.` : 'пусто'}
      </div>
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
                  <div className="text-[11px] text-spotify-text tabular-nums">
                    {ln.count} × {formatMinor(ln.unitPrice, currency)} = {formatMinor(ln.count * ln.unitPrice, currency)}
                  </div>
                </div>
                <button
                  onClick={() => onRemove(ln.txId)}
                  className="ml-2 shrink-0 inline-flex items-center gap-1 text-xs text-red-400"
                ><Undo2 size={14} /> вернуть</button>
              </div>
            ))}
          </div>
          <button onClick={onClose} className="mt-4 w-full bg-spotify-gray text-white rounded-lg py-2">Закрыть</button>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
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

  const [slots, setSlots] = useState(() => billToSlots(bill))
  const [hotPerson, setHotPerson] = useState(null)
  const [openPerson, setOpenPerson] = useState(null)
  const [renaming, setRenaming] = useState(null) // {txId, name}
  const [finishing, setFinishing] = useState(false)
  const [saving, setSaving] = useState(false)

  const slotRefs = useRef({})
  const registerRef = useCallback((id, el) => {
    if (el) slotRefs.current[id] = el
    else delete slotRefs.current[id]
  }, [])

  // Re-seed slots if the bill identity changes (e.g. reload of a different bill).
  useEffect(() => { setSlots(billToSlots(bill)) }, [bill.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Debounced auto-save ──
  const saveTimer = useRef(null)
  const queueSave = useCallback((nextSlots) => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(async () => {
      setSaving(true)
      try {
        await api.put(`/api/bills/${bill.id}/distribution`, {
          transactions: bill.transactions.map((tx) => ({
            id: tx.id,
            assignments: slotsToAssignments(nextSlots[tx.id] || []),
          })),
        })
      } catch { /* keep local state; will retry on next drop */ }
      finally { setSaving(false) }
    }, 600)
  }, [bill.id, bill.transactions])

  useEffect(() => () => { if (saveTimer.current) clearTimeout(saveTimer.current) }, [])

  const mutateSlots = useCallback((updater) => {
    setSlots((prev) => {
      const next = updater(prev)
      queueSave(next)
      return next
    })
  }, [queueSave])

  // ── Drop a unit of `txId` at viewport point → owning person ──
  const handleDropOnPerson = useCallback((txId, x, y) => {
    setHotPerson(null)
    let target = null
    for (const [pid, el] of Object.entries(slotRefs.current)) {
      const r = el?.getBoundingClientRect?.()
      if (r && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) { target = pid; break }
    }
    if (!target) return
    mutateSlots((prev) => {
      const arr = [...(prev[txId] || [])]
      const idx = arr.indexOf(null)
      if (idx === -1) return prev
      arr[idx] = target
      return { ...prev, [txId]: arr }
    })
  }, [mutateSlots])

  const removeOne = useCallback((txId, personId) => {
    mutateSlots((prev) => {
      const arr = [...(prev[txId] || [])]
      const idx = arr.indexOf(personId)
      if (idx === -1) return prev
      arr[idx] = null
      return { ...prev, [txId]: arr }
    })
  }, [mutateSlots])

  // ── Derived ──
  const remainingByTx = useMemo(() => {
    const out = []
    for (const tx of bill.transactions) {
      const left = (slots[tx.id] || []).filter((s) => s === null).length
      if (left > 0) out.push({ tx, left })
    }
    return out
  }, [bill.transactions, slots])

  const totalRemaining = remainingByTx.reduce((s, r) => s + r.left, 0)

  const personStats = useMemo(() => {
    const stat = {}
    for (const p of participants) stat[p.id] = { total: 0, count: 0, lines: {} }
    for (const tx of bill.transactions) {
      for (const pid of slots[tx.id] || []) {
        if (!pid || !stat[pid]) continue
        stat[pid].total += tx.unit_price_minor
        stat[pid].lines[tx.id] = (stat[pid].lines[tx.id] || 0) + 1
      }
    }
    for (const pid of Object.keys(stat)) stat[pid].count = Object.keys(stat[pid].lines).length
    return stat
  }, [participants, bill.transactions, slots])

  const personLines = useCallback((pid) => {
    const lines = personStats[pid]?.lines || {}
    return Object.entries(lines).map(([txId, count]) => ({
      txId, count, name: txById[txId]?.item_name || '?', unitPrice: txById[txId]?.unit_price_minor || 0,
    }))
  }, [personStats, txById])

  // ── Rename a position ──
  const submitRename = useCallback(async () => {
    if (!renaming) return
    const name = renaming.name.trim()
    setRenaming(null)
    if (!name || name === txById[renaming.txId]?.item_name) return
    try {
      await api.patch(`/api/bills/${bill.id}/transactions/${renaming.txId}`, { item_name: name })
      onChange?.()
    } catch { /* noop */ }
  }, [renaming, bill.id, txById, onChange])

  // ── Finalize ──
  const finalize = useCallback(async () => {
    setSaving(true)
    try {
      if (saveTimer.current) clearTimeout(saveTimer.current)
      await api.put(`/api/bills/${bill.id}/distribution`, {
        transactions: bill.transactions.map((tx) => ({
          id: tx.id, assignments: slotsToAssignments(slots[tx.id] || []),
        })),
      })
      await api.put(`/api/bills/${bill.id}/finalize`)
      onChange?.()
      onBack()
    } catch { /* noop */ } finally { setSaving(false) }
  }, [bill.id, bill.transactions, slots, onBack, onChange])

  // ── Finish summary screen ──
  if (finishing) {
    const filled = participants.filter((p) => personStats[p.id]?.count > 0)
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="px-4 pt-6 pb-28">
        <button onClick={() => setFinishing(false)} className="text-spotify-text text-sm mb-3 inline-flex items-center gap-1 hover:text-white">
          <ChevronLeft size={16} /> К доске
        </button>
        <h2 className="text-white text-xl font-bold mb-1 inline-flex items-center gap-2"><PartyPopper size={20} className="text-gold" /> Кто что взял</h2>
        <p className="text-spotify-text text-sm mb-4">Проверьте — потом счёт станет итоговым.</p>
        <div className="space-y-3">
          {filled.map((p) => {
            const st = personStats[p.id]
            return (
              <div key={p.id} className="bg-spotify-dark rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-white font-medium">{p.display_name}</div>
                  <div className="text-gold font-semibold tabular-nums">{formatMinor(st.total, currency)}</div>
                </div>
                <div className="space-y-1">
                  {personLines(p.id).map((ln) => (
                    <div key={ln.txId} className="text-xs text-spotify-text flex justify-between">
                      <span className="truncate mr-2">{ln.name} ×{ln.count}</span>
                      <span className="tabular-nums shrink-0">{formatMinor(ln.count * ln.unitPrice, currency)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
        <div className="fixed bottom-0 inset-x-0 p-4 bg-gradient-to-t from-spotify-black via-spotify-black/95 to-transparent">
          <div className="max-w-md mx-auto flex gap-2">
            <button onClick={() => setFinishing(false)} className="flex-1 bg-spotify-gray text-white rounded-xl py-3">Переделать</button>
            <button onClick={finalize} disabled={saving} className="flex-1 bg-gold text-black font-semibold rounded-xl py-3 disabled:opacity-50 hover:bg-gold-2 transition-colors">
              {saving ? '...' : 'Сохранить итог'}
            </button>
          </div>
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
        Перетаскивай карточки на людей. Осталось разложить: <span className="text-gold font-semibold tabular-nums">{totalRemaining}</span>
      </p>

      {/* People grid (drop targets) */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-6">
        {participants.map((p) => (
          <PersonSlot
            key={p.id}
            person={p}
            total={personStats[p.id]?.total || 0}
            count={personStats[p.id]?.count || 0}
            currency={currency}
            hot={hotPerson === p.id}
            registerRef={registerRef}
            onOpen={() => setOpenPerson(p.id)}
          />
        ))}
      </div>

      {/* Deck grouped by position */}
      <div className="space-y-3">
        {remainingByTx.length === 0 ? (
          <div className="text-center text-spotify-text text-sm py-6 bg-spotify-dark rounded-xl">
            Все карточки разложены 🎉
          </div>
        ) : (
          remainingByTx.map(({ tx, left }) => (
            <div key={tx.id} className="bg-spotify-dark rounded-xl p-3">
              <div className="flex items-center justify-between mb-2">
                <button
                  onClick={() => setRenaming({ txId: tx.id, name: tx.item_name })}
                  className="text-white text-sm font-medium inline-flex items-center gap-1.5 min-w-0"
                >
                  <span className="truncate">{tx.item_name}</span>
                  <Pencil size={12} className="text-spotify-text shrink-0" />
                </button>
                <span className="text-[11px] text-spotify-text tabular-nums shrink-0">{left} ост.</span>
              </div>
              <div className="flex flex-wrap gap-2">
                <AnimatePresence>
                  {Array.from({ length: left }).map((_, i) => (
                    <UnitCard key={`${tx.id}-${i}`} tx={tx} currency={currency} onDropOnPerson={handleDropOnPerson} />
                  ))}
                </AnimatePresence>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Finish */}
      {totalRemaining === 0 && (
        <motion.div
          initial={{ y: 60, opacity: 0 }} animate={{ y: 0, opacity: 1 }}
          className="fixed bottom-0 inset-x-0 p-4 bg-gradient-to-t from-spotify-black via-spotify-black/95 to-transparent"
        >
          <button
            onClick={() => setFinishing(true)}
            className="max-w-md mx-auto block w-full bg-gold text-black font-semibold rounded-xl py-3 hover:bg-gold-2 transition-colors"
          >Завершить →</button>
        </motion.div>
      )}

      <PersonSheet
        open={!!openPerson}
        onClose={() => setOpenPerson(null)}
        person={openPerson ? personsById[openPerson] : null}
        currency={currency}
        total={openPerson ? personStats[openPerson]?.total || 0 : 0}
        lines={openPerson ? personLines(openPerson) : []}
        onRemove={(txId) => removeOne(txId, openPerson)}
      />

      {/* Rename dialog */}
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
