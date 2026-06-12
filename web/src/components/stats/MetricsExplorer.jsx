import { useState, useEffect, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { api } from '../../api/client'
import { useToast } from '../../context/useToast'

const MODES = [
  { key: 'metric', label: 'По метрикам' },
  { key: 'chat', label: 'По чатам' },
  { key: 'user', label: 'По людям' },
]

const PERIODS = [
  { key: 'day', label: 'Сутки' },
  { key: '3d', label: '3 дня' },
  { key: 'week', label: 'Неделя' },
  { key: 'month', label: 'Месяц' },
  { key: 'quarter', label: '3 мес' },
  { key: 'year', label: 'Год' },
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
  '#fb7185',
  '#38bdf8',
]

const spring = { type: 'spring', stiffness: 500, damping: 35 }

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

function formatNum(v) {
  if (v >= 10000) return `${Math.round(v / 100) / 10}k`
  return Math.round(v * 10) / 10
}

function ExplorerTooltip({ active, payload, label, seriesByKey }) {
  if (!active || !payload?.length) return null
  const visible = payload.filter(p => p.value !== undefined && p.value !== null)
  if (!visible.length) return null
  const sorted = [...visible].sort((a, b) => (b.value || 0) - (a.value || 0))
  return (
    <div className="bg-spotify-gray rounded-lg px-3 py-2 shadow-lg border border-white/10 max-w-[230px]">
      <p className="text-white text-xs font-medium mb-1">{label}</p>
      {sorted.map(p => {
        const s = seriesByKey[p.dataKey]
        return (
          <div key={p.dataKey} className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: p.stroke }} />
            <span className="text-spotify-text truncate flex-1">
              {s ? `${s.emoji} ${s.label}` : p.dataKey}
            </span>
            <span className="text-white font-medium shrink-0">{formatNum(p.value || 0)}</span>
          </div>
        )
      })}
    </div>
  )
}

function ChartSkeleton() {
  return (
    <div className="h-60 flex items-end gap-1.5 px-2 pb-6">
      {Array.from({ length: 16 }).map((_, i) => (
        <motion.div
          key={i}
          className="flex-1 rounded-t bg-spotify-gray/60"
          initial={{ height: 8 }}
          animate={{ height: [12, 24 + ((i * 37) % 90), 12] }}
          transition={{ duration: 1.4, repeat: Infinity, delay: i * 0.07, ease: 'easeInOut' }}
        />
      ))}
    </div>
  )
}

export default function MetricsExplorer() {
  const toast = useToast()
  const [catalog, setCatalog] = useState(null)
  const [selected, setSelected] = useState([])
  const [mode, setMode] = useState('metric')
  const [period, setPeriod] = useState('week')
  const [cumulative, setCumulative] = useState(false)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [hidden, setHidden] = useState(() => new Set())

  useEffect(() => {
    let cancelled = false
    api.get('/api/metrics/catalog')
      .then(d => {
        if (cancelled) return
        const list = d.metrics || []
        setCatalog(list)
        setSelected(list.slice(0, 3).map(m => m.name))
      })
      .catch(() => {
        if (!cancelled) setCatalog([])
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!selected.length) return
    let cancelled = false
    setLoading(true)
    const params = new URLSearchParams({
      metrics: selected.join(','),
      mode,
      period,
    })
    api.get(`/api/metrics/range?${params}`)
      .then(d => {
        if (cancelled) return
        setData(d)
        setHidden(new Set())
      })
      .catch(e => {
        if (cancelled) return
        toast.error(`Не удалось загрузить метрики: ${e.message}`)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [selected, mode, period, toast])

  const metricByName = useMemo(
    () => Object.fromEntries((catalog || []).map(m => [m.name, m])),
    [catalog],
  )

  const seriesByKey = useMemo(
    () => Object.fromEntries((data?.series || []).map(s => [s.key, s])),
    [data],
  )

  const chartData = useMemo(() => {
    if (!data?.buckets?.length || !data?.series?.length) return []
    const running = {}
    return data.buckets.map((ts, i) => {
      const row = { label: formatBucketTs(ts, data.period, data.step_seconds) }
      data.series.forEach(s => {
        const v = s.values[i] || 0
        if (cumulative) {
          running[s.key] = (running[s.key] || 0) + v
          row[s.key] = Math.round(running[s.key] * 10) / 10
        } else {
          row[s.key] = v
        }
      })
      return row
    })
  }, [data, cumulative])

  const toggleMetric = (name) => {
    if (mode === 'metric') {
      setSelected(prev => {
        if (prev.includes(name)) {
          return prev.length > 1 ? prev.filter(n => n !== name) : prev
        }
        return [...prev, name]
      })
    } else {
      setSelected([name])
    }
  }

  const switchMode = (key) => {
    setMode(key)
    if (key !== 'metric' && selected.length > 1) setSelected([selected[0]])
  }

  const toggleSeries = (key) => {
    setHidden(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const visibleSeries = (data?.series || []).filter(s => !hidden.has(s.key))
  const grandTotal = visibleSeries.reduce((acc, s) => acc + (s.total || 0), 0)
  const hasData = !loading && chartData.length > 0 && visibleSeries.length > 0
  const activeMetricChips = mode === 'metric' ? selected : selected.slice(0, 1)

  if (catalog !== null && catalog.length === 0) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-spotify-dark rounded-xl p-4 mb-3 relative overflow-hidden"
    >
      <div
        className="absolute -top-20 -right-20 w-56 h-56 rounded-full pointer-events-none"
        style={{ background: 'radial-gradient(circle, rgba(29,185,84,0.12) 0%, transparent 70%)' }}
      />

      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-white font-semibold text-sm">📈 Метрики</h3>
          <p className="text-spotify-text text-[10px] mt-0.5">
            {cumulative ? 'накопительный рост' : 'прирост за интервал'}
          </p>
        </div>
        <AnimatePresence mode="popLayout">
          <motion.div
            key={`${grandTotal}-${period}-${mode}`}
            initial={{ scale: 0.6, opacity: 0, y: 6 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 400, damping: 20 }}
            className="text-right"
          >
            <span className="text-spotify-green text-xl font-bold leading-none">
              {formatNum(grandTotal)}
            </span>
            <span className="text-spotify-text text-[10px] block">за период</span>
          </motion.div>
        </AnimatePresence>
      </div>

      <div className="relative flex bg-spotify-black/50 rounded-lg p-0.5 mb-2">
        {MODES.map(m => (
          <button
            key={m.key}
            onClick={() => switchMode(m.key)}
            className="relative flex-1 py-1.5 text-[10px] font-medium"
          >
            {mode === m.key && (
              <motion.div
                layoutId="mx-mode-pill"
                className="absolute inset-0 bg-spotify-green rounded-md"
                transition={spring}
              />
            )}
            <span className={`relative z-10 transition-colors ${
              mode === m.key ? 'text-black font-semibold' : 'text-spotify-text'
            }`}>
              {m.label}
            </span>
          </button>
        ))}
      </div>

      <div className="flex gap-1 mb-2 bg-spotify-black/50 rounded-lg p-0.5 overflow-x-auto">
        {PERIODS.map(p => (
          <motion.button
            key={p.key}
            whileTap={{ scale: 0.93 }}
            onClick={() => setPeriod(p.key)}
            className={`px-2.5 py-1 rounded-md text-[10px] font-medium transition-colors whitespace-nowrap shrink-0 flex-1 ${
              period === p.key ? 'bg-spotify-green/80 text-black' : 'text-spotify-text hover:text-white'
            }`}
          >
            {p.label}
          </motion.button>
        ))}
      </div>

      <div className="flex gap-1.5 mb-2 overflow-x-auto pb-0.5">
        {(catalog || []).map(m => {
          const active = activeMetricChips.includes(m.name)
          return (
            <motion.button
              key={m.name}
              layout
              whileTap={{ scale: 0.9 }}
              onClick={() => toggleMetric(m.name)}
              transition={spring}
              className={`flex items-center gap-1 px-2.5 py-1.5 rounded-full text-[10px] font-medium whitespace-nowrap shrink-0 border transition-colors ${
                active
                  ? 'bg-spotify-green/15 border-spotify-green/60 text-white'
                  : 'bg-spotify-black/40 border-transparent text-spotify-text hover:text-white'
              }`}
            >
              <span>{m.emoji}</span>
              <span>{m.label}</span>
              <AnimatePresence>
                {active && mode === 'metric' && (
                  <motion.span
                    initial={{ scale: 0, width: 0 }}
                    animate={{ scale: 1, width: 'auto' }}
                    exit={{ scale: 0, width: 0 }}
                    transition={spring}
                    className="text-spotify-green"
                  >
                    ✓
                  </motion.span>
                )}
              </AnimatePresence>
            </motion.button>
          )
        })}
      </div>

      <div className="flex items-center justify-between mb-3">
        <button
          onClick={() => setCumulative(v => !v)}
          className="flex items-center gap-2"
        >
          <div className={`w-9 h-5 rounded-full p-0.5 transition-colors duration-300 ${
            cumulative ? 'bg-spotify-green' : 'bg-spotify-black/60'
          }`}>
            <motion.div
              className="w-4 h-4 bg-white rounded-full shadow"
              animate={{ x: cumulative ? 16 : 0 }}
              transition={spring}
            />
          </div>
          <span className={`text-[10px] font-medium transition-colors ${
            cumulative ? 'text-white' : 'text-spotify-text'
          }`}>
            Накопительно
          </span>
        </button>
        {loading && data && (
          <div className="w-3.5 h-3.5 border-2 border-spotify-green border-t-transparent rounded-full animate-spin" />
        )}
      </div>

      <AnimatePresence mode="wait">
        {loading && !data ? (
          <motion.div key="skeleton" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <ChartSkeleton />
          </motion.div>
        ) : !hasData ? (
          <motion.div
            key="empty"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center justify-center h-60 text-spotify-text text-sm gap-2"
          >
            <motion.span
              className="text-3xl"
              animate={{ rotate: [0, -8, 8, 0] }}
              transition={{ duration: 2, repeat: Infinity, repeatDelay: 1.5 }}
            >
              📊
            </motion.span>
            <span>Нет данных за этот период</span>
          </motion.div>
        ) : (
          <motion.div
            key={`${mode}-${period}-${cumulative}-${selected.join()}`}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.25 }}
          >
            <div className="h-60">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 5, right: 8, bottom: 0, left: 0 }}>
                  <defs>
                    {data.series.map((s, i) => (
                      <linearGradient key={s.key} id={`mx-grad-${i}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={LINE_COLORS[i % LINE_COLORS.length]} stopOpacity={0.28} />
                        <stop offset="100%" stopColor={LINE_COLORS[i % LINE_COLORS.length]} stopOpacity={0} />
                      </linearGradient>
                    ))}
                  </defs>
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
                    tickFormatter={formatNum}
                    width={36}
                  />
                  <Tooltip
                    content={<ExplorerTooltip seriesByKey={seriesByKey} />}
                    cursor={{ stroke: '#1DB954', strokeOpacity: 0.3 }}
                  />
                  {data.series.map((s, i) => {
                    if (hidden.has(s.key)) return null
                    const color = LINE_COLORS[i % LINE_COLORS.length]
                    return (
                      <Area
                        key={s.key}
                        type="monotone"
                        dataKey={s.key}
                        stroke={color}
                        strokeWidth={s.is_me ? 3.5 : 2.5}
                        fill={`url(#mx-grad-${i})`}
                        dot={false}
                        activeDot={{ r: 4, fill: color, strokeWidth: 0 }}
                        animationDuration={600}
                        animationEasing="ease-out"
                        isAnimationActive
                      />
                    )
                  })}
                </AreaChart>
              </ResponsiveContainer>
            </div>

            <div className="flex flex-wrap gap-1.5 mt-3">
              {data.series.map((s, i) => {
                const color = LINE_COLORS[i % LINE_COLORS.length]
                const isHidden = hidden.has(s.key)
                const meta = mode === 'metric' ? metricByName[s.key] : null
                return (
                  <motion.button
                    key={s.key}
                    layout
                    whileTap={{ scale: 0.9 }}
                    onClick={() => toggleSeries(s.key)}
                    transition={spring}
                    className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] bg-spotify-black/40 hover:bg-spotify-black/70 transition-opacity ${
                      isHidden ? 'opacity-40' : 'opacity-100'
                    } ${s.is_me ? 'ring-1 ring-spotify-green/60' : ''}`}
                  >
                    <span
                      className="w-2 h-2 rounded-full transition-colors"
                      style={{ background: isHidden ? '#666' : color }}
                    />
                    <span className="text-white">
                      {s.is_me ? '⭐ ' : ''}{(meta?.emoji || s.emoji) ?? ''} {meta?.label || s.label}
                    </span>
                    <span className="text-spotify-text">{formatNum(s.total)}</span>
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
