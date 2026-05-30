import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
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
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 px-4 py-3.5 rounded-xl bg-zinc-900/70 hover:bg-zinc-800 active:bg-zinc-800 border border-zinc-800 text-left"
    >
      <span className="text-base shrink-0" title={sp.label}>{sp.emoji}</span>
      <span className="text-zinc-500 text-xs font-mono w-10 shrink-0">#{s.id}</span>
      <span className="text-zinc-300 text-xs font-mono w-16 shrink-0">{date}</span>
      <span className="text-white truncate flex-1 text-base">
        {s.player_a_name} <span className="font-mono tabular-nums font-semibold">{a}:{b}</span> {s.player_b_name}
      </span>
      <span className={`text-xs px-2 py-1 rounded ${isLive ? 'bg-emerald-700/60 text-emerald-100' : 'bg-zinc-800 text-zinc-400'}`}>
        {tag}
      </span>
    </button>
  )
}

export default function TennisLobby({ onStartLive, onOpenSession, onOpenImport, onOpenStats, onOpenNewSession }) {
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
        <div className="text-5xl mb-1">🏓🎾</div>
        <h1 className="text-2xl font-bold text-white">Теннис и сквош</h1>
        <p className="text-zinc-400 text-sm">Привет, {greetName}</p>
      </header>

      {liveSession && (
        <button
          onClick={onStartLive}
          className="w-full mb-4 bg-gradient-to-br from-emerald-600 to-emerald-800 text-white rounded-2xl px-5 py-4 text-left shadow-lg active:scale-[0.98] transition-transform"
        >
          <div className="text-[11px] uppercase tracking-wider opacity-80">
            Активная сессия · {sportMeta(liveSession.sport).label}
          </div>
          <div className="font-semibold mt-1 text-lg">
            {sportMeta(liveSession.sport).emoji}{' '}
            {liveSession.player_a_name} {liveSession.wins[0]}:{liveSession.wins[1]} {liveSession.player_b_name}
          </div>
          <div className="text-sm opacity-80 mt-1">Открыть табло →</div>
        </button>
      )}

      <button
        onClick={onOpenNewSession}
        className="w-full mb-3 bg-gradient-to-br from-rose-600 to-rose-800 text-white rounded-2xl px-4 py-6 font-bold text-xl shadow-lg active:scale-[0.98] transition-transform"
      >
        ▶ Начать сессию
      </button>

      <div className="grid grid-cols-2 gap-3 mb-6">
        <button
          onClick={onOpenStats}
          className="bg-zinc-900 hover:bg-zinc-800 active:bg-zinc-800 text-white rounded-2xl px-4 py-5 border border-zinc-800 text-left"
        >
          <div className="text-3xl mb-1">📊</div>
          <div className="font-semibold text-base">Статистика</div>
        </button>
        <button
          onClick={onOpenImport}
          className="bg-zinc-900 hover:bg-zinc-800 active:bg-zinc-800 text-white rounded-2xl px-4 py-5 border border-zinc-800 text-left"
        >
          <div className="text-3xl mb-1">📥</div>
          <div className="font-semibold text-base">Импорт</div>
        </button>
      </div>

      <h2 className="text-zinc-400 text-xs uppercase tracking-wider mb-2">Последние</h2>
      {loadError && (
        <p className="text-red-400 text-sm px-2">{loadError}</p>
      )}
      {sessions === null && !loadError && (
        <p className="text-zinc-500 text-sm px-2">Загружаем…</p>
      )}
      {sessions?.length === 0 && (
        <p className="text-zinc-500 text-sm px-2">Сессий пока нет — запусти первую.</p>
      )}
      <div className="space-y-2">
        {sessions?.filter((s) => s.ended_at).map((s) => (
          <SessionRow key={s.id} s={s} onClick={() => onOpenSession(s.id)} />
        ))}
      </div>
    </motion.div>
  )
}
