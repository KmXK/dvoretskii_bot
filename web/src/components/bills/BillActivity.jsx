import { useEffect, useState } from 'react'

import { api } from '../../api/client'
import Loader from '../Loader'


const FIELD_LABELS = {
  item_name: 'Название',
  unit_price_minor: 'Цена за штуку',
  quantity: 'Количество',
  creditor: 'Кто оплатил',
  assignments: 'Кто взял',
  name: 'Название счёта',
  currency: 'Валюта',
  participants: 'Участники',
  closed: 'Счёт',
  distribution_status: 'Распределение',
}

const STATUS_LABELS = { draft: 'Собирается', distributing: 'Распределяется', final: 'Итоговое' }


function changeTitle(change) {
  const name = change.after?.item_name || change.before?.item_name || 'Позиция'
  if (change.kind === 'item_added') {
    return `Добавлено: ${name}`
  }

  if (change.kind === 'item_removed') {
    return `Удалено: ${name}`
  }

  if (change.kind === 'item_updated') {
    return `Изменено: ${name}`
  }

  if (change.kind === 'created') {
    return 'Счёт создан'
  }

  if (change.kind === 'deleted') {
    return 'Счёт удалён'
  }

  return 'Изменён счёт'
}


function fieldValue(field, value, currency, personsById, formatMinor) {
  const personName = (id) => personsById[id]?.display_name || 'Не указан'
  if (field === 'unit_price_minor') {
    return formatMinor(value || 0, currency)
  }

  if (field === 'creditor') {
    return personName(value)
  }

  if (field === 'closed') {
    return value ? 'Закрыт' : 'Открыт'
  }

  if (field === 'distribution_status') {
    return STATUS_LABELS[value] || value
  }

  if (field === 'participants') {
    return (value || []).map(personName).join(', ') || 'Нет'
  }

  if (field === 'assignments') {
    return (value || []).map((assignment) => {
      const quantity = assignment.denominator > 1 ? `${assignment.unit_count}/${assignment.denominator}` : assignment.unit_count
      const names = assignment.debtors.map(personName).join(', ') || 'Не распределено'
      return `${quantity} шт. → ${names}${assignment.debtors.length > 1 ? ' (поровну)' : ''}`
    }).join('; ') || 'Не распределено'
  }

  return String(value ?? '—')
}


function ActivityChange({ change, currency, personsById, formatMinor }) {
  const item = change.after || change.before
  const isItem = change.kind.startsWith('item_')
  return (
    <div className="rounded-xl bg-black/15 p-3">
      <div className={`text-sm font-medium ${change.kind === 'item_removed' ? 'text-red-300' : 'text-white'}`}>
        {changeTitle(change)}
      </div>
      {isItem && item && (
        <div className="mt-1 text-sm text-gold tabular-nums">
          {item.quantity} × {formatMinor(item.unit_price_minor, currency)} = {formatMinor(item.quantity * item.unit_price_minor, currency)}
        </div>
      )}
      {change.fields.length > 0 && (
        <div className="mt-2 space-y-2 text-sm">
          {change.fields.map((field) => (
            <div key={field}>
              <div className="text-xs text-spotify-text">{FIELD_LABELS[field] || field}</div>
              <div className="mt-0.5 break-words text-white">
                <span className="text-spotify-text">{fieldValue(field, change.before?.[field], currency, personsById, formatMinor)}</span>
                {' → '}{fieldValue(field, change.after?.[field], currency, personsById, formatMinor)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


export default function BillActivity({ billId, personsById, formatMinor, formatDateTime }) {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [hasMore, setHasMore] = useState(false)

  useEffect(() => {
    let active = true
    api.get(`/api/bills/${billId}/activity`)
      .then((data) => {
        if (active) {
          setEvents(data.events || [])
          setHasMore(data.has_more)
        }
      })
      .catch((requestError) => { if (active) setError(requestError.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [billId])

  const loadMore = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get(`/api/bills/${billId}/activity?offset=${events.length}`)
      setEvents((current) => [...current, ...(data.events || [])])
      setHasMore(data.has_more)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-spotify-text">Добавление, правки и удаление позиций сохраняются здесь. Изменения до появления журнала могут отсутствовать.</p>
      {error && <p className="text-sm text-red-400">{error}</p>}
      {loading && events.length === 0 ? (
        <div className="flex justify-center py-8"><Loader scale={0.6} /></div>
      ) : events.length === 0 ? (
        <div className="rounded-xl bg-spotify-dark p-5 text-center text-sm text-spotify-text">Изменений пока нет</div>
      ) : events.map((event) => (
        <div key={event.id} className="rounded-xl bg-spotify-dark p-4">
          <div className="mb-3 flex flex-wrap justify-between gap-1 text-xs text-spotify-text">
            <span>{formatDateTime(event.date)}</span>
            <span>{event.actor || 'Автор не указан'}</span>
          </div>
          <div className="space-y-2">
            {event.changes.map((change, index) => (
              <ActivityChange key={index} change={change} currency={event.currency} personsById={personsById} formatMinor={formatMinor} />
            ))}
          </div>
        </div>
      ))}
      {hasMore && (
        <button type="button" onClick={loadMore} disabled={loading} className="min-h-11 w-full rounded-xl bg-spotify-gray px-4 py-3 text-sm text-white disabled:opacity-50">
          {loading ? 'Загружаем…' : 'Показать ещё'}
        </button>
      )}
    </div>
  )
}
