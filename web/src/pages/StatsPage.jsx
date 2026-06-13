import { motion } from 'framer-motion'
import { Lock } from 'lucide-react'
import MetricsExplorer from '../components/stats/MetricsExplorer'
import { useAuth } from '../context/useAuth'

export default function StatsPage() {
  const { userId } = useAuth()

  if (!userId) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] px-4">
        <div className="bg-spotify-dark rounded-2xl p-6 text-center max-w-sm">
          <Lock size={36} className="mx-auto mb-3 text-spotify-text/60" />
          <h2 className="text-white font-semibold text-lg mb-2">Нет данных</h2>
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
      className="px-4 pt-6 pb-4 max-w-3xl mx-auto"
    >
      <h1 className="text-2xl font-bold text-white mb-4">Статистика</h1>
      <MetricsExplorer />
    </motion.div>
  )
}
