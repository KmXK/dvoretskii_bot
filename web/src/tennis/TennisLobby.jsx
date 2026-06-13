import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { BarChart3, ChevronRight, Download, Play, Watch } from 'lucide-react'
import { useAuth } from '../context/useAuth'
import { tennisApi } from './api'
import { sportMeta } from './sports'

function SessionRow({ s, onClick }) {
  const isLive = s.ended_at === null || s.ended_at === undefined
  const date = new Date(s.started_at).toLocaleDateString('ru-RU', {
    day: '2-digit', month: '2-digit', year: '2-digit',
  })
  const tag = isLive
    ? 'live'
    : s.is_aggregate_only
      ? 'агрегат'
      : `${s.matches_count} парт.`
  const [a, b] = s.wins
  const sp = sportMeta(s.sport)
  return (
    <motion.button
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
      className="w-full flex items-center gap-3 px-3 py-3 rounded-xl bg-spotify-dark hover:bg-white/5 border border-white/5 text-left transition-colors"
    >
      <span className="text-base shrink-0" title={sp.label}>{sp.emoji}</span>
      <span className="text-spotify-text text-xs font-mono w-9 shrink-0 tabular-nums">#{s.id}</span>
      <span className="text-spotify-text text-xs w-14 shrink-0 tabular-nums">{date}</span>
      <span className="text-white truncate flex-1 text-sm">
        {s.player_a_name} <span className="tabular-nums font-semibold">{a}:{b}</span> {s.player_b_name}
      </span>
      <span className={`text-[10px] px-2 py-1 rounded-full ${isLive ? 'bg-spotify-green/15 text-spotify-green' : 'bg-white/5 text-spotify-text'}`}>
        {tag}
      </span>
    </motion.button>
  )
}

export default function TennisLobby({ onStartLive, onOpenSession, onOpenImport, onOpenStats, onOpenNewSession, onOpenWatch }) {
  const { firstName, username } = useAuth()
  const [sessions, setSessions] = useState(null)
  const [loadError, setLoadError] = useState(null)

  useEffect(() => {
    let cancelled = false
    tennisApi.listSessions(10)
      .then((d) => { if (!cancelled) setSessions(d.sessions || []) })
      .catch((e) => { if (!cancelled) setLoadError(e.message || 'Ошибка загрузки') })
    return () => { cancelled = true }
  }, [])

  // Если есть live-сессия — предложим быстро в неё вернуться
  const liveSession = sessions?.find((s) => !s.ended_at)
  const greetName = firstName || username || 'друг'

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="min-h-screen px-4 pt-6 max-w-2xl mx-auto"
      style={{ paddingBottom: 'calc(env(safe-area-inset-bottom) + 80px)' }}
    >
      <header className="mb-6">
        <h1 className="font-display text-2xl font-extrabold tracking-tight text-white flex items-center gap-2">
          <span className="text-2xl">🏓</span> Теннис и сквош
        </h1>
        <p className="text-spotify-text text-sm mt-1">Привет, {greetName}</p>
      </header>

      {liveSession && (
        <motion.button
          whileTap={{ scale: 0.98 }}
          onClick={onStartLive}
          className="w-full mb-4 rounded-2xl border border-gold/30 bg-gold-soft px-5 py-4 text-left transition-colors hover:border-gold/50"
        >
          <div className="text-[11px] uppercase tracking-wider text-gold/80 flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-gold/60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-gold" />
            </span>
            Активная сессия · {sportMeta(liveSession.sport).label}
          </div>
          <div className="font-display font-extrabold mt-1.5 text-lg text-white">
            {sportMeta(liveSession.sport).emoji}{' '}
            {liveSession.player_a_name} <span className="tabular-nums">{liveSession.wins[0]}:{liveSession.wins[1]}</span> {liveSession.player_b_name}
          </div>
          <div className="text-spotify-text text-sm mt-1 flex items-center gap-1">Открыть табло <ChevronRight size={14} /></div>
        </motion.button>
      )}

      <motion.button
        whileTap={{ scale: 0.98 }}
        onClick={onOpenNewSession}
        className="w-full mb-3 flex items-center justify-center gap-2 rounded-2xl bg-gold py-5 font-display font-extrabold text-xl text-spotify-black shadow-lg transition-colors hover:bg-gold-2"
      >
        <Play size={20} strokeWidth={2.5} fill="currentColor" /> Начать сессию
      </motion.button>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <motion.button
          whileTap={{ scale: 0.97 }}
          onClick={onOpenStats}
          className="rounded-2xl border border-white/5 bg-spotify-gray hover:bg-white/5 px-4 py-5 text-left transition-colors"
        >
          <BarChart3 size={24} className="text-gold mb-2" strokeWidth={2} />
          <div className="font-semibold text-white text-base">Статистика</div>
        </motion.button>
        <motion.button
          whileTap={{ scale: 0.97 }}
          onClick={onOpenImport}
          className="rounded-2xl border border-white/5 bg-spotify-gray hover:bg-white/5 px-4 py-5 text-left transition-colors"
        >
          <Download size={24} className="text-indigo mb-2" strokeWidth={2} />
          <div className="font-semibold text-white text-base">Импорт</div>
        </motion.button>
      </div>

      <motion.button
        whileTap={{ scale: 0.98 }}
        onClick={onOpenWatch}
        className="w-full mb-6 flex items-center gap-3 rounded-2xl border border-indigo/30 bg-indigo-soft hover:border-indigo/50 px-4 py-4 text-left transition-colors"
      >
        <Watch size={24} className="text-indigo shrink-0" strokeWidth={2} />
        <span className="flex-1 min-w-0">
          <span className="block font-semibold text-white text-base">Привязать часы</span>
          <span className="block text-spotify-text text-xs">Вести счёт с Galaxy Watch без телефона</span>
        </span>
        <ChevronRight size={18} className="text-indigo shrink-0" />
      </motion.button>

      <h2 className="text-spotify-text text-xs uppercase tracking-wider mb-2">Последние</h2>
      {loadError && (
        <p className="text-red-400 text-sm px-2">{loadError}</p>
      )}
      {sessions === null && !loadError && (
        <p className="text-spotify-text text-sm px-2">Загружаем…</p>
      )}
      {sessions?.length === 0 && (
        <p className="text-spotify-text text-sm px-2">Сессий пока нет — запусти первую.</p>
      )}
      <div className="space-y-2">
        {sessions?.filter((s) => s.ended_at).map((s) => (
          <SessionRow key={s.id} s={s} onClick={() => onOpenSession(s.id)} />
        ))}
      </div>
    </motion.div>
  )
}
