import { useState, useEffect, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { api } from '../../api/client'
import { useToast } from '../../context/useToast'

const TIMESERIES_PERIODS = [
  { key: 'day', label: 'Сутки' },
  { key: '3d', label: '3 дня' },
  { key: 'week', label: 'Неделя' },
  { key: 'month', label: 'Месяц' },
  { key: 'quarter', label: '3 месяца' },
]

const METRICS = [
  { key: 'messages', label: '💬 Сообщения' },
  { key: 'reactions', label: '❤️ Реакции' },
  { key: 'videos', label: '🎬 Видосики' },
  { key: 'curses', label: '🤬 Мат' },
]

const LINE_COLORS = [
  '#1DB954',
  '#3b82f6',
  '#f43f5e',
  '#a855f7',
  '#f59e0b',
  '#22d3ee',
  '#e879f9',
  '#84cc16',
]

function formatBucketTs(ts, period, stepSeconds) {
  const d = new Date(ts * 1000)
  if (period === 'day') {
    return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  }
  const date = d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
  if (stepSeconds < 86400) {
    const time = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
    return `${date} ${time}`
  }
  return date
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const visible = payload.filter(p => p.value !== undefined && p.value !== null)
  if (!visible.length) return null
  const sorted = [...visible].sort((a, b) => (b.value || 0) - (a.value || 0))
  return (
    <div className="bg-spotify-gray rounded-lg px-3 py-2 shadow-lg border border-white/10 max-w-[220px]">
      <p className="text-white text-xs font-medium mb-1">{label}</p>
      {sorted.map(p => (
        <div key={p.dataKey} className="flex items-center gap-2 text-xs">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: p.color }} />
          <span className="text-spotify-text truncate flex-1">@{p.dataKey}</span>
          <span className="text-white font-medium shrink-0">{p.value || 0}</span>
        </div>
      ))}
    </div>
  )
}

export default function MessagesTimeseries({ scope, chatId }) {
  const toast = useToast()
  const [period, setPeriod] = useState('day')
  const [metric, setMetric] = useState('messages')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [hiddenUsers, setHiddenUsers] = useState(() => new Set())

  useEffect(() => {
    if (scope === 'chat' && !chatId) return
    let cancelled = false
    setLoading(true)
    const params = new URLSearchParams({
      period,
      scope,
      metric,
      top: '8',
    })
    if (scope === 'chat') params.set('chat_id', chatId)
    api.get(`/api/messages-timeseries?${params}`)
      .then(d => {
        if (cancelled) return
        setData(d)
        setHiddenUsers(new Set())
      })
      .catch(e => {
        if (cancelled) return
        toast.error(`Не удалось загрузить динамику: ${e.message}`)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [period, scope, chatId, metric, toast])

  const chartData = useMemo(() => {
    if (!data?.buckets?.length || !data?.series?.length) return []
    return data.buckets.map((ts, i) => {
      const row = { label: formatBucketTs(ts, data.period, data.step_seconds) }
      data.series.forEach(s => {
        row[s.user_name] = s.values[i] || 0
      })
      return row
    })
  }, [data])

  const toggleUser = (name) => {
    setHiddenUsers(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const hasData = !loading && chartData.length > 0 && (data?.series?.length || 0) > 0

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-spotify-dark rounded-xl p-4"
    >
      <h3 className="text-white font-semibold text-sm mb-3">📈 Динамика по времени</h3>

      <div className="flex gap-1 mb-2 bg-spotify-black/50 rounded-lg p-0.5 overflow-x-auto">
        {TIMESERIES_PERIODS.map(p => (
          <motion.button
            key={p.key}
            whileTap={{ scale: 0.93 }}
            onClick={() => setPeriod(p.key)}
            className={`px-2.5 py-1 rounded-md text-[10px] font-medium transition-colors whitespace-nowrap shrink-0 ${
              period === p.key
                ? 'bg-spotify-green text-black'
                : 'text-spotify-text hover:text-white'
            }`}
          >
            {p.label}
          </motion.button>
        ))}
      </div>

      <div className="flex gap-1 mb-3 bg-spotify-black/50 rounded-lg p-0.5 overflow-x-auto">
        {METRICS.map(m => (
          <motion.button
            key={m.key}
            whileTap={{ scale: 0.93 }}
            onClick={() => setMetric(m.key)}
            className={`px-2.5 py-1 rounded-md text-[10px] font-medium transition-colors whitespace-nowrap shrink-0 ${
              metric === m.key
                ? 'bg-white text-black'
                : 'text-spotify-text hover:text-white'
            }`}
          >
            {m.label}
          </motion.button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        {loading ? (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex items-center justify-center h-56"
          >
            <div className="w-6 h-6 border-2 border-spotify-green border-t-transparent rounded-full animate-spin" />
          </motion.div>
        ) : !hasData ? (
          <motion.div
            key="empty"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center justify-center h-56 text-spotify-text text-sm gap-2"
          >
            <span className="text-3xl">📊</span>
            <span>Нет данных за этот период</span>
          </motion.div>
        ) : (
          <motion.div
            key={`${period}-${metric}`}
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.98 }}
            transition={{ duration: 0.25 }}
          >
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 5, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#282828" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fill: '#b3b3b3', fontSize: 9 }}
                    tickLine={false}
                    axisLine={false}
                    interval="preserveStartEnd"
                    minTickGap={28}
                  />
                  <YAxis
                    tick={{ fill: '#b3b3b3', fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    allowDecimals={false}
                    width={36}
                  />
                  <Tooltip
                    content={<CustomTooltip />}
                    cursor={{ stroke: '#1DB954', strokeOpacity: 0.3 }}
                  />
                  {data.series.map((s, i) => {
                    if (hiddenUsers.has(s.user_name)) return null
                    const color = LINE_COLORS[i % LINE_COLORS.length]
                    return (
                      <Line
                        key={s.user_name}
                        type="linear"
                        dataKey={s.user_name}
                        stroke={color}
                        strokeWidth={2}
                        dot={false}
                        activeDot={{ r: 4, fill: color }}
                        animationDuration={500}
                        isAnimationActive
                      />
                    )
                  })}
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="flex flex-wrap gap-1.5 mt-3">
              {data.series.map((s, i) => {
                const color = LINE_COLORS[i % LINE_COLORS.length]
                const hidden = hiddenUsers.has(s.user_name)
                return (
                  <motion.button
                    key={s.user_name}
                    whileTap={{ scale: 0.9 }}
                    onClick={() => toggleUser(s.user_name)}
                    className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] bg-spotify-black/40 hover:bg-spotify-black/70 transition-opacity ${
                      hidden ? 'opacity-40' : 'opacity-100'
                    }`}
                  >
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ background: hidden ? '#666' : color }}
                    />
                    <span className="text-white">@{s.user_name}</span>
                    <span className="text-spotify-text">{s.total}</span>
                  </motion.button>
                )
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
