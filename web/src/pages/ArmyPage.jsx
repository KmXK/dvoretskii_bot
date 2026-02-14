import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import BackButton from '../components/BackButton'

function formatRemaining(seconds) {
  if (seconds <= 0) return null
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  if (days > 0) return `${days} д ${hours} ч`
  const minutes = Math.floor((seconds % 3600) / 60)
  return `${hours} ч ${minutes} мин`
}

function formatDate(timestamp) {
  if (!timestamp) return ''
  return new Date(timestamp * 1000).toLocaleDateString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
  })
}

function ProgressBar({ percent }) {
  const pct = Math.min(100, Math.max(0, percent * 100))
  const color = pct >= 100
    ? 'bg-spotify-green'
    : pct >= 75
      ? 'bg-emerald-400'
      : pct >= 50
        ? 'bg-yellow-400'
        : pct >= 25
          ? 'bg-orange-400'
          : 'bg-red-400'

  return (
    <div className="w-full h-2 bg-white/10 rounded-full overflow-hidden">
      <motion.div
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.8, ease: 'easeOut' }}
        className={`h-full rounded-full ${color}`}
      />
    </div>
  )
}

function ArmyCard({ person, index }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.08, duration: 0.3 }}
      className="bg-spotify-dark rounded-xl p-4"
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-white font-semibold text-sm">{person.name}</h3>
        {person.done ? (
          <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-spotify-green/20 text-spotify-green">
            Дембель
          </span>
        ) : (
          <span className="text-spotify-text text-xs font-mono">
            {(person.percent * 100).toFixed(1)}%
          </span>
        )}
      </div>

      <ProgressBar percent={person.percent} />

      {!person.done && (
        <p className="text-spotify-text text-xs mt-2.5">
          Осталось {formatRemaining(person.remaining_seconds)}
        </p>
      )}

      <div className="flex items-center justify-between mt-2.5 text-xs text-spotify-text/60">
        <span>{formatDate(person.start_date)}</span>
        <span>{formatDate(person.end_date)}</span>
      </div>
    </motion.div>
  )
}

export default function ArmyPage() {
  const [army, setArmy] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchArmy = useCallback(() => {
    fetch('/api/army')
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(data => { setArmy(data); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [])

  useEffect(() => {
    fetchArmy()
    const interval = setInterval(fetchArmy, 60000)
    return () => clearInterval(interval)
  }, [fetchArmy])

  const active = army.filter(p => !p.done)
  const done = army.filter(p => p.done)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-spotify-green border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="px-4 pt-6">
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400 text-sm">
          Не удалось загрузить данные: {error}
        </div>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6 pb-4"
    >
      <BackButton />
      <h1 className="text-2xl font-bold text-white mb-1">Армейка</h1>
      <p className="text-spotify-text text-sm mb-5">
        {army.length === 0
          ? 'Никого не добавили'
          : `${active.length} служат, ${done.length} на дембеле`}
      </p>

      {army.length === 0 && (
        <div className="text-center py-16">
          <span className="text-5xl block mb-4">🎖️</span>
          <p className="text-spotify-text text-sm">В армейку никого не добавили</p>
        </div>
      )}

      {active.length > 0 && (
        <div className="space-y-3 mb-5">
          <AnimatePresence initial={false}>
            {active.map((person, i) => (
              <ArmyCard key={person.name} person={person} index={i} />
            ))}
          </AnimatePresence>
        </div>
      )}

      {done.length > 0 && (
        <>
          <h2 className="text-white font-semibold text-sm mb-3">Дембеля</h2>
          <div className="space-y-3">
            <AnimatePresence initial={false}>
              {done.map((person, i) => (
                <ArmyCard key={person.name} person={person} index={i} />
              ))}
            </AnimatePresence>
          </div>
        </>
      )}
    </motion.div>
  )
}
