import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import BackButton from '../components/BackButton'
import { useTelegram } from '../context/TelegramContext'

const PERIODS = [
  { key: 'day', label: 'Сегодня' },
  { key: 'month', label: 'За месяц' },
  { key: 'alltime', label: 'За всё время' },
]

const SCOPES = [
  { key: 'chat', label: 'Текущий чат' },
  { key: 'all', label: 'Все чаты' },
]

const SECTION_COLORS = {
  '💬': '#3b82f6',
  '❤️': '#f43f5e',
  '🎬': '#a855f7',
  '🐵': '#f59e0b',
}

function getSectionColor(label) {
  for (const [emoji, color] of Object.entries(SECTION_COLORS)) {
    if (label.includes(emoji)) return color
  }
  return '#22c55e'
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="bg-spotify-gray rounded-lg px-3 py-2 shadow-lg border border-white/10">
      <p className="text-white text-xs font-medium">@{d.name}</p>
      <p className="text-spotify-text text-xs">{d.value} {d.emoji || ''}</p>
    </div>
  )
}

function StatsSection({ section, color }) {
  const [expanded, setExpanded] = useState(false)
  const displayItems = expanded ? section.items : section.items.slice(0, 5)

  if (section.items.length === 0) {
    return (
      <div className="bg-spotify-dark rounded-xl p-4">
        <h3 className="text-white font-semibold text-sm mb-2">{section.label}</h3>
        <p className="text-spotify-text text-xs">Нет данных</p>
      </div>
    )
  }

  return (
    <motion.div
      layout
      className="bg-spotify-dark rounded-xl p-4"
    >
      <h3 className="text-white font-semibold text-sm mb-3">{section.label}</h3>

      {section.items.length >= 3 && (
        <div className="h-32 mb-3">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={section.items.slice(0, 10)} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
              <XAxis
                dataKey="name"
                tick={{ fill: '#b3b3b3', fontSize: 9 }}
                tickLine={false}
                axisLine={false}
                tickFormatter={v => v.length > 8 ? v.slice(0, 7) + '…' : v}
              />
              <YAxis hide />
              <Tooltip content={<CustomTooltip />} cursor={false} />
              <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={32}>
                {section.items.slice(0, 10).map((_, i) => (
                  <Cell key={i} fill={color} fillOpacity={1 - i * 0.07} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="space-y-1.5">
        {displayItems.map((item, i) => (
          <div key={item.name} className="flex items-center gap-2">
            <span className="text-spotify-text text-xs w-5 text-right shrink-0">{i + 1}.</span>
            <span className="text-white text-sm flex-1 truncate">@{item.name}</span>
            <span className="text-sm font-medium shrink-0" style={{ color }}>
              {item.value} {item.emoji || ''}
            </span>
          </div>
        ))}
      </div>

      {section.items.length > 5 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-3 text-spotify-text text-xs hover:text-white transition-colors"
        >
          {expanded ? 'Свернуть' : `Показать все (${section.items.length})`}
        </button>
      )}
    </motion.div>
  )
}

export default function StatsPage() {
  const { userId } = useTelegram()
  const [chats, setChats] = useState([])
  const [selectedChat, setSelectedChat] = useState('')
  const [period, setPeriod] = useState('day')
  const [scope, setScope] = useState('chat')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!userId) return
    fetch(`/api/user/${userId}/chats`)
      .then(r => r.ok ? r.json() : { chats: [] })
      .then(d => {
        const ch = d.chats || []
        setChats(ch)
        if (ch.length > 0) setSelectedChat(String(ch[0].id))
      })
      .catch(e => setError(e.message))
  }, [userId])

  const fetchStats = useCallback(async () => {
    if (!selectedChat && scope === 'chat') return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ period, scope, top: '15' })
      if (selectedChat) params.set('chat_id', selectedChat)
      const res = await fetch(`/api/chat-stats?${params}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const d = await res.json()
      setData(d)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [selectedChat, period, scope])

  useEffect(() => {
    if (selectedChat || scope === 'all') fetchStats()
  }, [fetchStats, selectedChat, scope])

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
      <BackButton />
      <h1 className="text-2xl font-bold text-white mb-1">Статистика</h1>
      <p className="text-spotify-text text-sm mb-4">
        {data ? `${data.scope} · ${data.period}` : 'Загрузка...'}
      </p>

      {chats.length > 1 && (
        <div className="flex gap-1 mb-3 bg-spotify-dark rounded-xl p-1 overflow-x-auto">
          {chats.map(c => (
            <button
              key={c.id}
              onClick={() => { setSelectedChat(String(c.id)); setScope('chat') }}
              className={`px-3 py-2 rounded-lg text-xs font-medium transition-all whitespace-nowrap shrink-0 ${
                selectedChat === String(c.id) && scope === 'chat'
                  ? 'bg-spotify-green text-black'
                  : 'text-spotify-text hover:text-white'
              }`}
            >
              {c.name}
            </button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="flex gap-1 bg-spotify-dark rounded-xl p-1">
          {SCOPES.map(s => (
            <button
              key={s.key}
              onClick={() => setScope(s.key)}
              className={`flex-1 py-2 rounded-lg text-[10px] font-medium transition-all ${
                scope === s.key ? 'bg-spotify-green text-black' : 'text-spotify-text hover:text-white'
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="flex gap-1 bg-spotify-dark rounded-xl p-1">
          {PERIODS.map(p => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`flex-1 py-2 rounded-lg text-[10px] font-medium transition-all ${
                period === p.key ? 'bg-spotify-green text-black' : 'text-spotify-text hover:text-white'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 text-red-400 text-sm mb-4">
          {error}
        </div>
      )}

      {loading && !data && (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-spotify-green border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {data && (
        <div className="space-y-3">
          <AnimatePresence>
            {data.sections.map((section, i) => (
              <motion.div
                key={section.label}
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.08 }}
              >
                <StatsSection section={section} color={getSectionColor(section.label)} />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  )
}
