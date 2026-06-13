import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { CircleAlert, CircleCheck, ClipboardList, Check, RotateCcw } from 'lucide-react'
import BackButton from '../components/BackButton'
import Loader from '../components/Loader'
import { api } from '../api/client'


function formatDate(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${dd}.${mm} ${hh}:${mi}`
}


function IncidentCard({ incident, onChange, busy }) {
  const isOpen = incident.status === 'open'
  const [pending, setPending] = useState(false)

  const toggle = async () => {
    setPending(true)
    try {
      const updated = await api.patch(`/api/incidents/${incident.id}`, {
        status: isOpen ? 'resolved' : 'open',
      })
      if (updated && !updated.error) onChange(updated)
    } catch { /* noop */ } finally {
      setPending(false)
    }
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
      className={`rounded-2xl p-4 border ${
        isOpen
          ? 'border-red-500/40 bg-gradient-to-br from-red-500/10 to-rose-700/10'
          : 'border-white/5 bg-spotify-dark'
      }`}
    >
      <div className="flex items-start gap-3">
        <motion.span
          animate={isOpen ? { scale: [1, 1.1, 1] } : { scale: 1 }}
          transition={isOpen ? { duration: 1.8, repeat: Infinity } : undefined}
          className={`shrink-0 ${isOpen ? 'text-red-400' : 'text-spotify-green'}`}
        >
          {isOpen ? <CircleAlert size={24} /> : <CircleCheck size={24} />}
        </motion.span>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline justify-between gap-2">
            <span className={`text-xs font-mono ${isOpen ? 'text-red-300' : 'text-spotify-text/60'}`}>
              №{incident.id} · {formatDate(incident.created_at)}
            </span>
            <span className="text-xs text-spotify-text/60 truncate max-w-[40%]">
              {incident.author_name}
            </span>
          </div>
          <p className={`mt-1.5 text-sm leading-relaxed whitespace-pre-wrap break-words ${
            isOpen ? 'text-white' : 'text-spotify-text line-through'
          }`}>
            {incident.text}
          </p>
          {!isOpen && incident.closed_at && (
            <p className="mt-1.5 text-xs text-spotify-text/60">
              Закрыт {formatDate(incident.closed_at)}
              {incident.closed_by_name ? ` · ${incident.closed_by_name}` : ''}
            </p>
          )}
        </div>
      </div>
      <div className="mt-3 flex justify-end">
        <motion.button
          whileTap={{ scale: 0.96 }}
          disabled={pending || busy}
          onClick={toggle}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
            isOpen
              ? 'bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 border border-emerald-500/30'
              : 'bg-white/5 text-spotify-text hover:bg-white/10 border border-white/10'
          } ${pending ? 'opacity-50' : ''}`}
        >
          <span className="inline-flex items-center gap-1.5">
            {isOpen ? <Check size={14} /> : <RotateCcw size={14} />}
            {isOpen ? 'Закрыть' : 'Переоткрыть'}
          </span>
        </motion.button>
      </div>
    </motion.div>
  )
}


export default function IncidentsPage() {
  const [incidents, setIncidents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('open') // 'open' | 'all'

  useEffect(() => {
    setLoading(true)
    api.get(`/api/incidents?status=${filter === 'open' ? 'open' : 'all'}`)
      .then((d) => {
        setIncidents(Array.isArray(d) ? d : [])
        setError(null)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [filter])

  const onUpdated = (updated) => {
    setIncidents((prev) => {
      const next = prev.map((i) => i.id === updated.id ? updated : i)
      // если фильтр open — убираем resolved из списка
      return filter === 'open' && updated.status !== 'open'
        ? next.filter((i) => i.id !== updated.id)
        : next
    })
  }

  const openCount = useMemo(
    () => incidents.filter((i) => i.status === 'open').length,
    [incidents],
  )

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6 pb-4 max-w-3xl mx-auto"
    >
      <BackButton />
      <div className="flex items-baseline justify-between gap-2 mb-1">
        <h1 className="text-2xl font-bold text-white">Инциденты</h1>
        {openCount > 0 && filter === 'open' && (
          <span className="text-xs text-red-300 font-mono inline-flex items-center gap-1">
            <CircleAlert size={12} /> {openCount} актив.
          </span>
        )}
      </div>
      <p className="text-spotify-text text-sm mb-4">
        Создавай через <code className="text-white">/incident &lt;текст&gt;</code> в чате
      </p>

      <div className="flex gap-2 mb-5">
        {[
          { id: 'open', label: 'Открытые' },
          { id: 'all', label: 'Все' },
        ].map((opt) => (
          <button
            key={opt.id}
            onClick={() => setFilter(opt.id)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              filter === opt.id
                ? 'bg-gold text-black'
                : 'bg-spotify-dark text-spotify-text hover:text-white border border-white/5'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-40">
          <Loader scale={0.6} />
        </div>
      ) : error ? (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400 text-sm">
          {error}
        </div>
      ) : incidents.length === 0 ? (
        <div className="text-center py-16">
          {filter === 'open'
            ? <CircleCheck size={48} className="mx-auto mb-4 text-spotify-green/70" />
            : <ClipboardList size={48} className="mx-auto mb-4 text-spotify-text/60" />}
          <p className="text-spotify-text text-sm">
            {filter === 'open' ? 'Открытых инцидентов нет' : 'Инцидентов ещё не было'}
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          <AnimatePresence initial={false}>
            {incidents.map((inc) => (
              <IncidentCard key={inc.id} incident={inc} onChange={onUpdated} />
            ))}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  )
}
