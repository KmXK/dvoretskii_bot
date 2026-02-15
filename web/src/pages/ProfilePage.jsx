import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { useTelegram } from '../context/TelegramContext'

const PERIODS = [
  { key: 'day', label: 'День' },
  { key: 'week', label: 'Неделя' },
  { key: 'month', label: 'Месяц' },
]

const STAT_CARDS = [
  { key: 'messages', label: 'Сообщения', emoji: '💬', color: 'from-blue-500/20 to-blue-900/20', accent: '#3b82f6' },
  { key: 'reactions', label: 'Реакции', emoji: '❤️', color: 'from-rose-500/20 to-rose-900/20', accent: '#f43f5e' },
  { key: 'videos', label: 'Видосики', emoji: '🎬', color: 'from-purple-500/20 to-purple-900/20', accent: '#a855f7' },
]

const CHART_METRICS = [
  { key: 'messages', label: 'Сообщения', color: '#3b82f6' },
  { key: 'reactions', label: 'Реакции', color: '#f43f5e' },
  { key: 'videos', label: 'Видосики', color: '#a855f7' },
]

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-spotify-gray rounded-lg px-3 py-2 shadow-lg border border-white/10">
      <p className="text-white text-xs font-medium mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} className="text-xs" style={{ color: p.color }}>
          {CHART_METRICS.find(m => m.key === p.dataKey)?.label}: {p.value}
        </p>
      ))}
    </div>
  )
}

export default function ProfilePage() {
  const { userId, firstName, lastName, username, photoUrl } = useTelegram()
  const [rewards, setRewards] = useState(null)
  const [stats, setStats] = useState(null)
  const [history, setHistory] = useState(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const [activeChart, setActiveChart] = useState('messages')
  const [period, setPeriod] = useState('day')

  useEffect(() => {
    if (!userId) return
    fetch(`/api/profile/${userId}?period=day`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setRewards(data.rewards) })
      .catch(() => {})
  }, [userId])

  useEffect(() => {
    if (!userId) return
    setStatsLoading(true)
    Promise.all([
      fetch(`/api/profile/${userId}?period=${period}`).then(r => r.ok ? r.json() : null),
      fetch(`/api/profile/${userId}/history?period=${period}`).then(r => r.ok ? r.json() : null),
    ])
      .then(([profileData, historyData]) => {
        if (profileData) setStats(profileData.stats)
        if (historyData) setHistory(historyData)
      })
      .catch(e => console.error('Profile fetch error:', e))
      .finally(() => setStatsLoading(false))
  }, [userId, period])

  const displayName = [firstName, lastName].filter(Boolean).join(' ') || username || 'User'
  const currentStats = stats ?? { messages: 0, reactions: 0, videos: 0 }
  const currentRewards = rewards ?? []
  const activeChartMeta = CHART_METRICS.find(m => m.key === activeChart)

  if (!userId) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] px-4">
        <div className="bg-spotify-dark rounded-2xl p-6 text-center max-w-sm">
          <span className="text-4xl block mb-3">🔒</span>
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
      className="px-4 pt-6 pb-4"
    >
      {/* Header */}
      <div className="flex items-center gap-4 mb-5">
        <div className="w-16 h-16 rounded-full bg-gradient-to-br from-spotify-green to-emerald-700 flex items-center justify-center shrink-0 overflow-hidden">
          {photoUrl ? (
            <img src={photoUrl} alt="" className="w-full h-full object-cover" />
          ) : (
            <span className="text-2xl font-bold text-white">
              {(firstName?.[0] || username?.[0] || '?').toUpperCase()}
            </span>
          )}
        </div>
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-white truncate">{displayName}</h1>
          {username && <p className="text-spotify-text text-sm">@{username}</p>}
        </div>
      </div>

      {/* Rewards */}
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-spotify-dark rounded-xl p-4 mb-5"
      >
        <h2 className="text-white font-semibold text-sm mb-3">Достижения</h2>
        {rewards === null ? (
          <div className="flex gap-2">
            {[0, 1, 2].map(i => (
              <div key={i} className="w-10 h-10 rounded-lg bg-spotify-gray animate-pulse" />
            ))}
          </div>
        ) : currentRewards.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {currentRewards.map((r) => (
              <div
                key={r.id}
                className="group relative bg-spotify-gray hover:bg-spotify-light-gray rounded-lg px-3 py-2
                  transition-colors cursor-default"
                title={`${r.name}${r.description ? ': ' + r.description : ''}`}
              >
                <span className="text-lg">{r.emoji}</span>
                <span className="text-white text-xs ml-1.5 font-medium">{r.name}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-spotify-text text-sm">Пока нет достижений</p>
        )}
      </motion.div>

      {/* Period filter */}
      <div className="flex gap-1 mb-5 bg-spotify-dark rounded-xl p-1">
        {PERIODS.map(p => (
          <button
            key={p.key}
            onClick={() => setPeriod(p.key)}
            className={`flex-1 py-2 rounded-lg text-xs font-medium transition-all ${
              period === p.key
                ? 'bg-spotify-green text-black'
                : 'text-spotify-text hover:text-white'
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-2 mb-6">
        {STAT_CARDS.map((card, i) => (
          <motion.div
            key={card.key}
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 + i * 0.06 }}
            className={`bg-gradient-to-br ${card.color} bg-spotify-gray rounded-xl p-3 text-center`}
          >
            <span className="text-xl">{card.emoji}</span>
            <p className="text-white font-bold text-lg mt-1">
              {statsLoading ? '—' : currentStats[card.key]}
            </p>
            <p className="text-spotify-text text-[10px] mt-0.5">{card.label}</p>
          </motion.div>
        ))}
      </div>

      {/* Chart */}
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        className="bg-spotify-dark rounded-xl p-4"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-white font-semibold text-sm">Активность</h2>
          <div className="flex gap-1">
            {CHART_METRICS.map(m => (
              <button
                key={m.key}
                onClick={() => setActiveChart(m.key)}
                className={`px-2.5 py-1 rounded-full text-[10px] font-medium transition-colors ${
                  activeChart === m.key
                    ? 'text-white'
                    : 'bg-spotify-gray text-spotify-text hover:text-white'
                }`}
                style={activeChart === m.key ? { backgroundColor: m.color + '33', color: m.color } : {}}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        {statsLoading || !history ? (
          <div className="h-[180px] flex items-center justify-center">
            <div className="w-6 h-6 border-2 border-spotify-green border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <AnimatePresence mode="wait">
            <motion.div
              key={activeChart + period}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={history} barCategoryGap={period === 'month' ? '10%' : '20%'}>
                  <XAxis
                    dataKey="label"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: '#B3B3B3', fontSize: period === 'month' ? 8 : 11 }}
                    interval={period === 'month' ? 4 : 0}
                  />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: '#B3B3B3', fontSize: 10 }}
                    width={30}
                    allowDecimals={false}
                  />
                  <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.05)' }} />
                  <Bar dataKey={activeChart} radius={[4, 4, 0, 0]}>
                    {history.map((_, idx) => (
                      <Cell
                        key={idx}
                        fill={idx === history.length - 1 ? activeChartMeta.color : activeChartMeta.color + '66'}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </motion.div>
          </AnimatePresence>
        )}
      </motion.div>
    </motion.div>
  )
}
