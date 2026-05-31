import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import WebApp from '@twa-dev/sdk'
import { watchApi } from './api'
import { useToast } from '../context/useToast'

// Глобальный перехват QR-привязки часов. Часы показывают QR с deep-link
// `…?startapp=wp_<pairId>`; после скана телефоном вебаппа стартует с этим
// start_param — спрашиваем подтверждение и зовём approve.
export default function WatchApproveGate() {
  const toast = useToast()
  const [pairId, setPairId] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const raw = WebApp?.initDataUnsafe?.start_param || ''
    const m = /^wp_(.+)$/.exec(raw)
    if (m) setPairId(m[1])
  }, [])

  const confirm = async () => {
    setBusy(true)
    try {
      const r = await watchApi.approve(pairId)
      toast.success('⌚ Часы привязаны!')
      void r
    } catch (e) {
      let msg = e.message || 'Ошибка'
      try { const p = JSON.parse(msg); if (p?.error) msg = p.error } catch { /* */ }
      toast.error(`Не удалось привязать: ${msg}`)
    } finally {
      setBusy(false)
      setPairId(null)
    }
  }

  return (
    <AnimatePresence>
      {pairId && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[70] bg-black/70 backdrop-blur-sm flex items-center justify-center px-4"
          onClick={() => !busy && setPairId(null)}
        >
          <motion.div
            initial={{ y: 24, scale: 0.96, opacity: 0 }}
            animate={{ y: 0, scale: 1, opacity: 1 }}
            exit={{ scale: 0.96, opacity: 0 }}
            transition={{ type: 'spring', damping: 24, stiffness: 320 }}
            className="bg-zinc-900 border border-indigo-800/60 rounded-2xl shadow-2xl w-full max-w-sm p-6 text-center"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-5xl mb-3">⌚</div>
            <h2 className="text-white font-bold text-lg mb-1">Привязать часы?</h2>
            <p className="text-zinc-400 text-sm mb-5">
              Часы получат доступ к ведению счёта в твоих сессиях. Подтверди, что
              это твои часы.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setPairId(null)}
                disabled={busy}
                className="flex-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 py-3 rounded-xl font-medium disabled:opacity-50"
              >
                Отмена
              </button>
              <motion.button
                whileTap={{ scale: 0.96 }}
                onClick={confirm}
                disabled={busy}
                className="flex-1 bg-gradient-to-br from-indigo-600 to-indigo-800 text-white py-3 rounded-xl font-semibold disabled:opacity-50"
              >
                {busy ? 'Привязываем…' : 'Привязать'}
              </motion.button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
