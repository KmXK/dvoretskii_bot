import { useState } from 'react'
import { Loader2, Share2 } from 'lucide-react'
import WebApp from '@twa-dev/sdk'
import { api } from '../../api/client'

export default function ShareBillButton({ billId, beforeShare, className = '' }) {
  const [sharing, setSharing] = useState(false)

  const share = async () => {
    if (!WebApp.isVersionAtLeast?.('8.0') || typeof WebApp.shareMessage !== 'function') {
      alert('Обновите Telegram — нужен шеринг сообщений (8.0+)')
      return
    }

    setSharing(true)
    try {
      await beforeShare?.()
      const { prepared_message_id: preparedMessageId } = await api.post(`/api/bills/${billId}/share-image`, {})
      WebApp.shareMessage(preparedMessageId)
    } catch (error) {
      alert(error.message || 'Не удалось подготовить счёт')
    } finally {
      setSharing(false)
    }
  }

  return (
    <button
      type="button"
      onClick={share}
      disabled={sharing}
      className={`w-full rounded-xl bg-gold/15 border border-gold/30 text-gold py-3 font-medium inline-flex items-center justify-center gap-2 hover:bg-gold/25 disabled:opacity-50 transition ${className}`}
    >
      {sharing ? <Loader2 size={16} className="animate-spin" /> : <Share2 size={16} />}
      {sharing ? 'Готовим счёт…' : 'Поделиться счётом'}
    </button>
  )
}
