import { useState, useEffect, useMemo, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import * as Dialog from '@radix-ui/react-dialog'
import BackButton from '../components/BackButton'
import { useTelegram } from '../context/TelegramContext'

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

// ── Debt computation (matches steward/helpers/bills_money.py) ────────────────

function computeBillDebts(bill) {
  const debts = {}
  for (const tx of bill.transactions) {
    if (tx.creditor === '__unknown__') continue
    for (const asg of tx.assignments) {
      if (!asg.debtors || asg.debtors.length === 0) continue
      const total = tx.unit_price_minor * asg.unit_count
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
  const { initData } = useTelegram()
  const headers = useMemo(() => ({
    'Content-Type': 'application/json',
    'X-Telegram-Init-Data': initData || '',
  }), [initData])
  return useCallback(async (path, opts = {}) => {
    const res = await fetch(path, { ...opts, headers: { ...headers, ...(opts.headers || {}) } })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
    return data
  }, [headers])
}

// ── Components ────────────────────────────────────────────────────────────────

function DebtSummary({ bills, myPersonId, currency = 'BYN' }) {
  const { iOwe, owedToMe } = useMemo(() => {
    let iOwe = 0
    let owedToMe = 0
    for (const bill of bills) {
      if (bill.closed) continue
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
        <div className="text-white font-medium">{bill.name}</div>
        <div className="text-xs text-spotify-text">#{bill.id} {bill.closed ? '🔒' : '🔓'}</div>
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
        {isAuthor && (
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(tx.id) }}
            className="text-red-400 text-xs ml-2"
          >🗑</button>
        )}
      </div>
      <div className="mt-2 space-y-1">
        {tx.assignments.map((asg, i) => {
          const names = asg.debtors.map(d => personsById[d]?.display_name || '?').join(', ') || '⚠️ не назначено'
          return (
            <div key={i} className="text-xs text-spotify-text">
              ▫ {asg.unit_count} ед. → {names}
            </div>
          )
        })}
      </div>
      <div className="text-xs text-spotify-text/60 mt-1">оплатил {cred}</div>
      {tx.incomplete && (
        <div className="text-xs text-yellow-400 mt-1">⚠ позиция не завершена</div>
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
            <select
              value={creditor}
              onChange={e => setCreditor(e.target.value)}
              className="w-full bg-spotify-gray rounded-lg px-3 py-2 text-white text-sm outline-none"
            >
              <option value="">Кто оплатил...</option>
              {persons.map(p => <option key={p.id} value={p.id}>{p.display_name}</option>)}
            </select>

            <div className="border border-spotify-gray rounded-lg p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-white text-sm font-medium">Назначения</span>
                <button
                  onClick={splitEqually}
                  className="text-xs text-spotify-green"
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
                        className="ml-auto text-red-400 text-xs"
                      >×</button>
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
                              ? 'bg-spotify-green text-black'
                              : 'bg-spotify-gray text-spotify-text'
                          }`}
                        >{p.display_name}</button>
                      ))}
                    </div>
                  </div>
                ))}
                <button
                  onClick={addAssignment}
                  className="w-full text-xs text-spotify-green border border-dashed border-spotify-green/50 rounded py-1"
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
                className="flex-1 bg-spotify-green text-black rounded-lg py-2 font-medium disabled:opacity-50"
              >{loading ? '...' : 'Добавить'}</button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function BillDetail({ bill, persons, myPersonId, isAuthor, onBack, onChange }) {
  const api = useApi()
  const [tab, setTab] = useState('items')
  const [showAdd, setShowAdd] = useState(false)
  const [suggestions, setSuggestions] = useState([])
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

  const handleSuggestionDecide = async (sid, action) => {
    try {
      await api(`/api/bills/suggestions/${sid}/${action}`, { method: 'POST' })
      setSuggestions(s => s.filter(x => x.id !== sid))
      onChange()
    } catch (e) {
      alert(e.message)
    }
  }

  const net = useMemo(() => computeBillDebts(bill), [bill])
  const myDebts = (myPersonId && net[myPersonId]) || {}
  const owedToMe = {}
  for (const [d, creds] of Object.entries(net)) {
    if (d !== myPersonId && creds[myPersonId]) owedToMe[d] = creds[myPersonId]
  }

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="px-4 pt-4">
      <button onClick={onBack} className="text-spotify-text text-sm mb-3">← Назад</button>
      <div className="bg-spotify-dark rounded-xl p-4 mb-4">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-white text-xl font-bold">{bill.name}</h2>
            <div className="text-xs text-spotify-text">
              #{bill.id} · {bill.currency} · {bill.closed ? '🔒 закрыт' : '🔓 открыт'}
            </div>
            <div className="text-xs text-spotify-text mt-1">
              автор: {personsById[bill.author_person_id]?.display_name || '?'}
            </div>
          </div>
          {isAuthor && (
            <div className="flex gap-2">
              <button
                onClick={handleClose}
                className="text-xs bg-spotify-gray rounded px-2 py-1 text-white"
              >{bill.closed ? '🔓' : '🔒'}</button>
            </div>
          )}
        </div>
      </div>

      {suggestions.length > 0 && (
        <div className="bg-yellow-500/10 rounded-xl p-3 mb-4">
          <div className="text-yellow-400 text-sm font-medium mb-2">
            🧾 Предложенные правки ({suggestions.length})
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
                    className="flex-1 bg-green-500/20 text-green-400 rounded py-1 text-xs"
                  >✅ Одобрить</button>
                  <button
                    onClick={() => handleSuggestionDecide(s.id, 'reject')}
                    className="flex-1 bg-red-500/20 text-red-400 rounded py-1 text-xs"
                  >❌ Отклонить</button>
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
              tab === t ? 'bg-spotify-green text-black' : 'bg-spotify-gray text-spotify-text'
            }`}
          >
            {t === 'items' ? 'Позиции' : t === 'debts' ? 'Долги' : 'Платежи'}
          </button>
        ))}
        {isAuthor && !bill.closed && (
          <button
            onClick={() => setShowAdd(true)}
            className="ml-auto bg-spotify-green text-black rounded-lg px-3 py-1.5 text-xs font-medium"
          >+ Позиция</button>
        )}
      </div>

      {tab === 'items' && (
        <div className="space-y-2">
          {bill.transactions.length === 0 && (
            <div className="text-spotify-text text-center text-sm py-4">Нет позиций</div>
          )}
          {bill.transactions.map(tx => (
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
        </div>
      )}

      {tab === 'debts' && (
        <div className="space-y-2">
          {Object.keys(myDebts).length === 0 && Object.keys(owedToMe).length === 0 && (
            <div className="text-spotify-text text-center text-sm py-4">Долгов нет</div>
          )}
          {Object.entries(myDebts).map(([cred, amt]) => (
            <div key={cred} className="bg-red-500/10 rounded-lg p-3 flex justify-between">
              <span className="text-white text-sm">→ {personsById[cred]?.display_name || '?'}</span>
              <span className="text-red-400 font-semibold">{formatMinor(amt, bill.currency)}</span>
            </div>
          ))}
          {Object.entries(owedToMe).map(([deb, amt]) => (
            <div key={deb} className="bg-green-500/10 rounded-lg p-3 flex justify-between">
              <span className="text-white text-sm">← {personsById[deb]?.display_name || '?'}</span>
              <span className="text-green-400 font-semibold">{formatMinor(amt, bill.currency)}</span>
            </div>
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
  const { userId } = useTelegram()
  const [bills, setBills] = useState([])
  const [persons, setPersons] = useState([])
  const [tab, setTab] = useState('open')
  const [scopeAll, setScopeAll] = useState(false)
  const [openBillId, setOpenBillId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')

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

  const handleCreate = async () => {
    if (!newName.trim()) return
    try {
      const data = await api('/api/bills', {
        method: 'POST',
        body: JSON.stringify({ name: newName.trim() }),
      })
      setBills([...bills, data])
      setNewName('')
      setCreating(false)
      setOpenBillId(data.id)
    } catch (e) {
      alert(e.message)
    }
  }

  if (openBill) {
    return (
      <>
        <BackButton />
        <BillDetail
          bill={openBill}
          persons={persons}
          myPersonId={myPerson?.id}
          isAuthor={isAuthor}
          onBack={() => { setOpenBillId(null); reload() }}
          onChange={reload}
        />
      </>
    )
  }

  return (
    <>
      <BackButton />
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="px-4 pt-4">
        <h1 className="text-2xl font-bold text-white mb-1">Счета</h1>
        <p className="text-spotify-text text-sm mb-4">Совместные расходы</p>

        <DebtSummary bills={bills} myPersonId={myPerson?.id} />

        <div className="flex gap-2 mb-4">
          <button
            onClick={() => setTab('open')}
            className={`px-3 py-1.5 rounded-lg text-xs ${tab === 'open' ? 'bg-spotify-green text-black' : 'bg-spotify-gray text-spotify-text'}`}
          >Открытые</button>
          <button
            onClick={() => setTab('closed')}
            className={`px-3 py-1.5 rounded-lg text-xs ${tab === 'closed' ? 'bg-spotify-green text-black' : 'bg-spotify-gray text-spotify-text'}`}
          >Закрытые</button>
          <button
            onClick={() => setCreating(true)}
            className="ml-auto bg-spotify-green text-black rounded-lg px-3 py-1.5 text-xs font-medium"
          >+ Новый</button>
        </div>

        {creating && (
          <div className="bg-spotify-dark rounded-xl p-3 mb-4 flex gap-2">
            <input
              placeholder="Название счёта..."
              value={newName}
              autoFocus
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCreate()}
              className="flex-1 bg-spotify-gray rounded-lg px-3 py-2 text-white text-sm outline-none"
            />
            <button onClick={handleCreate} className="text-spotify-green text-sm">✓</button>
            <button onClick={() => { setCreating(false); setNewName('') }} className="text-spotify-text text-sm">×</button>
          </div>
        )}

        {error && <div className="text-red-400 text-sm mb-3">{error}</div>}

        {loading && bills.length === 0 ? (
          <div className="text-spotify-text text-center py-8">Загрузка...</div>
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
    </>
  )
}
