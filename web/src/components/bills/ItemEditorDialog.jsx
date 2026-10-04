import { useId, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Check, Loader2, Minus, Plus, X } from 'lucide-react'

import { api } from '../../api/client'
import {
  addPortions, deriveItemDistribution, formatItemMoney, formatPortion,
  getDistributionSizeError, getPersonAmounts, getPersonPortions, getUnassignedDraft, getUnassignedForPortions, getUnassignedPortion,
  parsePortion, parsePriceMinor,
} from '../../bills/itemEditor'


function ItemEditorForm({ onClose, onSaved, billId, currency, persons, defaultCreditor, transaction }) {
  const id = useId()
  const [name, setName] = useState(transaction?.item_name || '')
  const [price, setPrice] = useState(transaction ? (transaction.unit_price_minor / 100).toFixed(2).replace('.', ',') : '')
  const [creditor, setCreditor] = useState(transaction?.creditor || defaultCreditor || '')
  const [portions, setPortions] = useState(() => getPersonPortions(transaction?.assignments || []))
  const [quantityBaseline, setQuantityBaseline] = useState(() => ({ numerator: BigInt(transaction?.quantity || 0), denominator: 1n }))
  const [unassigned, setUnassigned] = useState(() => getUnassignedDraft(transaction))
  const [showUnassigned, setShowUnassigned] = useState(!!unassigned && unassigned !== '0')
  const [preserved, setPreserved] = useState(transaction || null)
  const [sharing, setSharing] = useState(false)
  const [selected, setSelected] = useState([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const membersById = new Map(persons.map((person) => [person.id, person]))
  for (const assignment of transaction?.assignments || []) {
    for (const personId of assignment.debtors || []) {
      if (!membersById.has(personId)) {
        membersById.set(personId, { id: personId, display_name: 'Неизвестный участник' })
      }
    }
  }

  if (transaction?.creditor && !membersById.has(transaction.creditor)) {
    membersById.set(transaction.creditor, { id: transaction.creditor, display_name: 'Плательщик не указан' })
  }

  const members = [...membersById.values()]
  const distribution = deriveItemDistribution({ portions, unassigned, preserved, original: transaction })
  const { assignments, quantity: quantityValue, total: totalPortions, remaining } = distribution
  const priceMinor = parsePriceMinor(price)
  const totalMinor = quantityValue !== null && priceMinor !== null ? quantityValue * priceMinor : null
  const payloadRemaining = assignments && quantityValue !== null ? getUnassignedPortion(quantityValue, assignments) : null
  const amounts = assignments && priceMinor !== null ? getPersonAmounts(assignments, priceMinor, creditor) : {}
  const priceError = price && priceMinor === null ? 'Укажи цену больше нуля, до двух знаков после запятой' : null
  const totalError = totalMinor !== null && !Number.isSafeInteger(totalMinor) ? 'Сумма слишком большая' : null
  const distributionSizeError = assignments && quantityValue !== null ? getDistributionSizeError(quantityValue, assignments) : null
  const distributionError = assignments === null
    ? 'Укажи неотрицательное количество или дробь, например 1/2'
    : totalPortions.denominator !== 1n
      ? `В сумме ${formatPortion(totalPortions)} шт. Дополни доли до целого количества или добавь остаток в «Не распределено».`
      : totalPortions.numerator > 0n && quantityValue === null
        ? 'Количество слишком большое'
        : payloadRemaining?.numerator < 0n
          ? 'В сохранённом распределении есть лишние части. Заново укажи доли.'
          : distributionSizeError
  const canSave = name.trim() && priceMinor !== null && quantityValue !== null
    && membersById.has(creditor) && !totalError && !distributionError

  const updatePortion = (personId, value) => {
    const updatedPortions = { ...portions, [personId]: value }
    const updated = getUnassignedForPortions(quantityBaseline, updatedPortions)
    if (updated !== null && parsePortion(unassigned)) {
      setUnassigned(updated)
      if (updated && updated !== '0') {
        setShowUnassigned(true)
      }
    }

    setPreserved(null)
    setPortions(updatedPortions)
  }

  const updateUnassigned = (value) => {
    setUnassigned(value)
    const updated = deriveItemDistribution({ portions, unassigned: value })
    if (updated.total) {
      setQuantityBaseline(updated.total)
    }
  }

  const changePortion = (personId, delta) => {
    const current = parsePortion(portions[personId] || '') || parsePortion('0')
    const updated = addPortions(current, { numerator: BigInt(delta), denominator: 1n })
    updatePortion(personId, updated.numerator < 0n ? '0' : formatPortion(updated))
  }

  const applyEqualSplit = (personIds) => {
    if (personIds.length === 0) {
      return
    }

    const equalAssignments = [{ unit_count: 1, denominator: 1, debtors: personIds }]
    const equalPortions = getPersonPortions(equalAssignments)
    setPreserved({ quantity: 1, assignments: equalAssignments })
    setPortions(equalPortions)
    const retained = getUnassignedForPortions(quantityBaseline, equalPortions)
    setUnassigned(retained)
    setShowUnassigned(retained !== '0')
    setSelected(personIds)
  }

  const startEqualSplit = () => {
    const allocatedPeople = Object.keys(getPersonPortions(assignments || [])).filter((personId) => personId !== '__unknown__')
    const personIds = allocatedPeople.length ? allocatedPeople : members.filter((person) => person.id !== '__unknown__').map((person) => person.id)
    if (personIds.length === 0) {
      return
    }

    setSharing(true)
    applyEqualSplit(personIds)
  }

  const addUnassigned = () => {
    updateUnassigned('1')
    setShowUnassigned(true)
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!canSave || saving) {
      return
    }

    setSaving(true)
    setError(null)
    try {
      const payload = {
        item_name: name.trim(),
        unit_price_minor: priceMinor,
        quantity: quantityValue,
        creditor,
        assignments,
      }
      const path = `/api/bills/${billId}/transactions`
      const updated = transaction
        ? await api.patch(`${path}/${transaction.id}`, payload)
        : await api.post(path, { ...payload, source: 'manual' })
      onSaved(updated)
      onClose()
    } catch (requestError) {
      setError(requestError.message || 'Не удалось сохранить позицию')
    } finally {
      setSaving(false)
    }
  }

  const close = () => {
    if (!saving) {
      onClose()
    }
  }

  const fieldClass = 'min-h-11 w-full rounded-xl border border-white/10 bg-spotify-gray px-3 py-2.5 text-base text-white outline-none focus:border-gold/70 focus:ring-1 focus:ring-gold/40'

  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) {
          close()
        }
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/70" />
        <Dialog.Content className="fixed bottom-0 left-1/2 z-50 flex max-h-[92dvh] w-full max-w-lg -translate-x-1/2 flex-col rounded-t-3xl border border-white/10 bg-spotify-black shadow-2xl sm:bottom-auto sm:top-1/2 sm:-translate-y-1/2 sm:rounded-3xl">
          <div className="flex items-center justify-between gap-3 px-5 pb-3 pt-4">
            <Dialog.Title className="text-xl font-semibold text-white">{transaction ? 'Изменить позицию' : 'Новая позиция'}</Dialog.Title>
            <button type="button" onClick={close} disabled={saving} aria-label="Закрыть" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-spotify-text hover:bg-white/5 hover:text-white disabled:opacity-40"><X size={21} /></button>
          </div>
          <Dialog.Description className="sr-only">Цена за штуку и доли участников. Общее количество считается автоматически.</Dialog.Description>
          <form onSubmit={handleSubmit} className="flex min-h-0 flex-col">
            <fieldset disabled={saving} className="min-h-0 space-y-5 overflow-y-auto px-5 pb-5 disabled:opacity-70">
              <div>
                <label htmlFor={`${id}-name`} className="mb-1.5 block text-sm text-spotify-text">Название</label>
                <input id={`${id}-name`} autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="Например, кофе" className={fieldClass} />
              </div>

              <div>
                <label htmlFor={`${id}-price`} className="mb-1.5 block text-sm text-spotify-text">Цена за штуку</label>
                <input id={`${id}-price`} inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} placeholder="8,50" aria-invalid={!!priceError} className={fieldClass} />
                {(priceError || totalError) && <p className="mt-2 text-sm text-red-400">{priceError || totalError}</p>}
              </div>

              <div className="rounded-2xl border border-gold/20 bg-gold/5 p-4">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm text-spotify-text">Всего за позицию</span>
                  <span className="text-2xl font-semibold text-gold tabular-nums">{totalMinor !== null && !totalError ? formatItemMoney(totalMinor, currency) : '—'}</span>
                </div>
                <div className="mt-1 text-sm text-spotify-text tabular-nums">
                  {totalPortions ? `${formatPortion(totalPortions)} шт.` : '— шт.'}{priceMinor !== null ? ` × ${formatItemMoney(priceMinor, currency)}` : ''}
                </div>
              </div>

              <div>
                <label htmlFor={`${id}-creditor`} className="mb-1.5 block text-sm text-spotify-text">Кто оплатил</label>
                <select id={`${id}-creditor`} value={membersById.has(creditor) ? creditor : ''} onChange={(event) => setCreditor(event.target.value)} className={fieldClass}>
                  <option value="" disabled>Выбери участника</option>
                  {members.map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}
                </select>
              </div>

              <div>
                <div className="flex items-center justify-between gap-3">
                  <h3 className="shrink-0 text-base font-medium text-white">Кому сколько</h3>
                  <button
                    type="button"
                    onClick={() => {
                      if (sharing) {
                        setSharing(false)
                      } else {
                        startEqualSplit()
                      }
                    }}
                    disabled={members.every((person) => person.id === '__unknown__')}
                    className="min-h-11 rounded-xl bg-white/5 px-3 text-sm font-medium text-gold hover:bg-white/10 disabled:opacity-40"
                  >{sharing ? 'Указать доли' : 'Одну штуку поровну'}</button>
                </div>
                <p className="mt-1 text-sm text-spotify-text">1 — штука; 1/2 — половина</p>
                <div className="divide-y divide-white/5">
                  {members.map((person) => {
                    const portion = parsePortion(portions[person.id] || '')
                    return (
                      <div key={person.id} className="flex items-center justify-between gap-3 py-3">
                        <div className="min-w-0 flex-1">
                          <label htmlFor={`${id}-${person.id}`} className="block break-words text-base font-medium text-white">{person.display_name}</label>
                          <div className="mt-0.5 text-sm text-spotify-text tabular-nums">
                            {formatItemMoney(amounts[person.id] || 0, currency)}{person.id === creditor ? ' · оплатил' : ''}
                          </div>
                          {sharing && <div className="mt-0.5 text-sm text-spotify-text">{portions[person.id] || '0'} шт.</div>}
                        </div>
                        {sharing ? (
                          <label className="flex h-11 w-11 shrink-0 items-center justify-center">
                            <input
                              id={`${id}-${person.id}`}
                              type="checkbox"
                              checked={selected.includes(person.id)}
                              disabled={selected.length === 1 && selected.includes(person.id)}
                              onChange={() => applyEqualSplit(selected.includes(person.id) ? selected.filter((personId) => personId !== person.id) : [...selected, person.id])}
                              className="h-6 w-6 accent-gold"
                            />
                          </label>
                        ) : (
                          <div className="flex shrink-0 items-center rounded-xl bg-spotify-gray">
                            <button type="button" onClick={() => changePortion(person.id, -1)} disabled={!portion || portion.numerator === 0n} aria-label={`Уменьшить количество: ${person.display_name}`} className="flex h-11 w-11 items-center justify-center rounded-l-xl text-white hover:bg-white/5 disabled:opacity-30"><Minus size={17} /></button>
                            <input id={`${id}-${person.id}`} inputMode="decimal" value={portions[person.id] ?? ''} placeholder="0" onChange={(event) => updatePortion(person.id, event.target.value)} aria-invalid={!portion} className="h-11 w-16 border-x border-white/5 bg-transparent px-1 text-center text-base text-white tabular-nums outline-none focus:bg-white/5" />
                            <button type="button" onClick={() => changePortion(person.id, 1)} aria-label={`Увеличить количество: ${person.display_name}`} className="flex h-11 w-11 items-center justify-center rounded-r-xl text-white hover:bg-white/5"><Plus size={17} /></button>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
                {showUnassigned ? (
                  <div className="mt-3 rounded-xl border border-white/10 bg-white/5 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <label htmlFor={`${id}-unassigned`} className="text-base font-medium text-white">Не распределено</label>
                      <div className="flex items-center gap-1">
                        <input id={`${id}-unassigned`} inputMode="decimal" value={unassigned} onChange={(event) => updateUnassigned(event.target.value)} aria-invalid={!remaining} className="h-11 w-20 rounded-lg bg-spotify-gray px-2 text-center text-base text-white tabular-nums outline-none focus:ring-1 focus:ring-gold/40" />
                        <button type="button" onClick={() => { updateUnassigned(''); setShowUnassigned(false) }} aria-label="Убрать нераспределённое количество" className="flex h-11 w-11 items-center justify-center rounded-lg text-spotify-text hover:bg-white/5 hover:text-white"><X size={17} /></button>
                      </div>
                    </div>
                    <p className="mt-1 text-sm text-spotify-text">Входит в общую сумму. Можно назначить людям позже.</p>
                  </div>
                ) : (
                  <button type="button" onClick={addUnassigned} className="mt-3 min-h-11 w-full rounded-xl border border-dashed border-white/15 px-3 text-sm text-spotify-text hover:border-white/30 hover:text-white">Распределить позже</button>
                )}
                {distributionError ? (
                  <p role="alert" className="mt-3 rounded-xl bg-red-500/10 p-3 text-sm text-red-300">{distributionError}</p>
                ) : totalPortions?.numerator === 0n && (
                  <p className="mt-3 text-sm text-spotify-text">Укажи доли людей или выбери «Распределить позже».</p>
                )}
              </div>
            </fieldset>

            <div className="shrink-0 border-t border-white/10 bg-spotify-black px-5 py-4 pb-[max(1rem,env(safe-area-inset-bottom))] sm:rounded-b-3xl">
              {error && <p role="alert" className="mb-3 text-sm text-red-400">{error}</p>}
              <button type="submit" disabled={!canSave || saving} className="flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-gold px-4 py-3 text-base font-semibold text-black transition hover:bg-gold-2 disabled:opacity-40">
                {saving ? <Loader2 size={18} className="animate-spin" /> : <Check size={18} />}
                {saving ? 'Сохраняю…' : transaction ? 'Сохранить изменения' : 'Добавить позицию'}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}


export default function ItemEditorDialog({ open, ...props }) {
  if (!open) {
    return null
  }

  return <ItemEditorForm key={props.transaction?.id || 'new'} {...props} />
}
