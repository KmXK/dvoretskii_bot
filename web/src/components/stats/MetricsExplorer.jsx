import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  ReferenceArea,
} from 'recharts'
import { api } from '../../api/client'
import { useToast } from '../../context/useToast'
import { useTheme } from '../../context/useTheme'

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
  '#1DB954', '#3b82f6', '#f43f5e', '#a855f7', '#f59e0b',
  '#22d3ee', '#e879f9', '#84cc16', '#fb7185', '#38bdf8',
  '#facc15', '#4ade80', '#c084fc', '#fb923c', '#2dd4bf',
  '#f472b6', '#a3e635', '#60a5fa', '#fbbf24', '#34d399',
]

const spring = { type: 'spring', stiffness: 500, damping: 35 }

function formatBucketTs(ts, stepSeconds, windowSeconds) {
  const d = new Date(ts * 1000)
  if (windowSeconds <= 86400 * 2) {
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

function formatShortDate(ts) {
  return new Date(ts * 1000).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
}

function toLocalInput(ts) {
  const d = new Date(ts * 1000)
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fromLocalInput(s) {
  const ms = new Date(s).getTime()
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null
}

function pluralOf(n, one, few, many) {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few
  return many
}

function ExplorerTooltip({ active, payload, label, seriesByKey }) {
  if (!active || !payload?.length) return null
  const visible = payload.filter(p => p.value !== undefined && p.value !== null)
  if (!visible.length) return null
  const sorted = [...visible].sort((a, b) => (b.value || 0) - (a.value || 0)).slice(0, 12)
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

function ToolbarButton({ active, onClick, children }) {
  return (
    <motion.button
      whileTap={{ scale: 0.95 }}
      onClick={onClick}
      className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-medium whitespace-nowrap border transition-colors ${
        active
          ? 'bg-spotify-green/15 border-spotify-green/60 text-white'
          : 'bg-spotify-black/50 border-transparent text-spotify-text hover:text-white'
      }`}
    >
      {children}
    </motion.button>
  )
}

function PanelShell({ children }) {
  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: 'auto', opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      transition={{ type: 'spring', stiffness: 400, damping: 34 }}
      className="overflow-hidden"
    >
      <div className="mt-1.5 mb-0.5 bg-spotify-gray/60 rounded-xl border border-white/10 overflow-hidden">
        {children}
      </div>
    </motion.div>
  )
}

function SearchList({ items, selected, onToggle, footer, emptyAction }) {
  const [search, setSearch] = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    const t = setTimeout(() => inputRef.current?.focus(), 80)
    return () => clearTimeout(t)
  }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return items
    return items.filter(it => it.label.toLowerCase().includes(q) || String(it.key).toLowerCase().includes(q))
  }, [items, search])

  return (
    <div>
      <div className="p-2 border-b border-white/5">
        <input
          ref={inputRef}
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="🔍 Поиск..."
          className="w-full bg-spotify-black/60 rounded-lg px-3 py-2 text-xs text-white placeholder-spotify-text outline-none focus:ring-1 focus:ring-spotify-green/50"
        />
      </div>
      <div className="max-h-56 overflow-y-auto p-1">
        {emptyAction}
        {filtered.length === 0 ? (
          <div className="py-6 text-center text-spotify-text text-xs">Ничего не нашлось</div>
        ) : (
          filtered.map(it => {
            const active = selected.includes(it.key)
            return (
              <motion.button
                key={it.key}
                whileTap={{ scale: 0.97 }}
                onClick={() => onToggle(it.key)}
                className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-left text-xs transition-colors ${
                  active ? 'bg-spotify-green/10 text-white' : 'text-spotify-text hover:bg-white/5 hover:text-white'
                }`}
              >
                {it.emoji && <span className="shrink-0">{it.emoji}</span>}
                <span className="flex-1 truncate">{it.label}</span>
                <span className={`w-4 h-4 rounded shrink-0 flex items-center justify-center border transition-colors ${
                  active ? 'bg-spotify-green border-spotify-green' : 'border-spotify-text/40'
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
      {footer && (
        <div className="px-3 py-1.5 border-t border-white/5 text-[9px] text-spotify-text">
          {footer}
        </div>
      )}
    </div>
  )
}

export default function MetricsExplorer() {
  const toast = useToast()
  const { theme } = useTheme()
  const [catalog, setCatalog] = useState(null)
  const [selected, setSelected] = useState([])
  const [mode, setMode] = useState('metric')
  const [period, setPeriod] = useState('week')
  const [custom, setCustom] = useState(null)
  const [rangeFrom, setRangeFrom] = useState('')
  const [rangeTo, setRangeTo] = useState('')
  const [chatsSel, setChatsSel] = useState([])
  const [usersSel, setUsersSel] = useState([])
  const [limit, setLimit] = useState(5)
  const [rank, setRank] = useState('max')
  const [cumulative, setCumulative] = useState(false)
  const [openPanel, setOpenPanel] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [hidden, setHidden] = useState(() => new Set())
  const [drag, setDrag] = useState(null)

  const gridColor = theme === 'light' ? '#d9d9d6' : '#282828'
  const tickColor = theme === 'light' ? '#6b6b6b' : '#b3b3b3'

  useEffect(() => {
    let cancelled = false
    api.get('/api/metrics/catalog')
      .then(d => {
        if (cancelled) return
        setCatalog(d)
        setSelected((d.metrics || []).slice(0, 3).map(m => m.name))
      })
      .catch(() => {
        if (!cancelled) setCatalog({ metrics: [], chats: [], users: [] })
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    setHidden(new Set())
  }, [mode])

  useEffect(() => {
    if (!selected.length) return
    let cancelled = false
    setLoading(true)
    const params = new URLSearchParams({
      metrics: selected.join(','),
      mode,
      limit: String(limit),
      rank,
    })
    if (custom) {
      params.set('start', String(custom.from))
      params.set('end', String(custom.to))
    } else {
      params.set('period', period)
    }
    if (chatsSel.length) params.set('chats', chatsSel.join(','))
    if (usersSel.length) params.set('users', usersSel.join(','))
    api.get(`/api/metrics/range?${params}`)
      .then(d => {
        if (cancelled) return
        setData(d)
      })
      .catch(e => {
        if (cancelled) return
        toast.error(`Не удалось загрузить метрики: ${e.message}`)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [selected, mode, period, custom, chatsSel, usersSel, limit, rank, toast])

  const metricByName = useMemo(
    () => Object.fromEntries((catalog?.metrics || []).map(m => [m.name, m])),
    [catalog],
  )

  const seriesByKey = useMemo(
    () => Object.fromEntries((data?.series || []).map(s => [s.key, s])),
    [data],
  )

  const windowSeconds = useMemo(() => {
    const b = data?.buckets
    if (!b?.length) return 7 * 86400
    return b[b.length - 1] - b[0] + (data.step_seconds || 0)
  }, [data])

  const chartData = useMemo(() => {
    if (!data?.buckets?.length || !data?.series?.length) return []
    const running = {}
    return data.buckets.map((ts, i) => {
      const row = { label: formatBucketTs(ts, data.step_seconds, windowSeconds), ts }
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
  }, [data, cumulative, windowSeconds])

  const legendRows = useMemo(() => (data?.series || []).map(s => {
    const vals = s.values || []
    const max = vals.length ? Math.max(...vals) : 0
    const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0
    return { ...s, max, avg }
  }), [data])

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

  const toggleIn = setter => key => {
    setter(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key])
  }

  const toggleSeries = (key) => {
    setHidden(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const togglePanel = key => {
    setOpenPanel(p => (p === key ? null : key))
    if (key === 'range' && data?.buckets?.length) {
      const from = custom?.from ?? data.buckets[0]
      const to = custom?.to ?? data.buckets[data.buckets.length - 1]
      setRangeFrom(prev => prev || toLocalInput(from))
      setRangeTo(prev => prev || toLocalInput(to))
    }
  }

  const applyCustomRange = () => {
    const from = fromLocalInput(rangeFrom)
    const to = fromLocalInput(rangeTo)
    if (!from || !to || to <= from) {
      toast.error('Неверный интервал: «с» должно быть раньше «по»')
      return
    }
    setCustom({ from, to })
    setOpenPanel(null)
  }

  const onChartMouseDown = useCallback(e => {
    if (e && e.activeTooltipIndex != null) {
      setDrag({ s: e.activeTooltipIndex, e: e.activeTooltipIndex })
    }
  }, [])

  const onChartMouseMove = useCallback(e => {
    if (e && e.activeTooltipIndex != null) {
      setDrag(prev => (prev ? { ...prev, e: e.activeTooltipIndex } : prev))
    }
  }, [])

  const onChartMouseUp = useCallback(() => {
    setDrag(prev => {
      if (prev && data?.buckets?.length) {
        const i1 = Math.min(prev.s, prev.e)
        const i2 = Math.max(prev.s, prev.e)
        if (i2 - i1 >= 2) {
          setCustom({ from: data.buckets[i1], to: data.buckets[i2] })
        }
      }
      return null
    })
  }, [data])

  const visibleSeries = (data?.series || []).filter(s => !hidden.has(s.key))
  const grandTotal = visibleSeries.reduce((acc, s) => acc + (s.total || 0), 0)
  const hasSeries = !loading && chartData.length > 0 && (data?.series?.length || 0) > 0
  const beyondTop = Math.max(0, (data?.series_total || 0) - (data?.series?.length || 0))

  const selectedMeta = selected.map(n => metricByName[n]).filter(Boolean)
  const rangeLabel = custom
    ? `${formatShortDate(custom.from)} – ${formatShortDate(custom.to)}`
    : PERIODS.find(p => p.key === period)?.label
  const metricsLabel = selectedMeta.length === 1
    ? `${selectedMeta[0].emoji} ${selectedMeta[0].label}`
    : `${selectedMeta.slice(0, 3).map(m => m.emoji).join('')} ${selectedMeta.length} ${pluralOf(selectedMeta.length, 'метрика', 'метрики', 'метрик')}`
  const chatsLabel = chatsSel.length ? `💬 ${chatsSel.length}` : '💬 Все чаты'
  const usersLabel = usersSel.length ? `👤 ${usersSel.length}` : '👤 Все люди'

  if (catalog !== null && (catalog.metrics || []).length === 0) return null

  const chatItems = (catalog?.chats || []).map(c => ({ key: c.id, label: c.name, emoji: '💬' }))
  const userItems = (catalog?.users || []).map(u => ({ key: u.id, label: u.name, emoji: '👤' }))
  const metricItems = (catalog?.metrics || []).map(m => ({ key: m.name, label: m.label, emoji: m.emoji }))

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

      <div className="flex flex-wrap gap-1.5">
        <ToolbarButton active={openPanel === 'range' || !!custom} onClick={() => togglePanel('range')}>
          🕐 {rangeLabel}
        </ToolbarButton>
        <ToolbarButton active={openPanel === 'metrics'} onClick={() => togglePanel('metrics')}>
          {metricsLabel}
        </ToolbarButton>
        {chatItems.length > 0 && (
          <ToolbarButton active={openPanel === 'chats' || chatsSel.length > 0} onClick={() => togglePanel('chats')}>
            {chatsLabel}
          </ToolbarButton>
        )}
        {userItems.length > 0 && (
          <ToolbarButton active={openPanel === 'users' || usersSel.length > 0} onClick={() => togglePanel('users')}>
            {usersLabel}
          </ToolbarButton>
        )}
        <ToolbarButton active={openPanel === 'top'} onClick={() => togglePanel('top')}>
          🏆 Топ {limit} · {RANK_OPTIONS.find(r => r.key === rank)?.label}
        </ToolbarButton>
        <ToolbarButton active={cumulative} onClick={() => setCumulative(v => !v)}>
          <span className="text-xs leading-none">∑</span> Накопительно
        </ToolbarButton>
      </div>

      <AnimatePresence initial={false} mode="wait">
        {openPanel === 'range' && (
          <PanelShell key="range">
            <div className="p-2 space-y-2">
              <div className="flex flex-wrap gap-1">
                {PERIODS.map(p => (
                  <motion.button
                    key={p.key}
                    whileTap={{ scale: 0.93 }}
                    onClick={() => { setPeriod(p.key); setCustom(null); setOpenPanel(null) }}
                    className={`px-2.5 py-1.5 rounded-md text-[10px] font-medium transition-colors ${
                      !custom && period === p.key
                        ? 'bg-spotify-green text-black'
                        : 'bg-spotify-black/40 text-spotify-text hover:text-white'
                    }`}
                  >
                    {p.label}
                  </motion.button>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <input
                  type="datetime-local"
                  value={rangeFrom}
                  onChange={e => setRangeFrom(e.target.value)}
                  className="flex-1 min-w-[140px] bg-spotify-black/60 rounded-lg px-2 py-1.5 text-[10px] text-white outline-none focus:ring-1 focus:ring-spotify-green/50"
                />
                <span className="text-spotify-text text-[10px]">—</span>
                <input
                  type="datetime-local"
                  value={rangeTo}
                  onChange={e => setRangeTo(e.target.value)}
                  className="flex-1 min-w-[140px] bg-spotify-black/60 rounded-lg px-2 py-1.5 text-[10px] text-white outline-none focus:ring-1 focus:ring-spotify-green/50"
                />
                <motion.button
                  whileTap={{ scale: 0.93 }}
                  onClick={applyCustomRange}
                  className="bg-spotify-green text-black text-[10px] font-semibold px-3 py-1.5 rounded-lg"
                >
                  Применить
                </motion.button>
              </div>
              <p className="text-spotify-text text-[9px]">
                Подсказка: интервал можно выделить мышкой прямо на графике
              </p>
            </div>
          </PanelShell>
        )}
        {openPanel === 'metrics' && (
          <PanelShell key="metrics">
            <SearchList
              items={metricItems}
              selected={selected}
              onToggle={toggleMetric}
              footer={`Выбрано: ${selected.length} / ${MAX_SELECTED}`}
            />
          </PanelShell>
        )}
        {openPanel === 'chats' && (
          <PanelShell key="chats">
            <SearchList
              items={chatItems}
              selected={chatsSel}
              onToggle={toggleIn(setChatsSel)}
              emptyAction={
                <motion.button
                  whileTap={{ scale: 0.97 }}
                  onClick={() => setChatsSel([])}
                  className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-left text-xs transition-colors ${
                    chatsSel.length === 0 ? 'bg-spotify-green/10 text-white' : 'text-spotify-text hover:bg-white/5'
                  }`}
                >
                  <span>🌐</span>
                  <span className="flex-1">Все чаты</span>
                </motion.button>
              }
              footer="Пусто = без фильтра. Метрики без чата при фильтре скрываются"
            />
          </PanelShell>
        )}
        {openPanel === 'users' && (
          <PanelShell key="users">
            <SearchList
              items={userItems}
              selected={usersSel}
              onToggle={toggleIn(setUsersSel)}
              emptyAction={
                <motion.button
                  whileTap={{ scale: 0.97 }}
                  onClick={() => setUsersSel([])}
                  className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-left text-xs transition-colors ${
                    usersSel.length === 0 ? 'bg-spotify-green/10 text-white' : 'text-spotify-text hover:bg-white/5'
                  }`}
                >
                  <span>🌐</span>
                  <span className="flex-1">Все люди</span>
                </motion.button>
              }
              footer="Пусто = без фильтра"
            />
          </PanelShell>
        )}
        {openPanel === 'top' && (
          <PanelShell key="top">
            <div className="p-2 space-y-2">
              <div className="flex items-center gap-1">
                <span className="text-spotify-text text-[10px] px-1 shrink-0">Линий:</span>
                {LIMIT_OPTIONS.map(n => (
                  <motion.button
                    key={n}
                    whileTap={{ scale: 0.93 }}
                    onClick={() => setLimit(n)}
                    className={`px-3 py-1.5 rounded-md text-[10px] font-medium transition-colors ${
                      limit === n ? 'bg-spotify-green text-black' : 'bg-spotify-black/40 text-spotify-text hover:text-white'
                    }`}
                  >
                    {n}
                  </motion.button>
                ))}
              </div>
              <div className="flex items-center gap-1">
                <span className="text-spotify-text text-[10px] px-1 shrink-0">Топ по:</span>
                {RANK_OPTIONS.map(r => (
                  <motion.button
                    key={r.key}
                    whileTap={{ scale: 0.93 }}
                    onClick={() => setRank(r.key)}
                    className={`px-3 py-1.5 rounded-md text-[10px] font-medium transition-colors ${
                      rank === r.key ? 'bg-spotify-green text-black' : 'bg-spotify-black/40 text-spotify-text hover:text-white'
                    }`}
                  >
                    {r.label}
                  </motion.button>
                ))}
              </div>
            </div>
          </PanelShell>
        )}
      </AnimatePresence>

      <div className="flex items-center justify-between mt-2 mb-1 min-h-[20px]">
        <AnimatePresence>
          {custom && (
            <motion.button
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -8 }}
              whileTap={{ scale: 0.93 }}
              onClick={() => setCustom(null)}
              className="flex items-center gap-1 text-[10px] text-spotify-green font-medium"
            >
              ↺ Сбросить зум ({rangeLabel})
            </motion.button>
          )}
        </AnimatePresence>
        {loading && data && (
          <div className="w-3.5 h-3.5 border-2 border-spotify-green border-t-transparent rounded-full animate-spin ml-auto" />
        )}
      </div>

      <AnimatePresence mode="wait">
        {loading && !data ? (
          <motion.div key="skeleton" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <ChartSkeleton />
          </motion.div>
        ) : !hasSeries ? (
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
            key={`${mode}-${period}-${custom?.from}-${cumulative}-${limit}-${rank}-${selected.join()}-${chatsSel.join()}-${usersSel.join()}`}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.25 }}
          >
            {visibleSeries.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-60 text-spotify-text text-sm gap-3">
                <motion.span
                  className="text-3xl"
                  animate={{ rotate: [0, -10, 10, 0] }}
                  transition={{ duration: 1.6, repeat: Infinity, repeatDelay: 1 }}
                >
                  🙈
                </motion.span>
                <span>Все линии выключены</span>
                <motion.button
                  whileTap={{ scale: 0.93 }}
                  onClick={() => setHidden(new Set())}
                  className="bg-spotify-green text-black text-xs font-semibold px-4 py-2 rounded-full"
                >
                  Включить все
                </motion.button>
              </div>
            ) : (
            <div className="h-60 select-none">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={chartData}
                  margin={{ top: 5, right: 8, bottom: 0, left: 0 }}
                  onMouseDown={onChartMouseDown}
                  onMouseMove={drag ? onChartMouseMove : undefined}
                  onMouseUp={onChartMouseUp}
                  onMouseLeave={() => setDrag(null)}
                >
                  <defs>
                    {data.series.map((s, i) => (
                      <linearGradient key={s.key} id={`mx-grad-${i}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={LINE_COLORS[i % LINE_COLORS.length]} stopOpacity={0.28} />
                        <stop offset="100%" stopColor={LINE_COLORS[i % LINE_COLORS.length]} stopOpacity={0} />
                      </linearGradient>
                    ))}
                  </defs>
                  <CartesianGrid stroke={gridColor} strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fill: tickColor, fontSize: 9 }}
                    tickLine={false}
                    axisLine={false}
                    interval="preserveStartEnd"
                    minTickGap={28}
                  />
                  <YAxis
                    tick={{ fill: tickColor, fontSize: 10 }}
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
                  {drag && chartData[Math.min(drag.s, drag.e)] && chartData[Math.max(drag.s, drag.e)] && (
                    <ReferenceArea
                      x1={chartData[Math.min(drag.s, drag.e)].label}
                      x2={chartData[Math.max(drag.s, drag.e)].label}
                      fill="#1DB954"
                      fillOpacity={0.12}
                      stroke="#1DB954"
                      strokeOpacity={0.4}
                    />
                  )}
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
                        isAnimationActive={!drag}
                      />
                    )
                  })}
                </AreaChart>
              </ResponsiveContainer>
            </div>
            )}

            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="text-spotify-text text-left">
                    <th className="font-medium pb-1 pr-2"></th>
                    <th className="font-medium pb-1 pr-2 text-right">Сумма</th>
                    <th className="font-medium pb-1 pr-2 text-right">Сред</th>
                    <th className="font-medium pb-1 text-right">Макс</th>
                  </tr>
                </thead>
                <tbody>
                  {legendRows.map((s, i) => {
                    const color = LINE_COLORS[i % LINE_COLORS.length]
                    const isHidden = hidden.has(s.key)
                    const meta = mode === 'metric' ? metricByName[s.key] : null
                    return (
                      <tr
                        key={s.key}
                        onClick={() => toggleSeries(s.key)}
                        className={`cursor-pointer border-t border-white/5 transition-opacity hover:bg-white/5 ${
                          isHidden ? 'opacity-40' : 'opacity-100'
                        }`}
                      >
                        <td className="py-1.5 pr-2">
                          <span className="flex items-center gap-1.5 min-w-0">
                            <span
                              className="w-2 h-2 rounded-full shrink-0"
                              style={{ background: isHidden ? '#666' : color }}
                            />
                            <span className={`text-white truncate max-w-[140px] ${s.is_me ? 'font-semibold' : ''}`}>
                              {s.is_me ? '⭐ ' : ''}{(meta?.emoji || s.emoji) ?? ''} {meta?.label || s.label}
                            </span>
                          </span>
                        </td>
                        <td className="py-1.5 pr-2 text-right text-white font-medium">{formatNum(s.total)}</td>
                        <td className="py-1.5 pr-2 text-right text-spotify-text">{formatNum(s.avg)}</td>
                        <td className="py-1.5 text-right text-spotify-text">{formatNum(s.max)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {beyondTop > 0 && (
                <div className="mt-1.5 text-[9px] text-spotify-text">
                  +{beyondTop} {pluralOf(beyondTop, 'линия', 'линии', 'линий')} за топом — подними лимит в «Топ»
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
