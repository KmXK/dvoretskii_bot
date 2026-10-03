import { useId, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Check, Loader2, Minus, Plus, X } from 'lucide-react'

import { api } from '../../api/client'
import {
  addPortions, assignmentsFromPortions, formatItemMoney, formatPortion,
  getAssignmentsTotal, getDistributionSizeError, getPersonAmounts, getPersonPortions, getUnassignedPortion,
  parsePortion, parsePriceMinor, parseQuantity, retainAssignmentsForQuantity,
} from '../../bills/itemEditor'


function ItemEditorForm({ onClose, onSaved, billId, currency, persons, defaultCreditor, transaction }) {
  const id = useId()
  const [name, setName] = useState(transaction?.item_name || '')
  const [price, setPrice] = useState(transaction ? (transaction.unit_price_minor / 100).toFixed(2).replace('.', ',') : '')
  const [quantity, setQuantity] = useState(String(transaction?.quantity ?? 1))
  const [creditor, setCreditor] = useState(transaction?.creditor || defaultCreditor || '')
  const [portions, setPortions] = useState(() => getPersonPortions(transaction?.assignments || []))
  const [mode, setMode] = useState('units')
  const [selected, setSelected] = useState(() => Object.keys(getPersonPortions(transaction?.assignments || [])))
  const [distributionChanged, setDistributionChanged] = useState(false)
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

  const members = [...membersById.values()]
  const quantityValue = parseQuantity(quantity)
  const priceMinor = parsePriceMinor(price)
  const totalMinor = quantityValue !== null && priceMinor !== null ? quantityValue * priceMinor : null
  let assignments = retainAssignmentsForQuantity(transaction?.assignments || [], transaction?.quantity, quantityValue)
  if (distributionChanged) {
    assignments = mode === 'equal'
      ? selected.length > 0 && quantityValue !== null
        ? [{ unit_count: quantityValue, denominator: 1, debtors: selected }]
        : []
      : assignmentsFromPortions(portions)
  }

  const allocatedAssignments = assignments?.filter((assignment) => assignment.debtors?.length)
  const assigned = allocatedAssignments ? getAssignmentsTotal(allocatedAssignments) : null
  const remaining = allocatedAssignments && quantityValue !== null ? getUnassignedPortion(quantityValue, allocatedAssignments) : null
  const payloadRemaining = assignments && quantityValue !== null ? getUnassignedPortion(quantityValue, assignments) : null
  const amounts = assignments && priceMinor !== null ? getPersonAmounts(assignments, priceMinor, creditor) : {}
  const displayedPortions = mode === 'equal' && assignments ? getPersonPortions(assignments) : portions
  const quantityError = quantityValue === null ? 'Укажи целое количество больше нуля' : null
  const priceError = price && priceMinor === null ? 'Укажи цену больше нуля, до двух знаков после запятой' : null
  const totalError = totalMinor !== null && !Number.isSafeInteger(totalMinor) ? 'Сумма слишком большая' : null
  const distributionSizeError = assignments && quantityValue !== null ? getDistributionSizeError(quantityValue, assignments) : null
  const distributionError = assignments === null
    ? 'Количество у человека должно быть числом или дробью, например 1/2'
    : remaining?.numerator < 0n
      ? `Распределено ${formatPortion(assigned)} шт. при количестве ${quantityValue}. Уменьши доли или измени количество.`
      : payloadRemaining?.numerator < 0n
        ? `В сохранённом распределении учтено больше ${quantityValue} шт. Проверь количество или заново укажи доли.`
        : distributionSizeError
  const canSave = name.trim() && priceMinor !== null && quantityValue !== null
    && membersById.has(creditor) && !totalError && !distributionError

  const updatePortion = (personId, value) => {
    setDistributionChanged(true)
    setPortions((current) => ({ ...current, [personId]: value }))
  }

  const changePortion = (personId, delta) => {
    const current = parsePortion(portions[personId] || '') || parsePortion('0')
    const updated = addPortions(current, { numerator: BigInt(delta), denominator: 1n })
    updatePortion(personId, updated.numerator < 0n ? '0' : formatPortion(updated))
  }

  const changeMode = (nextMode) => {
    if (nextMode === mode) {
      return
    }

    if (nextMode === 'units') {
      setPortions(getPersonPortions(assignments || []))
    } else {
      const allocatedPeople = Object.keys(getPersonPortions(assignments || []))
      setSelected(allocatedPeople.length ? allocatedPeople : members.map((person) => person.id))
    }

    setDistributionChanged(true)
    setMode(nextMode)
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
          <Dialog.Description className="sr-only">Цена за штуку, количество и распределение между участниками счёта</Dialog.Description>
          <form onSubmit={handleSubmit} className="flex min-h-0 flex-col">
            <fieldset disabled={saving} className="min-h-0 space-y-5 overflow-y-auto px-5 pb-5 disabled:opacity-70">
              <div>
                <label htmlFor={`${id}-name`} className="mb-1.5 block text-sm text-spotify-text">Название</label>
                <input id={`${id}-name`} autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="Например, кофе" className={fieldClass} />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor={`${id}-price`} className="mb-1.5 block text-sm text-spotify-text">Цена за штуку</label>
                  <input id={`${id}-price`} inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} placeholder="8,50" aria-invalid={!!priceError} className={fieldClass} />
                </div>
                <div>
                  <label htmlFor={`${id}-quantity`} className="mb-1.5 block text-sm text-spotify-text">Количество, шт.</label>
                  <input id={`${id}-quantity`} inputMode="numeric" value={quantity} onChange={(event) => setQuantity(event.target.value)} aria-invalid={!!quantityError} className={fieldClass} />
                </div>
                {(priceError || quantityError || totalError) && <p className="col-span-2 text-sm text-red-400">{priceError || quantityError || totalError}</p>}
              </div>

              <div className="rounded-2xl border border-gold/20 bg-gold/5 p-4">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm text-spotify-text">Всего за позицию</span>
                  <span className="text-2xl font-semibold text-gold tabular-nums">{totalMinor !== null && !totalError ? formatItemMoney(totalMinor, currency) : '—'}</span>
                </div>
                {totalMinor !== null && !totalError && <div className="mt-1 text-sm text-spotify-text tabular-nums">{formatItemMoney(priceMinor, currency)} × {quantityValue} шт.</div>}
              </div>

              <div>
                <label htmlFor={`${id}-creditor`} className="mb-1.5 block text-sm text-spotify-text">Кто оплатил</label>
                <select id={`${id}-creditor`} value={membersById.has(creditor) ? creditor : ''} onChange={(event) => setCreditor(event.target.value)} className={fieldClass}>
                  <option value="" disabled>Выбери участника</option>
                  {members.map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}
                </select>
              </div>

              <div>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h3 className="text-base font-medium text-white">Кто взял</h3>
                  <div className="inline-flex rounded-xl bg-spotify-gray p-1">
                    {[['units', 'По штукам'], ['equal', 'Поровну']].map(([value, label]) => (
                      <button key={value} type="button" onClick={() => changeMode(value)} aria-pressed={mode === value} className={`min-h-11 rounded-lg px-3 text-sm ${mode === value ? 'bg-gold text-black' : 'text-spotify-text hover:text-white'}`}>{label}</button>
                    ))}
                  </div>
                </div>
                <div className="divide-y divide-white/5">
                  {members.map((person) => {
                    const portion = parsePortion(displayedPortions[person.id] || '')
                    return (
                      <div key={person.id} className="flex items-center justify-between gap-3 py-3">
                        <div className="min-w-0 flex-1">
                          <label htmlFor={`${id}-${person.id}`} className="block break-words text-base font-medium text-white">{person.display_name}</label>
                          <div className="mt-0.5 text-sm text-spotify-text tabular-nums">
                            {formatItemMoney(amounts[person.id] || 0, currency)}{person.id === creditor ? ' · оплатил' : ''}
                          </div>
                          {mode === 'equal' && <div className="mt-0.5 text-sm text-spotify-text">{displayedPortions[person.id] || '0'} шт.</div>}
                        </div>
                        {mode === 'equal' ? (
                          <label className="flex h-11 w-11 shrink-0 items-center justify-center">
                            <input
                              id={`${id}-${person.id}`}
                              type="checkbox"
                              checked={selected.includes(person.id)}
                              onChange={() => setSelected((current) => current.includes(person.id) ? current.filter((personId) => personId !== person.id) : [...current, person.id])}
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
                {mode === 'units' && <p className="mt-2 text-sm text-spotify-text">Для части штуки укажи 0,5 или 1/2.</p>}
                {distributionError ? (
                  <p role="alert" className="mt-3 rounded-xl bg-red-500/10 p-3 text-sm text-red-300">{distributionError}</p>
                ) : remaining && (
                  <div className={`mt-3 rounded-xl p-3 text-sm ${remaining.numerator === 0n ? 'bg-green-500/10 text-green-300' : 'bg-white/5 text-spotify-text'}`}>
                    {remaining.numerator === 0n ? `Распределено ${quantityValue} из ${quantityValue} шт.` : `Осталось распределить ${formatPortion(remaining)} шт. Можно сохранить и распределить позже.`}
                  </div>
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
