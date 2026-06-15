import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import WebApp from '@twa-dev/sdk'
import * as Dialog from '@radix-ui/react-dialog'
import { Lock, LockOpen, Trash2, TriangleAlert, Receipt, Check, X, ChevronLeft, Plus, LayoutGrid, Send, Wallet, Loader2, Share2 } from 'lucide-react'
import Loader from '../components/Loader'
import Dropdown from '../components/Dropdown'
import { useAuth } from '../context/useAuth'
import { api } from '../api/client'
import BillDistribute from './BillDistribute'
import BillCreate, { PositionsStep, PeopleManage } from './BillCreate'

// ── Money formatting ─────────────────────────────────────────────────────────

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

function splitMinor(total, n) {
  if (n <= 0) return []
  const base = Math.floor(total / n)
  const rem = total - base * n
  return Array.from({ length: n }, (_, i) => base + (i < rem ? 1 : 0))
}

// Группировка позиций по людям: для каждого должника — его позиции с долей.
function buildPeopleGroups(bill) {
  const groups = {} // personId -> { items: [...], total }
  for (const tx of bill.transactions) {
    for (const asg of tx.assignments) {
      if (!asg.debtors || asg.debtors.length === 0) continue
      const den = asg.denominator || 1
      const total = Math.floor((tx.unit_price_minor * asg.unit_count + Math.floor(den / 2)) / den)
      const shares = splitMinor(total, asg.debtors.length)
      asg.debtors.forEach((d, i) => {
        if (d === '__unknown__') return
        if (!groups[d]) groups[d] = { items: [], total: 0 }
        groups[d].items.push({
          txId: tx.id,
          name: tx.item_name,
          share: shares[i],
          creditor: tx.creditor,
          isPayer: d === tx.creditor,
          locked: !!tx.locked,
        })
        groups[d].total += shares[i]
      })
    }
  }
  return groups
}

// ── Debt computation (matches steward/helpers/bills_money.py) ────────────────

function computeBillDebts(bill) {
  const debts = {}
  for (const tx of bill.transactions) {
    if (tx.creditor === '__unknown__') continue
    for (const asg of tx.assignments) {
      if (!asg.debtors || asg.debtors.length === 0) continue
      const den = asg.denominator || 1
      const total = Math.floor((tx.unit_price_minor * asg.unit_count + Math.floor(den / 2)) / den)
      const shares = splitMinor(total, asg.debtors.length)
      asg.debtors.forEach((d, i) => {
        if (d === tx.creditor || d === '__unknown__') return
        if (!debts[d]) debts[d] = {}
        debts[d][tx.creditor] = (debts[d][tx.creditor] || 0) + shares[i]
      })
    }
  }
  // Apply payments
  for (const p of bill.payments || []) {
    if (p.status !== 'confirmed' && p.status !== 'auto_confirmed') continue
    if (debts[p.debtor] && debts[p.debtor][p.creditor]) {
      debts[p.debtor][p.creditor] -= p.amount_minor
      if (debts[p.debtor][p.creditor] < 0) debts[p.debtor][p.creditor] = 0
    }
  }
  // Net out mutual debts
  const net = {}
  const seen = new Set()
  for (const [d, creds] of Object.entries(debts)) {
    for (const [c, amt] of Object.entries(creds)) {
      const key = `${c}|${d}`
      if (seen.has(key)) continue
      seen.add(`${d}|${c}`)
      const reverse = (debts[c] && debts[c][d]) || 0
      const diff = amt - reverse
      if (diff > 0) {
        if (!net[d]) net[d] = {}
        net[d][c] = diff
      } else if (diff < 0) {
        if (!net[c]) net[c] = {}
        net[c][d] = -diff
      }
    }
  }
  return net
}

// ── API client ────────────────────────────────────────────────────────────────

function useApi() {
  return useCallback(async (path, opts = {}) => {
    const method = (opts.method || 'GET').toUpperCase()
    if (method === 'GET') return api.get(path)
    if (method === 'DELETE') return api.delete(path)
    let body
    if (typeof opts.body === 'string') {
      try { body = JSON.parse(opts.body) } catch { body = opts.body }
    } else {
      body = opts.body
    }
    if (method === 'POST') return api.post(path, body)
    if (method === 'PUT') return api.put(path, body)
    if (method === 'PATCH') return api.patch(path, body)
    throw new Error(`Unsupported method ${method}`)
  }, [])
}

// ── Components ────────────────────────────────────────────────────────────────

function DebtSummary({ bills, myPersonId, currency = 'BYN' }) {
  const { iOwe, owedToMe } = useMemo(() => {
    let iOwe = 0
    let owedToMe = 0
    for (const bill of bills) {
      if (bill.closed) continue
      if (bill.distribution_status && bill.distribution_status !== 'final') continue
      const net = computeBillDebts(bill)
      if (myPersonId && net[myPersonId]) {
        for (const amt of Object.values(net[myPersonId])) iOwe += amt
      }
      for (const [d, creds] of Object.entries(net)) {
        if (d !== myPersonId && creds[myPersonId]) owedToMe += creds[myPersonId]
      }
    }
    return { iOwe, owedToMe }
  }, [bills, myPersonId])

  if (!iOwe && !owedToMe) return null
  return (
    <div className="grid grid-cols-2 gap-3 mb-4">
      <div className="bg-green-500/10 rounded-xl p-3">
        <div className="text-xs text-green-300">Тебе должны</div>
        <div className="text-xl font-bold text-green-400">{formatMinor(owedToMe, currency)}</div>
      </div>
      <div className="bg-red-500/10 rounded-xl p-3">
        <div className="text-xs text-red-300">Ты должен</div>
        <div className="text-xl font-bold text-red-400">{formatMinor(iOwe, currency)}</div>
      </div>
    </div>
  )
}

function BillCard({ bill, myPersonId, personsById, onOpen }) {
  const myNet = useMemo(() => {
    if (bill.distribution_status && bill.distribution_status !== 'final') return 0
    const net = computeBillDebts(bill)
    let iOwe = 0
    let owed = 0
    if (myPersonId && net[myPersonId]) {
      for (const amt of Object.values(net[myPersonId])) iOwe += amt
    }
    for (const [d, creds] of Object.entries(net)) {
      if (d !== myPersonId && creds[myPersonId]) owed += creds[myPersonId]
    }
    return iOwe - owed
  }, [bill, myPersonId])

  const author = personsById[bill.author_person_id]
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-spotify-dark rounded-xl p-4 cursor-pointer hover:bg-spotify-dark/80"
      onClick={onOpen}
    >
      <div className="flex items-start justify-between mb-1">
        <div className="text-white font-medium inline-flex items-center gap-2">
          {bill.name}
          {bill.distribution_status && bill.distribution_status !== 'final' && (
            <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-indigo/20 text-indigo">
              {bill.distribution_status === 'distributing' ? 'распределяется' : 'недозаполнен'}
            </span>
          )}
        </div>
        <div className="text-xs text-spotify-text inline-flex items-center gap-1">#{bill.id} {bill.closed ? <Lock size={12} /> : <LockOpen size={12} />}</div>
      </div>
      <div className="text-xs text-spotify-text">
        {author?.display_name || '?'} · {bill.transactions.length} поз. · {bill.participants.length} уч.
      </div>
      {myNet !== 0 && (
        <div className={`mt-2 text-sm font-semibold ${myNet > 0 ? 'text-red-400' : 'text-green-400'}`}>
          {myNet > 0 ? '−' : '+'}{formatMinor(Math.abs(myNet), bill.currency)}
        </div>
      )}
    </motion.div>
  )
}

// Группа позиций одного человека (вид «По людям»): его доли + итог.
function PersonGroup({ name, group, personsById, currency, isMine }) {
  return (
    <div className={`bg-spotify-gray/50 rounded-lg p-3 ${isMine ? 'border-l-2 border-green-400' : ''}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="text-white text-sm font-semibold truncate">{name}</div>
        <div className="text-gold font-bold tabular-nums">{formatMinor(group.total, currency)}</div>
      </div>
      <div className="space-y-1">
        {group.items.map((it, i) => (
          <div key={i} className="flex items-center justify-between gap-2 text-xs">
            <span className="text-spotify-text truncate flex items-center gap-1 min-w-0">
              {it.locked && <Lock size={11} className="text-spotify-green/70 shrink-0" />}
              <span className="truncate">{it.name}</span>
              {it.isPayer
                ? <span className="text-spotify-text/50 shrink-0">· платил</span>
                : <span className="text-spotify-text/50 shrink-0">→ {personsById[it.creditor]?.display_name || '?'}</span>}
            </span>
            <span className="text-white tabular-nums shrink-0">{formatMinor(it.share, currency)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function TransactionRow({ tx, personsById, currency, isMine, isAuthor, onDelete }) {
  const cred = personsById[tx.creditor]?.display_name || '?'
  const total = tx.unit_price_minor * tx.quantity
  return (
    <div className={`bg-spotify-gray/50 rounded-lg p-3 ${isMine ? 'border-l-2 border-green-400' : ''}`}>
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="text-white text-sm font-medium">{tx.item_name}</div>
          <div className="text-xs text-spotify-text">
            {tx.quantity} × {formatMinor(tx.unit_price_minor, currency)} = {formatMinor(total, currency)}
          </div>
        </div>
        {tx.locked ? (
          <span className="text-spotify-green/70 ml-2" title="По позиции прошла оплата — правка заблокирована"><Lock size={14} /></span>
        ) : isAuthor && (
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(tx.id) }}
            className="text-red-400 ml-2"
          ><Trash2 size={14} /></button>
        )}
      </div>
      <div className="mt-2 space-y-1">
        {tx.assignments.map((asg, i) => {
          const names = asg.debtors.map(d => personsById[d]?.display_name || '?').join(', ')
          const den = asg.denominator || 1
          const portion = den > 1 ? `${asg.unit_count}/${den}` : `${asg.unit_count} ед.`
          return (
            <div key={i} className="text-xs text-spotify-text inline-flex items-center gap-1">
              {!names && <TriangleAlert size={11} className="text-yellow-400" />}
              · {portion} → {names || 'не назначено'}
            </div>
          )
        })}
      </div>
      <div className="text-xs text-spotify-text/60 mt-1">оплатил {cred}</div>
      {tx.incomplete && (
        <div className="text-xs text-yellow-400 mt-1 inline-flex items-center gap-1"><TriangleAlert size={11} /> позиция не завершена</div>
      )}
    </div>
  )
}

function AddItemModal({ open, onClose, billId, persons, onAdded }) {
  const api = useApi()
  const [name, setName] = useState('')
  const [price, setPrice] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [creditor, setCreditor] = useState('')
  const [assignments, setAssignments] = useState([{ unit_count: 1, debtors: [] }])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) {
      setName(''); setPrice(''); setQuantity(1); setCreditor('')
      setAssignments([{ unit_count: 1, debtors: [] }])
      setError(null)
    }
  }, [open])

  const totalAssigned = assignments.reduce((s, a) => s + a.unit_count, 0)

  const splitEqually = () => {
    setAssignments([{ unit_count: quantity, debtors: persons.map(p => p.id) }])
  }

  const addAssignment = () => {
    setAssignments([...assignments, { unit_count: 1, debtors: [] }])
  }

  const updateAsg = (idx, patch) => {
    setAssignments(assignments.map((a, i) => i === idx ? { ...a, ...patch } : a))
  }

  const removeAsg = (idx) => {
    setAssignments(assignments.filter((_, i) => i !== idx))
  }

  const handleSubmit = async () => {
    setError(null)
    if (!name.trim() || !price || !creditor) {
      setError('Заполни все поля')
      return
    }
    setLoading(true)
    try {
      const unit_price_minor = Math.round(parseFloat(price.replace(',', '.')) * 100)
      const data = await api(`/api/bills/${billId}/transactions`, {
        method: 'POST',
        body: JSON.stringify({
          item_name: name.trim(),
          unit_price_minor,
          quantity,
          creditor,
          assignments,
          source: 'manual',
        }),
      })
      onAdded(data)
      onClose()
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onClose}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50
          bg-spotify-black rounded-2xl p-5 w-[calc(100%-2rem)] max-w-md max-h-[85vh] overflow-y-auto">
          <Dialog.Title className="text-white text-lg font-bold mb-4">Новая позиция</Dialog.Title>
          <div className="space-y-3">
            <input
              placeholder="Название"
              value={name}
              onChange={e => setName(e.target.value)}
              className="w-full bg-spotify-gray rounded-lg px-3 py-2 text-white text-sm outline-none"
            />
            <div className="grid grid-cols-2 gap-2">
              <input
                placeholder="Цена за ед."
                inputMode="decimal"
                value={price}
                onChange={e => setPrice(e.target.value)}
                className="bg-spotify-gray rounded-lg px-3 py-2 text-white text-sm outline-none"
              />
              <input
                placeholder="Кол-во"
                type="number"
                min="1"
                value={quantity}
                onChange={e => setQuantity(parseInt(e.target.value) || 1)}
                className="bg-spotify-gray rounded-lg px-3 py-2 text-white text-sm outline-none"
              />
            </div>
            <Dropdown
              value={creditor}
              onChange={v => setCreditor(v)}
              options={persons.map(p => ({ value: p.id, label: p.display_name }))}
              placeholder="Кто оплатил..."
            />

            <div className="border border-spotify-gray rounded-lg p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-white text-sm font-medium">Назначения</span>
                <button
                  onClick={splitEqually}
                  className="text-xs text-gold"
                >Поровну на всех</button>
              </div>
              <div className="space-y-2">
                {assignments.map((asg, i) => (
                  <div key={i} className="bg-spotify-gray/50 rounded p-2">
                    <div className="flex items-center gap-2 mb-1">
                      <input
                        type="number"
                        min="1"
                        value={asg.unit_count}
                        onChange={e => updateAsg(i, { unit_count: parseInt(e.target.value) || 1 })}
                        className="w-16 bg-spotify-gray rounded px-2 py-1 text-white text-xs"
                      />
                      <span className="text-xs text-spotify-text">ед. →</span>
                      <button
                        onClick={() => removeAsg(i)}
                        className="ml-auto text-red-400"
                      ><X size={14} /></button>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {persons.map(p => (
                        <button
                          key={p.id}
                          onClick={() => {
                            const has = asg.debtors.includes(p.id)
                            updateAsg(i, {
                              debtors: has
                                ? asg.debtors.filter(d => d !== p.id)
                                : [...asg.debtors, p.id]
                            })
                          }}
                          className={`text-xs px-2 py-1 rounded ${
                            asg.debtors.includes(p.id)
                              ? 'bg-gold text-black'
                              : 'bg-spotify-gray text-spotify-text'
                          }`}
                        >{p.display_name}</button>
                      ))}
                    </div>
                  </div>
                ))}
                <button
                  onClick={addAssignment}
                  className="w-full text-xs text-gold border border-dashed border-gold/50 rounded py-1"
                >+ Назначение</button>
              </div>
              <div className="text-xs text-spotify-text mt-2">
                Распределено: {totalAssigned}/{quantity}
              </div>
            </div>

            {error && <div className="text-red-400 text-xs">{error}</div>}

            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="flex-1 bg-spotify-gray text-white rounded-lg py-2"
              >Отмена</button>
              <button
                onClick={handleSubmit}
                disabled={loading}
                className="flex-1 bg-gold text-black rounded-lg py-2 font-medium disabled:opacity-50 hover:bg-gold-2 transition-colors"
              >{loading ? '...' : 'Добавить'}</button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

// Строка долга с действием: «Переслал» (я должник) или «Получил» (я кредитор).
// По клику раскрывается инлайн-поле суммы (предзаполнено остатком).
function DebtRow({ direction, name, amount, currency, onSubmit }) {
  const owe = direction === 'owe'
  const [open, setOpen] = useState(false)
  const [val, setVal] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const start = () => {
    setVal(((amount / 100).toFixed(amount % 100 === 0 ? 0 : 2)))
    setErr(null)
    setOpen(true)
  }
  const submit = async () => {
    const minor = Math.round(parseFloat(String(val).replace(',', '.')) * 100)
    if (!minor || minor <= 0) { setErr('Неверная сумма'); return }
    setBusy(true); setErr(null)
    try { await onSubmit(minor); setOpen(false) }
    catch (e) { setErr(e.message || 'Не вышло') }
    finally { setBusy(false) }
  }

  return (
    <motion.div layout className={`rounded-lg overflow-hidden ${owe ? 'bg-red-500/10' : 'bg-green-500/10'}`}>
      <div className="p-3 flex items-center justify-between gap-2">
        <span className="text-white text-sm truncate">{owe ? '→' : '←'} {name}</span>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`font-semibold ${owe ? 'text-red-400' : 'text-green-400'}`}>{formatMinor(amount, currency)}</span>
          <button
            onClick={open ? () => setOpen(false) : start}
            className={`rounded-md px-2 py-1 text-xs inline-flex items-center gap-1 transition ${
              owe ? 'bg-red-500/20 text-red-300 hover:bg-red-500/30' : 'bg-green-500/20 text-green-300 hover:bg-green-500/30'
            }`}
          >
            {owe ? <><Send size={12} /> Переслал</> : <><Wallet size={12} /> Получил</>}
          </button>
        </div>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            className="px-3 pb-3"
          >
            <div className="flex items-center gap-2">
              <input
                value={val} onChange={(e) => setVal(e.target.value)} inputMode="decimal" autoFocus
                onKeyDown={(e) => e.key === 'Enter' && submit()}
                className="flex-1 min-w-0 rounded-lg bg-white/5 px-3 py-2 text-sm text-white outline-none focus:bg-white/10"
              />
              <button
                onClick={submit} disabled={busy}
                className={`rounded-lg px-3 py-2 text-xs font-medium inline-flex items-center gap-1 disabled:opacity-50 ${
                  owe ? 'bg-red-500/25 text-red-200' : 'bg-green-500/25 text-green-200'
                }`}
              >
                {busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
                {owe ? 'Перевёл' : 'Зачесть'}
              </button>
            </div>
            {err && <div className="text-xs text-red-400 mt-1">{err}</div>}
            <div className="text-[11px] text-spotify-text/60 mt-1">
              {owe ? 'Пометится как перевод, ждёт подтверждения получателя' : 'Засчитается сразу как полученный перевод'}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

function BillDetail({ bill, persons, myPersonId, isAuthor, onBack, onChange }) {
  const api = useApi()
  const [tab, setTab] = useState('items')
  const [itemsView, setItemsView] = useState('positions')
  const [showAdd, setShowAdd] = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const peopleGroups = useMemo(() => buildPeopleGroups(bill), [bill])
  const personsById = useMemo(
    () => Object.fromEntries(persons.map(p => [p.id, p])),
    [persons]
  )

  useEffect(() => {
    api(`/api/bills/${bill.id}/suggestions`).then(setSuggestions).catch(() => {})
  }, [api, bill.id])

  const handleDelete = async (txId) => {
    if (!confirm('Удалить позицию?')) return
    await api(`/api/bills/${bill.id}/transactions/${txId}`, { method: 'DELETE' })
    onChange()
  }

  const handleClose = async () => {
    if (!confirm(bill.closed ? 'Открыть счёт?' : 'Закрыть счёт?')) return
    const path = bill.closed ? 'reopen' : 'close'
    await api(`/api/bills/${bill.id}/${path}`, { method: 'PUT' })
    onChange()
  }

  const handleRedistribute = async () => {
    try {
      await api(`/api/bills/${bill.id}/redistribute`, { method: 'PUT' })
      onChange()
    } catch (e) {
      alert(e.status === 409 ? 'По счёту уже есть подтверждённые платежи — распределение заблокировано.' : e.message)
    }
  }

  const handleSuggestionDecide = async (sid, action) => {
    try {
      await api(`/api/bills/suggestions/${sid}/${action}`, { method: 'POST' })
      setSuggestions(s => s.filter(x => x.id !== sid))
      onChange()
    } catch (e) {
      alert(e.message)
    }
  }

  const payForward = async (creditorId, amountMinor) => {
    await api('/api/bills/payments', { method: 'POST', body: {
      creditor: creditorId, amount_minor: amountMinor, currency: bill.currency, bill_ids: [bill.id],
    } })
    onChange()
  }

  const markReceived = async (debtorId, amountMinor) => {
    await api('/api/bills/payments/received', { method: 'POST', body: {
      debtor: debtorId, amount_minor: amountMinor, currency: bill.currency, bill_ids: [bill.id],
    } })
    onChange()
  }

  const [sharing, setSharing] = useState(false)
  const shareImage = async () => {
    if (!WebApp.isVersionAtLeast?.('8.0') || typeof WebApp.shareMessage !== 'function') {
      alert('Обновите Telegram — нужен шеринг сообщений (8.0+)')
      return
    }
    setSharing(true)
    try {
      const { prepared_message_id } = await api(`/api/bills/${bill.id}/share-image`, { method: 'POST' })
      WebApp.shareMessage(prepared_message_id)
    } catch (e) {
      alert(e.message || 'Не удалось подготовить картинку')
    } finally {
      setSharing(false)
    }
  }

  const net = useMemo(() => computeBillDebts(bill), [bill])
  const myDebts = (myPersonId && net[myPersonId]) || {}
  const owedToMe = {}
  for (const [d, creds] of Object.entries(net)) {
    if (d !== myPersonId && creds[myPersonId]) owedToMe[d] = creds[myPersonId]
  }

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="px-4 pt-6 pb-4">
      <button onClick={onBack} className="text-spotify-text text-sm mb-3 hover:text-white transition-colors inline-flex items-center gap-1"><ChevronLeft size={16} /> Назад</button>
      <div className="bg-spotify-dark rounded-xl p-4 mb-4">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-white text-xl font-bold">{bill.name}</h2>
            <div className="text-xs text-spotify-text inline-flex items-center gap-1">
              #{bill.id} · {bill.currency} · {bill.closed ? <><Lock size={12} /> закрыт</> : <><LockOpen size={12} /> открыт</>}
            </div>
            <div className="text-xs text-spotify-text mt-1">
              автор: {personsById[bill.author_person_id]?.display_name || '?'}
            </div>
          </div>
          {isAuthor && (
            <div className="flex gap-2">
              {!bill.closed && bill.transactions.length > 0 && (
                <button
                  onClick={handleRedistribute}
                  className="bg-spotify-gray rounded px-2 py-1.5 text-white hover:bg-spotify-light-gray transition-colors"
                  title="Распределить по людям"
                ><LayoutGrid size={14} /></button>
              )}
              <button
                onClick={handleClose}
                className="bg-spotify-gray rounded px-2 py-1.5 text-white hover:bg-spotify-light-gray transition-colors"
                title={bill.closed ? 'Открыть счёт' : 'Закрыть счёт'}
              >{bill.closed ? <LockOpen size={14} /> : <Lock size={14} />}</button>
            </div>
          )}
        </div>
      </div>

      {suggestions.length > 0 && (
        <div className="bg-yellow-500/10 rounded-xl p-3 mb-4">
          <div className="text-yellow-400 text-sm font-medium mb-2 inline-flex items-center gap-1.5">
            <Receipt size={14} /> Предложенные правки ({suggestions.length})
          </div>
          {suggestions.map(s => (
            <div key={s.id} className="bg-spotify-dark rounded-lg p-3 mb-2">
              <div className="text-xs text-spotify-text">
                от {personsById[s.proposed_by_person_id]?.display_name || '?'}
              </div>
              <div className="space-y-1 mt-1">
                {s.proposed_tx.map(tx => (
                  <div key={tx.id} className="text-xs text-white">
                    • {tx.item_name} × {tx.quantity} — {formatMinor(tx.unit_price_minor * tx.quantity, bill.currency)}
                  </div>
                ))}
              </div>
              {isAuthor && (
                <div className="flex gap-2 mt-2">
                  <button
                    onClick={() => handleSuggestionDecide(s.id, 'approve')}
                    className="flex-1 bg-green-500/20 text-green-400 rounded py-1 text-xs inline-flex items-center justify-center gap-1"
                  ><Check size={13} /> Одобрить</button>
                  <button
                    onClick={() => handleSuggestionDecide(s.id, 'reject')}
                    className="flex-1 bg-red-500/20 text-red-400 rounded py-1 text-xs inline-flex items-center justify-center gap-1"
                  ><X size={13} /> Отклонить</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-2 mb-4">
        {['items', 'debts', 'payments'].map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 rounded-lg text-xs ${
              tab === t ? 'bg-gold text-black' : 'bg-spotify-gray text-spotify-text'
            }`}
          >
            {t === 'items' ? 'Позиции' : t === 'debts' ? 'Долги' : 'Платежи'}
          </button>
        ))}
        {isAuthor && !bill.closed && (
          <button
            onClick={() => setShowAdd(true)}
            className="ml-auto bg-gold text-black rounded-lg px-3 py-1.5 text-xs font-medium inline-flex items-center gap-1 hover:bg-gold-2 transition-colors"
          ><Plus size={14} /> Позиция</button>
        )}
      </div>

      {tab === 'items' && (
        <div className="space-y-2">
          {bill.transactions.length > 0 && (
            <div className="inline-flex rounded-lg bg-spotify-gray p-0.5 mb-1">
              {[['positions', 'По позициям'], ['people', 'По людям']].map(([v, label]) => (
                <button
                  key={v}
                  onClick={() => setItemsView(v)}
                  className={`px-3 py-1 rounded-md text-xs transition ${
                    itemsView === v ? 'bg-gold text-black font-medium' : 'text-spotify-text'
                  }`}
                >{label}</button>
              ))}
            </div>
          )}
          {bill.transactions.length === 0 && (
            <div className="text-spotify-text text-center text-sm py-4">Нет позиций</div>
          )}
          {itemsView === 'positions' && bill.transactions.map(tx => (
            <TransactionRow
              key={tx.id}
              tx={tx}
              personsById={personsById}
              currency={bill.currency}
              isMine={tx.assignments.some(a => a.debtors.includes(myPersonId))}
              isAuthor={isAuthor}
              onDelete={handleDelete}
            />
          ))}
          {itemsView === 'people' && (
            Object.keys(peopleGroups).length === 0 ? (
              <div className="text-spotify-text text-center text-sm py-4">Позиции ещё не распределены</div>
            ) : (
              Object.entries(peopleGroups)
                .sort((a, b) => (personsById[a[0]]?.display_name || '').localeCompare(personsById[b[0]]?.display_name || ''))
                .map(([pid, group]) => (
                  <PersonGroup
                    key={pid}
                    name={personsById[pid]?.display_name || '?'}
                    group={group}
                    personsById={personsById}
                    currency={bill.currency}
                    isMine={pid === myPersonId}
                  />
                ))
            )
          )}
        </div>
      )}

      {tab === 'debts' && (
        <div className="space-y-2">
          <button
            onClick={shareImage}
            disabled={sharing}
            className="w-full rounded-lg bg-gold/15 border border-gold/30 text-gold py-2.5 text-sm font-medium inline-flex items-center justify-center gap-2 hover:bg-gold/25 disabled:opacity-50 transition"
          >
            {sharing ? <Loader2 size={15} className="animate-spin" /> : <Share2 size={15} />}
            Поделиться итогом
          </button>
          {Object.keys(myDebts).length === 0 && Object.keys(owedToMe).length === 0 && (
            <div className="text-spotify-text text-center text-sm py-4">Долгов нет</div>
          )}
          {Object.entries(myDebts).map(([cred, amt]) => (
            <DebtRow
              key={cred} direction="owe" amount={amt} currency={bill.currency}
              name={personsById[cred]?.display_name || '?'}
              onSubmit={(minor) => payForward(cred, minor)}
            />
          ))}
          {Object.entries(owedToMe).map(([deb, amt]) => (
            <DebtRow
              key={deb} direction="owed" amount={amt} currency={bill.currency}
              name={personsById[deb]?.display_name || '?'}
              onSubmit={(minor) => markReceived(deb, minor)}
            />
          ))}
        </div>
      )}

      {tab === 'payments' && (
        <div className="space-y-2">
          {(bill.payments || []).length === 0 && (
            <div className="text-spotify-text text-center text-sm py-4">Платежей нет</div>
          )}
          {(bill.payments || []).map(p => (
            <div key={p.id} className="bg-spotify-dark rounded-lg p-3">
              <div className="flex justify-between text-sm">
                <span className="text-white">
                  {personsById[p.debtor]?.display_name || '?'} → {personsById[p.creditor]?.display_name || '?'}
                </span>
                <span className="font-semibold">{formatMinor(p.amount_minor, p.currency)}</span>
              </div>
              <div className={`text-xs mt-1 ${
                p.status === 'confirmed' ? 'text-green-400' :
                p.status === 'pending' ? 'text-yellow-400' : 'text-red-400'
              }`}>{p.status}</div>
            </div>
          ))}
        </div>
      )}

      <AddItemModal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        billId={bill.id}
        persons={persons.filter(p => bill.participants.includes(p.id))}
        onAdded={() => onChange()}
      />
    </motion.div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function BillsPage() {
  const api = useApi()
  const { userId } = useAuth()
  const [bills, setBills] = useState([])
  const [persons, setPersons] = useState([])
  const [tab, setTab] = useState('open')
  const [scopeAll, setScopeAll] = useState(false)
  const [openBillId, setOpenBillId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [editPositionsId, setEditPositionsId] = useState(null)
  const [managePeopleId, setManagePeopleId] = useState(null)

  const reload = useCallback(async () => {
    try {
      setLoading(true)
      const data = await api(`/api/bills${scopeAll ? '?scope=all' : ''}`)
      setBills(data.bills || [])
      setPersons(data.persons || [])
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [api, scopeAll])

  useEffect(() => { reload() }, [reload])
  useEffect(() => {
    const t = setInterval(reload, 30000)
    return () => clearInterval(t)
  }, [reload])

  // Deep link `startapp=bill_<id>` → jump into that bill once. Guard with a ref so
  // it fires a single time: start_param persists, and every reload mutates `bills`,
  // which would otherwise keep yanking the user back into the bill forever.
  const deepLinkConsumed = useRef(false)
  useEffect(() => {
    if (deepLinkConsumed.current) return
    const raw = WebApp?.initDataUnsafe?.start_param || ''
    const m = /^bill_(\d+)$/.exec(raw)
    if (m && bills.some((b) => b.id === Number(m[1]))) {
      deepLinkConsumed.current = true
      setOpenBillId(Number(m[1]))
    }
  }, [bills])

  const personsById = useMemo(
    () => Object.fromEntries(persons.map(p => [p.id, p])),
    [persons]
  )
  const myPerson = useMemo(
    () => persons.find(p => p.telegram_id === userId),
    [persons, userId]
  )

  const filteredBills = bills.filter(b => tab === 'open' ? !b.closed : b.closed)
  const openBill = openBillId ? bills.find(b => b.id === openBillId) : null
  const isAuthor = openBill && myPerson && openBill.author_person_id === myPerson.id

  const needsDistribution = openBill
    && openBill.distribution_status && openBill.distribution_status !== 'final'
    && openBill.transactions.length > 0
    && !openBill.closed

  if (showCreate) {
    return (
      <BillCreate
        onCancel={() => setShowCreate(false)}
        onReady={(billId) => { setShowCreate(false); reload(); setOpenBillId(billId) }}
      />
    )
  }

  if (openBill && isAuthor && managePeopleId === openBill.id) {
    return (
      <div className="max-w-3xl mx-auto">
        <PeopleManage
          bill={openBill}
          onDone={async () => { await reload(); setManagePeopleId(null) }}
          onBack={async () => { await reload(); setManagePeopleId(null) }}
        />
      </div>
    )
  }

  if (openBill && isAuthor && editPositionsId === openBill.id) {
    const counts = {}
    for (const t of openBill.transactions) {
      if (t.creditor && t.creditor !== '__unknown__') counts[t.creditor] = (counts[t.creditor] || 0) + 1
    }
    const defPayer = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || openBill.author_person_id
    return (
      <div className="max-w-3xl mx-auto">
        <PositionsStep
          bill={openBill}
          defaultPayer={defPayer}
          onBack={async () => { await reload(); setEditPositionsId(null) }}
          onReady={async () => { await reload(); setEditPositionsId(null) }}
          onDeleted={() => { setEditPositionsId(null); setOpenBillId(null); reload() }}
          onPeople={() => { setEditPositionsId(null); setManagePeopleId(openBill.id) }}
        />
      </div>
    )
  }

  if (openBill && needsDistribution && isAuthor) {
    return (
      <div className="max-w-3xl mx-auto">
        <BillDistribute
          bill={openBill}
          persons={persons}
          onBack={() => { setOpenBillId(null); reload() }}
          onChange={reload}
          onEditPositions={() => setEditPositionsId(openBill.id)}
          onManagePeople={() => setManagePeopleId(openBill.id)}
        />
      </div>
    )
  }

  if (openBill) {
    return (
      <div className="max-w-3xl mx-auto">
        <BillDetail
          bill={openBill}
          persons={persons}
          myPersonId={myPerson?.id}
          isAuthor={isAuthor}
          onBack={() => { setOpenBillId(null); reload() }}
          onChange={reload}
        />
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="px-4 pt-6 pb-4">
        <h1 className="text-2xl font-bold text-white mb-1">Счета</h1>
        <p className="text-spotify-text text-sm mb-4">Совместные расходы</p>

        <DebtSummary bills={bills} myPersonId={myPerson?.id} />

        <div className="flex gap-2 mb-4">
          <button
            onClick={() => setTab('open')}
            className={`px-3 py-1.5 rounded-lg text-xs ${tab === 'open' ? 'bg-gold text-black' : 'bg-spotify-gray text-spotify-text'}`}
          >Открытые</button>
          <button
            onClick={() => setTab('closed')}
            className={`px-3 py-1.5 rounded-lg text-xs ${tab === 'closed' ? 'bg-gold text-black' : 'bg-spotify-gray text-spotify-text'}`}
          >Закрытые</button>
          <button
            onClick={() => setShowCreate(true)}
            className="ml-auto bg-gold text-black rounded-lg px-3 py-1.5 text-xs font-medium inline-flex items-center gap-1 hover:bg-gold-2 transition-colors"
          ><Plus size={14} /> Новый</button>
        </div>

        {error && <div className="text-red-400 text-sm mb-3">{error}</div>}

        {loading && bills.length === 0 ? (
          <div className="flex items-center justify-center py-10"><Loader scale={0.6} /></div>
        ) : filteredBills.length === 0 ? (
          <div className="text-spotify-text text-center py-8">
            {tab === 'open' ? 'Нет открытых счетов' : 'Нет закрытых счетов'}
          </div>
        ) : (
          <div className="space-y-2">
            <AnimatePresence>
              {filteredBills.map(b => (
                <BillCard
                  key={b.id}
                  bill={b}
                  myPersonId={myPerson?.id}
                  personsById={personsById}
                  onOpen={() => setOpenBillId(b.id)}
                />
              ))}
            </AnimatePresence>
          </div>
        )}
      </motion.div>
    </div>
  )
}
