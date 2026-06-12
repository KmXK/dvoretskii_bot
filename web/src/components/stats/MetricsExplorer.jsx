import { useState, useEffect, useMemo, useRef } from 'react'
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

const LIMIT_OPTIONS = [5, 10, 20]

const RANK_OPTIONS = [
  { key: 'max', label: 'макс' },
  { key: 'avg', label: 'сред' },
  { key: 'min', label: 'мин' },
]

const MAX_SELECTED = 8

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
  '#facc15',
  '#4ade80',
  '#c084fc',
  '#fb923c',
  '#2dd4bf',
  '#f472b6',
  '#a3e635',
  '#60a5fa',
  '#fbbf24',
  '#34d399',
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

function pluralMetrics(n) {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'метрика'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'метрики'
  return 'метрик'
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

function MetricMultiSelect({ catalog, selected, onToggle }) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    if (open) {
      setSearch('')
      const t = setTimeout(() => inputRef.current?.focus(), 80)
      return () => clearTimeout(t)
    }
  }, [open])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return catalog
    return catalog.filter(m =>
      m.label.toLowerCase().includes(q) || m.name.toLowerCase().includes(q),
    )
  }, [catalog, search])

  const selectedMeta = selected
    .map(name => catalog.find(m => m.name === name))
    .filter(Boolean)

  return (
    <div className="relative mb-2">
      <motion.button
        whileTap={{ scale: 0.98 }}
        onClick={() => setOpen(v => !v)}
        className={`w-full flex items-center gap-2 bg-spotify-black/50 rounded-lg px-3 py-2.5 text-left border transition-colors ${
          open ? 'border-spotify-green/60' : 'border-transparent'
        }`}
      >
        <span className="flex-1 min-w-0 flex items-center gap-1.5 text-xs text-white">
          {selectedMeta.length === 1 ? (
            <>
              <span>{selectedMeta[0].emoji}</span>
              <span className="truncate">{selectedMeta[0].label}</span>
            </>
          ) : (
            <>
              <span className="shrink-0">{selectedMeta.slice(0, 4).map(m => m.emoji).join('')}</span>
              <span className="text-spotify-text">
                {selectedMeta.length} {pluralMetrics(selectedMeta.length)}
              </span>
            </>
          )}
        </span>
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={spring}
          className="text-spotify-text text-[10px] shrink-0"
        >
          ▼
        </motion.span>
      </motion.button>

      <AnimatePresence>
        {open && (
          <>
            <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
            <motion.div
              initial={{ opacity: 0, y: -8, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -6, scale: 0.98 }}
              transition={{ type: 'spring', stiffness: 500, damping: 32 }}
              className="absolute left-0 right-0 top-full mt-1.5 z-30 bg-spotify-gray rounded-xl shadow-xl border border-white/10 overflow-hidden"
            >
              <div className="p-2 border-b border-white/5">
                <input
                  ref={inputRef}
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="🔍 Поиск метрики..."
                  className="w-full bg-spotify-black/60 rounded-lg px-3 py-2 text-xs text-white placeholder-spotify-text outline-none focus:ring-1 focus:ring-spotify-green/50"
                />
              </div>
              <div className="max-h-56 overflow-y-auto p-1">
                {filtered.length === 0 ? (
                  <div className="py-6 text-center text-spotify-text text-xs">
                    Ничего не нашлось
                  </div>
                ) : (
                  filtered.map(m => {
                    const active = selected.includes(m.name)
                    return (
                      <motion.button
                        key={m.name}
                        whileTap={{ scale: 0.97 }}
                        onClick={() => onToggle(m.name)}
                        className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-left text-xs transition-colors ${
                          active ? 'bg-spotify-green/10 text-white' : 'text-spotify-text hover:bg-white/5 hover:text-white'
                        }`}
                      >
                        <span className="shrink-0">{m.emoji}</span>
                        <span className="flex-1 truncate">{m.label}</span>
                        <span className={`w-4 h-4 rounded shrink-0 flex items-center justify-center border transition-colors ${
                          active
                            ? 'bg-spotify-green border-spotify-green'
                            : 'border-spotify-text/40'
                        }`}>
                          <AnimatePresence>
                            {active && (
                              <motion.span
                                initial={{ scale: 0 }}
                                animate={{ scale: 1 }}
                                exit={{ scale: 0 }}
                                transition={spring}
                                className="text-black text-[9px] font-bold"
                              >
                                ✓
                              </motion.span>
                            )}
                          </AnimatePresence>
                        </span>
                      </motion.button>
                    )
                  })
                )}
              </div>
              <div className="px-3 py-1.5 border-t border-white/5 text-[9px] text-spotify-text">
                Выбрано: {selected.length} / {MAX_SELECTED}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}

export default function MetricsExplorer() {
  const toast = useToast()
  const [catalog, setCatalog] = useState(null)
  const [selected, setSelected] = useState([])
  const [mode, setMode] = useState('metric')
  const [period, setPeriod] = useState('week')
  const [limit, setLimit] = useState(5)
  const [rank, setRank] = useState('max')
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
      limit: String(limit),
      rank,
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
  }, [selected, mode, period, limit, rank, toast])

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
    setSelected(prev => {
      if (prev.includes(name)) {
        return prev.length > 1 ? prev.filter(n => n !== name) : prev
      }
      if (prev.length >= MAX_SELECTED) {
        toast.info(`Максимум ${MAX_SELECTED} метрик за раз`)
        return prev
      }
      return [...prev, name]
    })
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
  const beyondTop = Math.max(0, (data?.series_total || 0) - (data?.series?.length || 0))

  if (catalog !== null && catalog.length === 0) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-spotify-dark rounded-xl p-4 mb-3 relative"
    >
      <div className="absolute inset-0 rounded-xl overflow-hidden pointer-events-none">
        <div
          className="absolute -top-20 -right-20 w-56 h-56 rounded-full"
          style={{ background: 'radial-gradient(circle, rgba(29,185,84,0.12) 0%, transparent 70%)' }}
        />
      </div>

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
            onClick={() => setMode(m.key)}
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

      <MetricMultiSelect
        catalog={catalog || []}
        selected={selected}
        onToggle={toggleMetric}
      />

      <div className="flex items-center gap-1 mb-2 bg-spotify-black/50 rounded-lg p-0.5 overflow-x-auto">
        <span className="text-spotify-text text-[10px] px-1.5 shrink-0">Линий:</span>
        {LIMIT_OPTIONS.map(n => (
          <motion.button
            key={n}
            whileTap={{ scale: 0.93 }}
            onClick={() => setLimit(n)}
            className={`px-2.5 py-1 rounded-md text-[10px] font-medium transition-colors shrink-0 ${
              limit === n ? 'bg-spotify-green/80 text-black' : 'text-spotify-text hover:text-white'
            }`}
          >
            {n}
          </motion.button>
        ))}
        <span className="text-spotify-text text-[10px] px-1.5 shrink-0 ml-2">топ по:</span>
        {RANK_OPTIONS.map(r => (
          <motion.button
            key={r.key}
            whileTap={{ scale: 0.93 }}
            onClick={() => setRank(r.key)}
            className={`px-2.5 py-1 rounded-md text-[10px] font-medium transition-colors shrink-0 ${
              rank === r.key ? 'bg-white text-black' : 'text-spotify-text hover:text-white'
            }`}
          >
            {r.label}
          </motion.button>
        ))}
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
            key={`${mode}-${period}-${cumulative}-${limit}-${rank}-${selected.join()}`}
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
              {beyondTop > 0 && (
                <span className="flex items-center px-2 py-1 rounded-md text-[10px] text-spotify-text border border-dashed border-spotify-text/30">
                  +{beyondTop} за топом
                </span>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
