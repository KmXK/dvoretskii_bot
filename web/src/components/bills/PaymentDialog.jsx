import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Check, Copy, CreditCard, Loader2, X } from 'lucide-react'

import { api } from '../../api/client'
import { useToast } from '../../context/useToast'


function amountInputValue(amountMinor) {
  return (amountMinor / 100).toFixed(amountMinor % 100 === 0 ? 0 : 2)
}


function parseAmountMinor(value) {
  const normalized = value.trim().replace(',', '.')
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) return null

  const amountMinor = Math.round(Number(normalized) * 100)
  return Number.isSafeInteger(amountMinor) && amountMinor > 0 ? amountMinor : null
}


export default function PaymentDialog({ entry, person, formatMinor, onClose, onChanged }) {
  const toast = useToast()
  const [value, setValue] = useState('')
  const [details, setDetails] = useState('')
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!entry) return

    setValue(amountInputValue(entry.amountMinor))
    setError(null)
    setDetails('')
    if (entry.direction !== 'owe') return

    let active = true
    setDetailsLoading(true)
    api.get(`/api/bills/payment-details/${encodeURIComponent(entry.personId)}`)
      .then((payload) => {
        if (active) setDetails(payload.payment_details || '')
      })
      .catch((requestError) => {
        if (active) setError(requestError.message)
      })
      .finally(() => {
        if (active) setDetailsLoading(false)
      })
    return () => { active = false }
  }, [entry])

  if (!entry) return null

  const amountMinor = parseAmountMinor(value)
  const amountValid = amountMinor !== null
  const excess = amountValid ? Math.max(0, amountMinor - entry.amountMinor) : 0
  const outgoing = entry.direction === 'owe'

  const copyDetails = async () => {
    try {
      await navigator.clipboard.writeText(details)
      toast.success('Реквизиты скопированы')
    } catch {
      toast.error('Не получилось скопировать')
    }
  }

  const submit = async (event) => {
    event.preventDefault()
    if (!amountValid) {
      setError('Укажи сумму больше нуля')
      return
    }

    setBusy(true)
    setError(null)
    try {
      const path = outgoing ? '/api/bills/payments' : '/api/bills/payments/received'
      const targetField = outgoing ? 'creditor' : 'debtor'
      const result = await api.post(path, {
        [targetField]: entry.personId,
        amount_minor: amountMinor,
        currency: entry.currency,
        bill_ids: entry.billIds,
      })
      if (outgoing && !result.auto_confirmed) {
        toast.success('Платёж отправлен на подтверждение')
      } else {
        toast.success(outgoing ? 'Платёж засчитан' : 'Получение засчитано')
      }
      onClose()
      await onChanged()
    } catch (requestError) {
      setError(requestError.message || 'Не получилось сохранить платёж')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open && !busy) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-white/5 bg-spotify-dark p-5 shadow-xl">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <Dialog.Title className="text-xl font-bold tracking-tight text-white">
                {outgoing ? `Оплатить ${person?.display_name || ''}` : `Получено от ${person?.display_name || ''}`}
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-spotify-text">
                Текущий долг: {formatMinor(entry.amountMinor, entry.currency)}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label="Закрыть"
                disabled={busy}
                className="rounded-lg bg-white/5 p-2 text-spotify-text transition-colors hover:bg-white/10 hover:text-white disabled:opacity-50"
              >
                <X size={16} />
              </button>
            </Dialog.Close>
          </div>

          {outgoing && (
            <div className="mb-4 rounded-2xl border border-white/5 bg-spotify-gray p-4">
              <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.08em] text-spotify-text">
                <CreditCard size={16} className="text-gold" />
                Реквизиты
              </div>
              {detailsLoading ? (
                <div className="flex items-center gap-2 text-sm text-spotify-text">
                  <Loader2 size={15} className="animate-spin" /> Загружаю
                </div>
              ) : details ? (
                <div className="space-y-3">
                  <div className="whitespace-pre-wrap break-words text-sm text-white">{details}</div>
                  <button
                    type="button"
                    onClick={copyDetails}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-white/5 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-white/10"
                  >
                    <Copy size={14} /> Скопировать
                  </button>
                </div>
              ) : (
                <div className="text-sm text-spotify-text">
                  Получатель пока не указал реквизиты. Уточни их перед переводом.
                </div>
              )}
            </div>
          )}

          <form onSubmit={submit} className="space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-xs font-bold uppercase tracking-[0.08em] text-spotify-text">
                Сумма
              </span>
              <div className="flex gap-2">
                <input
                  autoFocus={!outgoing}
                  inputMode="decimal"
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                  className="min-w-0 flex-1 rounded-xl border border-white/5 bg-spotify-gray px-3 py-2.5 text-white outline-none transition-colors focus:border-gold/60"
                />
                <button
                  type="button"
                  onClick={() => setValue(amountInputValue(entry.amountMinor))}
                  className="rounded-xl bg-white/5 px-3 text-xs font-medium text-white transition-colors hover:bg-white/10"
                >
                  Весь долг
                </button>
              </div>
            </label>

            {excess > 0 && (
              <div className="rounded-xl bg-gold-soft px-3 py-2 text-xs text-gold">
                Переплата {formatMinor(excess, entry.currency)} останется на балансе и пойдёт в будущие долги.
              </div>
            )}
            {error && <div role="alert" className="text-sm text-red-400">{error}</div>}

            <button
              type="submit"
              disabled={busy}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gold py-3 font-semibold text-black transition-colors hover:bg-gold-2 disabled:opacity-50"
            >
              {busy ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
              {outgoing ? 'Я перевёл' : 'Зачесть получение'}
            </button>
            <div className="text-center text-[11px] text-spotify-text/70">
              {outgoing
                ? 'Получатель получит уведомление и подтвердит перевод.'
                : 'Платёж сразу уменьшит долг и отправит уведомление плательщику.'}
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
