import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import BackButton from '../components/BackButton'
import { useAuth } from '../context/useAuth'
import { api } from '../api/client'

export default function GrafanaPage() {
  const { userId } = useAuth()
  const [src, setSrc] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [frameReady, setFrameReady] = useState(false)

  const fetchToken = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await api.get('/api/grafana/token')
      setSrc(`${d.url}/?auth_token=${encodeURIComponent(d.token)}&theme=dark`)
    } catch (e) {
      if (e.status === 403) setError('Grafana доступна только участникам чатов бота')
      else if (e.status === 503) setError('Grafana не настроена на сервере (нужен metrics-профиль)')
      else setError(`Не удалось получить доступ: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (userId) fetchToken()
  }, [userId, fetchToken])

  if (!userId) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] px-4">
        <div className="bg-spotify-dark rounded-2xl p-6 text-center max-w-sm">
          <span className="text-4xl block mb-3">🔒</span>
          <h2 className="text-white font-semibold text-lg mb-2">Нет доступа</h2>
          <p className="text-spotify-text text-sm">Откройте приложение через Telegram</p>
        </div>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6 pb-4 max-w-5xl mx-auto"
    >
      <BackButton />
      <h1 className="text-2xl font-bold text-white mb-1">Grafana</h1>
      <p className="text-spotify-text text-sm mb-4">Все метрики бота, без купюр</p>

      <AnimatePresence mode="wait">
        {loading && (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex items-center justify-center h-[60vh]"
          >
            <div className="w-8 h-8 border-2 border-spotify-green border-t-transparent rounded-full animate-spin" />
          </motion.div>
        )}

        {!loading && error && (
          <motion.div
            key="error"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="bg-spotify-dark rounded-2xl p-6 text-center"
          >
            <span className="text-4xl block mb-3">📵</span>
            <p className="text-white text-sm mb-4">{error}</p>
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={fetchToken}
              className="bg-spotify-green text-black text-sm font-medium px-4 py-2 rounded-full"
            >
              Попробовать ещё раз
            </motion.button>
          </motion.div>
        )}

        {!loading && !error && src && (
          <motion.div
            key="frame"
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            className="relative rounded-2xl overflow-hidden bg-spotify-dark"
            style={{ height: 'calc(100vh - 180px)' }}
          >
            {!frameReady && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-8 h-8 border-2 border-spotify-green border-t-transparent rounded-full animate-spin" />
              </div>
            )}
            <iframe
              src={src}
              title="Grafana"
              className={`w-full h-full border-0 transition-opacity duration-500 ${
                frameReady ? 'opacity-100' : 'opacity-0'
              }`}
              onLoad={() => setFrameReady(true)}
              allow="fullscreen"
            />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
