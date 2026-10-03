import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronLeft, History, RefreshCw } from 'lucide-react'

import { api } from '../../api/client'
import Dropdown from '../Dropdown'
import Loader from '../Loader'


function matchesFilters(entry, filters, personId) {
  if (filters.direction === 'owe' && entry.debtor !== personId) {
    return false
  }

  if (filters.direction === 'owed' && entry.creditor !== personId) {
    return false
  }

  return (!filters.debtor || entry.debtor === filters.debtor)
    && (!filters.creditor || entry.creditor === filters.creditor)
    && (!filters.currency || entry.currency === filters.currency)
}


function eventTitle(event, personId) {
  if (event.type === 'payment') {
    return event.debtor === personId ? 'Оплата' : 'Получено'
  }

  if (event.type === 'close') {
    return 'Закрытие счёта'
  }

  if (event.type === 'adjustment') {
    return 'Корректировка переплаты'
  }

  const billName = event.bills?.[0]?.name
  return billName ? `Начисление: ${billName}` : 'Начисление по счёту'
}


function eventDateLabel(event, formatDateTime) {
  if (!event.date) {
    return 'Дата не сохранена'
  }

  const start = formatDateTime(event.date)
  if (!event.date_to || event.date_to === event.date) {
    return start
  }

  const end = formatDateTime(event.date_to)
  return start === end ? start : `Период: ${start} — ${end}`
}


export default function DebtHistory({ filters, onFiltersChange, onBack, onOpenBill, formatMinor, formatDateTime }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [limit, setLimit] = useState(50)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await api.get('/api/bills/history'))
    } catch (requestError) {
      setError(requestError.message || 'Не получилось загрузить историю')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let active = true
    api.get('/api/bills/history')
      .then((payload) => { if (active) setData(payload) })
      .catch((requestError) => { if (active) setError(requestError.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const personsById = useMemo(
    () => Object.fromEntries((data?.persons || []).map((person) => [person.id, person])),
    [data]
  )
  const peopleOptions = useMemo(() => [
    { value: '', label: 'Все' },
    ...(data?.persons || [])
      .slice()
      .sort((left, right) => left.display_name.localeCompare(right.display_name))
      .map((person) => ({
        value: person.id,
        label: person.id === data.person_id ? `${person.display_name} (я)` : person.display_name,
      })),
  ], [data])
  const currencyOptions = useMemo(() => [
    { value: '', label: 'Все валюты' },
    ...[...new Set((data?.events || []).map((event) => event.currency))]
      .sort()
      .map((currency) => ({ value: currency, label: currency })),
  ], [data])
  const events = useMemo(
    () => (data?.events || []).filter((event) => matchesFilters(event, filters, data.person_id)),
    [data, filters]
  )
  const balances = useMemo(
    () => (data?.balances || []).filter((entry) => matchesFilters(entry, filters, data.person_id)),
    [data, filters]
  )

  const changeFilter = (field, value) => {
    onFiltersChange({ ...filters, [field]: value })
    setLimit(50)
  }
  const personName = (id) => personsById[id]?.display_name || '?'
  const balanceLabel = (amount, currency) => amount < 0
    ? `переплата ${formatMinor(-amount, currency)}`
    : formatMinor(amount, currency)

  return (
    <div className="max-w-3xl mx-auto px-4 pt-6 pb-8">
      <button
        type="button"
        onClick={onBack}
        className="mb-3 inline-flex items-center gap-1 text-sm text-spotify-text hover:text-white"
      ><ChevronLeft size={16} /> К счетам</button>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h1 className="inline-flex items-center gap-2 text-2xl font-bold text-white">
            <History size={23} className="text-gold" /> История долгов
          </h1>
          <p className="mt-1 text-sm text-spotify-text">Твои расчёты во всех чатах, включая закрытые счета</p>
        </div>
        <button
          type="button"
          onClick={reload}
          disabled={loading}
          aria-label="Обновить историю"
          className="rounded-xl bg-white/5 p-2.5 text-white hover:bg-white/10 disabled:opacity-50"
        ><RefreshCw size={17} className={loading ? 'animate-spin' : ''} /></button>
      </div>

      <div className="mb-4 rounded-xl bg-spotify-dark p-3">
        <div className="mb-3 flex flex-wrap gap-2">
          {[['all', 'Все'], ['owed', 'Мне должны'], ['owe', 'Я должен']].map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => changeFilter('direction', value)}
              className={`rounded-lg px-3 py-1.5 text-xs ${filters.direction === value ? 'bg-gold text-black' : 'bg-spotify-gray text-spotify-text'}`}
            >{label}</button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="mb-1 text-xs text-spotify-text">Отправитель / должник</div>
            <Dropdown compact value={filters.debtor} onChange={(value) => changeFilter('debtor', value)} options={peopleOptions} />
          </div>
          <div>
            <div className="mb-1 text-xs text-spotify-text">Получатель</div>
            <Dropdown compact value={filters.creditor} onChange={(value) => changeFilter('creditor', value)} options={peopleOptions} />
          </div>
          <div>
            <Dropdown compact value={filters.currency} onChange={(value) => changeFilter('currency', value)} options={currencyOptions} />
          </div>
          <button
            type="button"
            onClick={() => { onFiltersChange({ direction: 'all', debtor: '', creditor: '', currency: '' }); setLimit(50) }}
            className="text-right text-xs text-spotify-text hover:text-white"
          >Сбросить фильтры</button>
        </div>
      </div>

      {balances.length > 0 && (
        <div className="mb-4 rounded-xl border border-gold/20 bg-gold/5 p-3">
          <div className="mb-2 text-xs font-semibold text-gold">Сейчас по выбранным людям</div>
          <div className="space-y-2">
            {balances.map((entry) => (
              <div key={`${entry.debtor}:${entry.creditor}:${entry.currency}`} className="flex items-start justify-between gap-3 text-xs">
                <span className="text-spotify-text">{personName(entry.debtor)} → {personName(entry.creditor)}</span>
                <span className="text-right font-semibold text-white tabular-nums">{balanceLabel(entry.amount_minor, entry.currency)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {data && balances.length === 0 && events.length > 0 && (
        <div className="mb-4 rounded-xl border border-green-400/20 bg-green-400/5 p-3 text-sm text-green-300">
          Сейчас по выбранным людям долга и переплаты нет.
        </div>
      )}

      {error && <div className="mb-3 text-sm text-red-400">{error}</div>}
      {loading && !data ? (
        <div className="flex justify-center py-10"><Loader scale={0.6} /></div>
      ) : events.length === 0 ? (
        <div className="py-8 text-center text-sm text-spotify-text">По этим фильтрам истории нет</div>
      ) : (
        <div className="space-y-3">
          {events.slice(0, limit).map((event) => (
            <div key={event.id} className="rounded-xl bg-spotify-dark p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-white">{eventTitle(event, data.person_id)}</div>
                  <div className="mt-0.5 text-xs text-spotify-text">{eventDateLabel(event, formatDateTime)}</div>
                </div>
                {event.type === 'charge' ? (
                  <div className="shrink-0 text-right">
                    <div className="text-xs text-spotify-text">По этому счёту</div>
                    <div className="text-sm font-semibold text-gold tabular-nums">{formatMinor(event.amount_minor, event.currency)}</div>
                  </div>
                ) : event.type !== 'close' && event.amount_minor > 0 && (
                  <span className="shrink-0 text-sm font-semibold text-gold tabular-nums">{formatMinor(event.amount_minor, event.currency)}</span>
                )}
              </div>
              <div className="my-2 text-sm text-white">{personName(event.debtor)} → {personName(event.creditor)}</div>
              {event.balance_known === false ? (
                <div className="rounded-lg bg-black/15 p-2.5 text-xs text-spotify-text">
                  Исторический остаток неизвестен: дата закрытия счёта не сохранена.
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-2 rounded-lg bg-black/15 p-2.5 text-xs">
                  <div>
                    <div className="mb-1 text-spotify-text">Было</div>
                    <div className="text-white tabular-nums">{balanceLabel(event.before_minor, event.currency)}</div>
                  </div>
                  <div>
                    <div className="mb-1 text-spotify-text">Изменение</div>
                    <div className={`tabular-nums ${event.delta_minor > 0 ? 'text-gold' : event.delta_minor < 0 ? 'text-green-400' : 'text-spotify-text'}`}>
                      {event.delta_minor > 0 ? '+' : ''}{formatMinor(event.delta_minor, event.currency)}
                    </div>
                  </div>
                  <div>
                    <div className="mb-1 text-spotify-text">Стало</div>
                    <div className="font-semibold text-white tabular-nums">{balanceLabel(event.after_minor, event.currency)}</div>
                  </div>
                </div>
              )}
              {(event.items || []).length > 0 && (
                <div className="mt-3 space-y-1 text-xs text-spotify-text">
                  <div className="text-[10px] uppercase tracking-wide text-spotify-text/70">Позиции</div>
                  {(event.items || []).map((item, index) => (
                    <div key={index} className="flex justify-between gap-3">
                      <span>{item.name}</span>
                      <span className="shrink-0 tabular-nums">{formatMinor(item.amount_minor, event.currency)}</span>
                    </div>
                  ))}
                </div>
              )}
              {event.bills.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {event.bills.map((bill) => (
                    <button
                      key={bill.id}
                      type="button"
                      onClick={() => onOpenBill(bill.id)}
                      className="rounded-lg bg-white/5 px-2.5 py-1.5 text-xs text-gold hover:bg-white/10"
                    >{bill.name} · #{bill.id} →</button>
                  ))}
                </div>
              )}
            </div>
          ))}
          {events.length > limit && (
            <button
              type="button"
              onClick={() => setLimit((current) => current + 50)}
              className="w-full rounded-xl bg-spotify-gray py-3 text-sm text-white hover:bg-white/10"
            >Показать ещё</button>
          )}
        </div>
      )}
      <p className="mt-4 text-xs text-spotify-text/70">
        Начисления показаны по текущему составу сохранённых счетов. Учитываются только подтверждённые платежи. Отрицательный остаток означает переплату.
      </p>
    </div>
  )
}
