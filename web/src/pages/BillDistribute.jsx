import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import * as Dialog from '@radix-ui/react-dialog'
import { ChevronLeft, Pencil, X, Check, Undo2, PartyPopper, Scissors } from 'lucide-react'
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

// Round a fractional cost (unit_price · count / den) to whole minor units,
// half-up — must match steward/helpers/bills_money.compute_bill_debts.
function piecesCost(unitPrice, count, den) {
  return Math.floor((unitPrice * count + Math.floor(den / 2)) / den)
}

const fracLabel = (den) => (den > 1 ? `1/${den}` : '1 шт')

// ── Pieces model ────────────────────────────────────────────────────────────────
// Each transaction is a bag of "pieces", each a 1/den fraction of one unit owned
// by one person (or null = in the deck). Σ(1/den) === quantity. "Разделить на N"
// turns a piece into N pieces of 1/(den·N). A person holding K pieces of the same
// den shows as "K/N". Persisted as BillItemAssignment{unit_count, debtors, denominator}.

let _seq = 0
const nextPieceId = () => `pc${++_seq}`

function billToPieces(bill) {
  const out = {}
  for (const tx of bill.transactions) {
    const pieces = []
    let covered = 0 // in whole units
    for (const asg of tx.assignments || []) {
      const den = asg.denominator || 1
      const debtors = asg.debtors || []
      if (debtors.length === 0) {
        for (let k = 0; k < asg.unit_count; k++) pieces.push({ id: nextPieceId(), den, owner: null })
        covered += asg.unit_count / den
      } else if (debtors.length === 1) {
        for (let k = 0; k < asg.unit_count; k++) pieces.push({ id: nextPieceId(), den, owner: debtors[0] })
        covered += asg.unit_count / den
      } else {
        // Legacy equal-split: u/den shared by k people → each owns u pieces of 1/(den·k).
        const subDen = den * debtors.length
        for (const d of debtors) {
          for (let k = 0; k < asg.unit_count; k++) pieces.push({ id: nextPieceId(), den: subDen, owner: d })
        }
        covered += asg.unit_count / den
      }
    }
    const remainder = Math.round(tx.quantity - covered)
    for (let k = 0; k < Math.max(0, remainder); k++) pieces.push({ id: nextPieceId(), den: 1, owner: null })
    out[tx.id] = pieces
  }
  return out
}

function piecesToAssignments(arr) {
  // group by owner|den → one assignment per (person, denominator)
  const groups = {}
  for (const p of arr) {
    const key = `${p.owner || ''}|${p.den}`
    if (!groups[key]) groups[key] = { owner: p.owner, den: p.den, count: 0 }
    groups[key].count += 1
  }
  return Object.values(groups).map((g) => ({
    unit_count: g.count,
    debtors: g.owner ? [g.owner] : [],
    denominator: g.den,
  }))
}

// ── Draggable piece card ──────────────────────────────────────────────────────

function PieceCard({ tx, piece, onDropOnPerson }) {
  const handleDragEnd = useCallback((_e, info) => {
    onDropOnPerson(tx.id, piece.id, info.point.x, info.point.y)
  }, [tx.id, piece.id, onDropOnPerson])

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
        text-black px-3 py-2 shadow-lg shadow-black/40 text-left min-w-[72px]"
    >
      <div className="text-xs font-semibold leading-tight line-clamp-1">{tx.item_name}</div>
      <div className="text-[10px] opacity-80 tabular-nums">{fracLabel(piece.den)}</div>
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

const SPLIT_OPTIONS = [2, 3, 4, 6]

// ── Main board ──────────────────────────────────────────────────────────────────

export default function BillDistribute({ bill, persons, onBack, onChange }) {
  const personsById = useMemo(() => Object.fromEntries(persons.map((p) => [p.id, p])), [persons])
  const participants = useMemo(
    () => bill.participants.map((id) => personsById[id]).filter(Boolean),
    [bill.participants, personsById],
  )
  const txById = useMemo(() => Object.fromEntries(bill.transactions.map((t) => [t.id, t])), [bill.transactions])
  const currency = bill.currency

  const [pieces, setPieces] = useState(() => billToPieces(bill))
  const [hotPerson] = useState(null)
  const [openPerson, setOpenPerson] = useState(null)
  const [renaming, setRenaming] = useState(null)
  const [finishing, setFinishing] = useState(false)
  const [saving, setSaving] = useState(false)

  const slotRefs = useRef({})
  const registerRef = useCallback((id, el) => {
    if (el) slotRefs.current[id] = el
    else delete slotRefs.current[id]
  }, [])

  useEffect(() => { setPieces(billToPieces(bill)) }, [bill.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Debounced auto-save ──
  const saveTimer = useRef(null)
  const buildBody = useCallback((src) => ({
    transactions: bill.transactions.map((tx) => ({
      id: tx.id, assignments: piecesToAssignments(src[tx.id] || []),
    })),
  }), [bill.transactions])

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
    setPieces((prev) => {
      const next = updater(prev)
      queueSave(next)
      return next
    })
  }, [queueSave])

  // ── Drop a piece onto whichever person slot is under the release point ──
  const handleDropOnPerson = useCallback((txId, pieceId, x, y) => {
    let target = null
    for (const [pid, el] of Object.entries(slotRefs.current)) {
      const r = el?.getBoundingClientRect?.()
      if (r && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) { target = pid; break }
    }
    if (!target) return
    mutate((prev) => ({
      ...prev,
      [txId]: (prev[txId] || []).map((p) => (p.id === pieceId ? { ...p, owner: target } : p)),
    }))
  }, [mutate])

  // ── Split one unassigned piece (den) of a tx into N smaller pieces ──
  const splitPiece = useCallback((txId, den, n) => {
    mutate((prev) => {
      const arr = [...(prev[txId] || [])]
      const idx = arr.findIndex((p) => p.owner === null && p.den === den)
      if (idx === -1) return prev
      const fresh = Array.from({ length: n }, () => ({ id: nextPieceId(), den: den * n, owner: null }))
      arr.splice(idx, 1, ...fresh)
      return { ...prev, [txId]: arr }
    })
  }, [mutate])

  // ── Return a person's whole share of a tx back to the deck ──
  const returnLine = useCallback((txId, personId) => {
    mutate((prev) => ({
      ...prev,
      [txId]: (prev[txId] || []).map((p) => (p.owner === personId ? { ...p, owner: null } : p)),
    }))
  }, [mutate])

  // ── Derived: deck grouped by tx → den ──
  const deck = useMemo(() => {
    const out = []
    for (const tx of bill.transactions) {
      const free = (pieces[tx.id] || []).filter((p) => p.owner === null)
      if (!free.length) continue
      const byDen = {}
      for (const p of free) (byDen[p.den] = byDen[p.den] || []).push(p)
      out.push({ tx, groups: Object.entries(byDen).map(([den, ps]) => ({ den: Number(den), ps })).sort((a, b) => a.den - b.den) })
    }
    return out
  }, [bill.transactions, pieces])

  const totalRemaining = useMemo(
    () => Object.values(pieces).reduce((s, arr) => s + arr.filter((p) => p.owner === null).length, 0),
    [pieces],
  )

  // ── Per-person stats ──
  const personStats = useMemo(() => {
    const stat = {}
    for (const p of participants) stat[p.id] = { total: 0, lines: {} }
    for (const tx of bill.transactions) {
      const byPersonDen = {}
      for (const pc of pieces[tx.id] || []) {
        if (!pc.owner || !stat[pc.owner]) continue
        const key = `${pc.owner}|${pc.den}`
        byPersonDen[key] = (byPersonDen[key] || 0) + 1
      }
      for (const [key, count] of Object.entries(byPersonDen)) {
        const [owner, denStr] = key.split('|')
        const den = Number(denStr)
        const amount = piecesCost(tx.unit_price_minor, count, den)
        stat[owner].total += amount
        const line = (stat[owner].lines[tx.id] = stat[owner].lines[tx.id] || { amount: 0, parts: [] })
        line.amount += amount
        line.parts.push(den > 1 ? `${count}/${den}` : `${count} шт`)
      }
    }
    return stat
  }, [participants, bill.transactions, pieces])

  const personLines = useCallback((pid) => {
    const lines = personStats[pid]?.lines || {}
    return Object.entries(lines).map(([txId, ln]) => ({
      txId, name: txById[txId]?.item_name || '?', amount: ln.amount, portion: ln.parts.join(' + '),
    }))
  }, [personStats, txById])

  const personCount = useCallback((pid) => Object.keys(personStats[pid]?.lines || {}).length, [personStats])

  // ── Rename ──
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
      await api.put(`/api/bills/${bill.id}/distribution`, buildBody(pieces))
      await api.put(`/api/bills/${bill.id}/finalize`)
      onChange?.()
      onBack()
    } catch { /* noop */ } finally { setSaving(false) }
  }, [bill.id, buildBody, pieces, onBack, onChange])

  // ── Finish summary ──
  if (finishing) {
    const filled = participants.filter((p) => personCount(p.id) > 0)
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="px-4 pt-6 pb-28">
        <button onClick={() => setFinishing(false)} className="text-spotify-text text-sm mb-3 inline-flex items-center gap-1 hover:text-white">
          <ChevronLeft size={16} /> К доске
        </button>
        <h2 className="text-white text-xl font-bold mb-1 inline-flex items-center gap-2"><PartyPopper size={20} className="text-gold" /> Кто что взял</h2>
        <p className="text-spotify-text text-sm mb-4">Проверьте — потом счёт станет итоговым.</p>
        <div className="space-y-3">
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
        Перетаскивай карточки на людей. Осталось: <span className="text-gold font-semibold tabular-nums">{totalRemaining}</span>
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-6">
        {participants.map((p) => (
          <PersonSlot
            key={p.id}
            person={p}
            total={personStats[p.id]?.total || 0}
            count={personCount(p.id)}
            currency={currency}
            hot={hotPerson === p.id}
            registerRef={registerRef}
            onOpen={() => setOpenPerson(p.id)}
          />
        ))}
      </div>

      <div className="space-y-3">
        {deck.length === 0 ? (
          <div className="text-center text-spotify-text text-sm py-6 bg-spotify-dark rounded-xl">Все карточки разложены 🎉</div>
        ) : (
          deck.map(({ tx, groups }) => (
            <div key={tx.id} className="bg-spotify-dark rounded-xl p-3">
              <button
                onClick={() => setRenaming({ txId: tx.id, name: tx.item_name })}
                className="text-white text-sm font-medium inline-flex items-center gap-1.5 min-w-0 mb-2"
              >
                <span className="truncate">{tx.item_name}</span>
                <Pencil size={12} className="text-spotify-text shrink-0" />
                <span className="text-[11px] text-spotify-text font-normal">· {formatMinor(tx.unit_price_minor, currency)}/шт</span>
              </button>
              {groups.map(({ den, ps }) => (
                <div key={den} className="mb-2 last:mb-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[11px] text-spotify-text">{fracLabel(den)} ×{ps.length}</span>
                    <span className="inline-flex items-center gap-1 ml-auto">
                      <Scissors size={11} className="text-spotify-text" />
                      {SPLIT_OPTIONS.map((n) => (
                        <button
                          key={n}
                          onClick={() => splitPiece(tx.id, den, n)}
                          className="text-[11px] px-1.5 py-0.5 rounded bg-spotify-gray text-spotify-text hover:text-white"
                        >÷{n}</button>
                      ))}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <AnimatePresence>
                      {ps.map((piece) => (
                        <PieceCard key={piece.id} tx={tx} piece={piece} onDropOnPerson={handleDropOnPerson} />
                      ))}
                    </AnimatePresence>
                  </div>
                </div>
              ))}
            </div>
          ))
        )}
      </div>

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
