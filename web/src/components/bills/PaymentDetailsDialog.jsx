import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { CreditCard, Loader2, Save, X } from 'lucide-react'

import { api } from '../../api/client'
import { useToast } from '../../context/useToast'


export default function PaymentDetailsDialog({ open, onClose, onSaved }) {
  const toast = useToast()
  const [value, setValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) return

    let active = true
    setLoading(true)
    setError(null)
    api.get('/api/bills/payment-details')
      .then((payload) => {
        if (active) setValue(payload.payment_details || '')
      })
      .catch((requestError) => {
        if (active) setError(requestError.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [open])

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.put('/api/bills/payment-details', { payment_details: value })
      if (onSaved) await Promise.resolve(onSaved()).catch(() => {})
      toast.success(value.trim() ? 'Реквизиты сохранены' : 'Реквизиты удалены')
      onClose()
    } catch (requestError) {
      setError(requestError.message || 'Не получилось сохранить реквизиты')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={(nextOpen) => { if (!nextOpen && !busy) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-white/5 bg-spotify-dark p-5 shadow-xl">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <Dialog.Title className="flex items-center gap-2 text-xl font-bold tracking-tight text-white">
                <CreditCard size={20} className="text-gold" /> Реквизиты
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-spotify-text">
                Их увидят только люди, которые собираются погасить долг тебе.
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

          {loading ? (
            <div className="flex min-h-32 items-center justify-center text-spotify-text">
              <Loader2 size={20} className="animate-spin" />
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <label className="block">
                <span className="mb-1.5 block text-xs font-bold uppercase tracking-[0.08em] text-spotify-text">
                  Куда переводить
                </span>
                <textarea
                  autoFocus
                  maxLength={2000}
                  rows={6}
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                  placeholder="Телефон, номер карты, банк или ссылка для перевода"
                  className="w-full resize-none rounded-xl border border-white/5 bg-spotify-gray px-3 py-3 text-sm text-white outline-none transition-colors placeholder:text-spotify-text/60 focus:border-gold/60"
                />
              </label>
              <div className="flex items-center justify-between text-[11px] text-spotify-text/70">
                <span>Можно оставить поле пустым, чтобы удалить реквизиты.</span>
                <span className="tabular-nums">{value.length}/2000</span>
              </div>
              {error && <div role="alert" className="text-sm text-red-400">{error}</div>}
              <button
                type="submit"
                disabled={busy}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gold py-3 font-semibold text-black transition-colors hover:bg-gold-2 disabled:opacity-50"
              >
                {busy ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                Сохранить
              </button>
            </form>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
