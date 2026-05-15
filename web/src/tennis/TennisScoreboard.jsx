import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import WebApp from '@twa-dev/sdk'
import { useAuth } from '../context/useAuth'
import { tennisApi } from './api'

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000]
const SHORT_GAP_MS = 250
const MUTE_KEY = 'tennis:muted'

function fmtClock(seconds) {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  const mm = String(m).padStart(2, '0')
  const sec = String(ss).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${sec}` : `${mm}:${sec}`
}

function buildMatchAnnouncement(match, state) {
  const winnerName = match.winner === 'a' ? state.player_a_name : state.player_b_name
  if (match.score_a == null || match.score_b == null) {
    return `Партия! Победил ${winnerName}.`
  }
  const winnerScore = match.winner === 'a' ? match.score_a : match.score_b
  const loserScore = match.winner === 'a' ? match.score_b : match.score_a
  return `Партия! Победил ${winnerName}. Счёт ${winnerScore} на ${loserScore}.`
}

function buildSetEndAnnouncement(state, setNum) {
  const [a, b] = state.wins
  return `Конец сета ${setNum}. ${state.player_a_name} ${a} партий, ${state.player_b_name} ${b}.`
}

function buildSessionEndAnnouncement(state) {
  const [a, b] = state.wins
  if (a === b) return `Сессия завершена. Ничья: ${a} на ${b}.`
  if (a > b) return `Сессия завершена. Победил ${state.player_a_name} со счётом ${a} на ${b}.`
  return `Сессия завершена. Победил ${state.player_b_name} со счётом ${b} на ${a}.`
}

function speakBrowser(text) {
  if (typeof window === 'undefined') return
  const synth = window.speechSynthesis
  if (!synth) return
  try {
    synth.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.lang = 'ru-RU'
    const voices = synth.getVoices?.() || []
    const ruVoice = voices.find((v) => (v.lang || '').toLowerCase().startsWith('ru'))
    if (ruVoice) u.voice = ruVoice
    synth.speak(u)
  } catch { /* noop */ }
}

// Кэш OGG-блобов от Yandex SpeechKit — повторные фразы играем мгновенно
const ttsCache = new Map()
const ttsAudioRef = { current: null }

async function speakServer(text) {
  let blob = ttsCache.get(text)
  if (!blob) {
    blob = await tennisApi.tts(text)
    if (!blob) return false
    if (ttsCache.size > 64) {
      ttsCache.delete(ttsCache.keys().next().value)
    }
    ttsCache.set(text, blob)
  }
  try { ttsAudioRef.current?.pause?.() } catch { /* noop */ }
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  ttsAudioRef.current = audio
  audio.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true })
  await audio.play().catch(() => { /* autoplay blocked or other */ })
  return true
}

async function speak(text) {
  try {
    const ok = await speakServer(text)
    if (ok) return
  } catch { /* fall through */ }
  speakBrowser(text)
}

function computeSetsCompleted(state) {
  const size = state?.set_size ?? 0
  if (!size) return 0
  return Math.floor((state.matches?.length ?? 0) / size)
}

function PlayerPanel({
  name,
  isYou,
  currentScore,
  partyWins,
  isServing,
  serverProgress,
  color,
  accentText,
  canEdit,
  onPlus,
  onMinus,
  isLeft,
}) {
  return (
    <div
      className={`flex-1 flex flex-col items-center justify-center bg-gradient-to-br ${color} relative select-none`}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className={`absolute ${isLeft ? 'top-3 left-3' : 'top-3 right-3'} flex items-center gap-1.5 max-w-[60%] truncate`}>
        {isServing && (
          <motion.span
            animate={{ scale: [1, 1.18, 1] }}
            transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
            className="text-base"
            title={serverProgress ? `Подача ${serverProgress[0]}/${serverProgress[1]}` : 'Подача'}
          >
            🏓
          </motion.span>
        )}
        <span className={`text-[11px] uppercase tracking-wider ${accentText} opacity-80 truncate`}>
          {name}{isYou ? ' (ты)' : ''}
        </span>
      </div>
      <div className={`absolute ${isLeft ? 'top-3 right-3' : 'top-3 left-3'} text-zinc-300/70 text-xs font-mono`}>
        партий: {partyWins}
      </div>
      <motion.div
        key={currentScore}
        initial={{ scale: 0.78, opacity: 0.4 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', damping: 14, stiffness: 240 }}
        className="text-white font-black tabular-nums leading-none"
        style={{ fontSize: 'clamp(80px, 22vw, 200px)' }}
      >
        {currentScore}
      </motion.div>
      <div className="flex gap-3 mt-6">
        <motion.button
          whileTap={canEdit ? { scale: 0.85 } : {}}
          disabled={!canEdit}
          onClick={onPlus}
          className={`w-20 h-20 rounded-full text-4xl font-bold text-white shadow-lg ${
            canEdit ? 'bg-white/20 hover:bg-white/30 active:bg-white/40' : 'bg-white/5 opacity-40'
          }`}
          aria-label="Очко"
        >
          +
        </motion.button>
        <motion.button
          whileTap={canEdit ? { scale: 0.85 } : {}}
          disabled={!canEdit}
          onClick={onMinus}
          className={`w-20 h-20 rounded-full text-4xl font-bold text-white shadow-lg ${
            canEdit ? 'bg-white/10 hover:bg-white/20 active:bg-white/30' : 'bg-white/5 opacity-40'
          }`}
          aria-label="Отменить"
        >
          −
        </motion.button>
      </div>
    </div>
  )
}

function HistoryPanel({ state, onClose }) {
  const matches = state.matches || []
  return (
    <motion.div
      initial={{ x: '100%' }}
      animate={{ x: 0 }}
      exit={{ x: '100%' }}
      transition={{ type: 'tween', duration: 0.25 }}
      className="absolute right-0 top-0 bottom-0 w-72 max-w-[80vw] bg-zinc-900/95 backdrop-blur-md border-l border-zinc-700 z-20 overflow-y-auto"
      style={{ paddingTop: 'calc(env(safe-area-inset-top) + 12px)' }}
    >
      <div className="flex items-center justify-between px-4 pb-3 border-b border-zinc-800">
        <h3 className="text-white font-semibold">Партии</h3>
        <button onClick={onClose} className="text-zinc-400 hover:text-white text-2xl leading-none">×</button>
      </div>
      {matches.length === 0 ? (
        <p className="px-4 py-6 text-zinc-500 text-sm">Партий пока нет</p>
      ) : (
        <ol className="divide-y divide-zinc-800 text-sm">
          {matches.map((m, i) => {
            const winnerName = m.winner === 'a' ? state.player_a_name : state.player_b_name
            const score = (m.score_a != null && m.score_b != null) ? `${m.score_a}:${m.score_b}` : '—'
            return (
              <li key={i} className="px-4 py-2 flex items-center justify-between gap-2">
                <span className="text-zinc-300">#{i + 1}</span>
                <span className="text-zinc-100 font-mono">{score}</span>
                <span className="text-zinc-500 text-xs truncate flex-1 text-right">{winnerName}</span>
              </li>
            )
          })}
        </ol>
      )}
    </motion.div>
  )
}

export default function TennisScoreboard({ onBackToLobby }) {
  const { userId, initData } = useAuth()
  const [state, setState] = useState(null)
  const [status, setStatus] = useState('connecting')
  const [closeReason, setCloseReason] = useState('')
  const [errorBanner, setErrorBanner] = useState(null)
  const [now, setNow] = useState(Date.now())
  const [historyOpen, setHistoryOpen] = useState(false)
  const [muted, setMuted] = useState(() => {
    try { return window.localStorage?.getItem(MUTE_KEY) === '1' } catch { return false }
  })

  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const reconnectAttempt = useRef(0)
  const lastActivityTap = useRef(0)
  const closedRef = useRef(false)
  const initializedRef = useRef(false)
  const prevMatchesCount = useRef(0)
  const prevSetsAnnounced = useRef(0)
  const mutedRef = useRef(muted)

  useEffect(() => { mutedRef.current = muted }, [muted])

  const send = useCallback((msg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
      return true
    }
    return false
  }, [])

  useEffect(() => {
    try { WebApp?.expand?.() } catch { /* noop */ }
    try { WebApp?.disableVerticalSwipes?.() } catch { /* noop */ }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined' || !window.speechSynthesis) return
    const synth = window.speechSynthesis
    synth.getVoices()
    const onVoices = () => synth.getVoices()
    synth.addEventListener?.('voiceschanged', onVoices)
    return () => synth.removeEventListener?.('voiceschanged', onVoices)
  }, [])

  const handleIncomingState = useCallback((incoming, options = {}) => {
    const newMatches = incoming.matches?.length ?? 0
    const newSetsAnnounced = computeSetsCompleted(incoming)
    if (initializedRef.current && !mutedRef.current) {
      if (newMatches > prevMatchesCount.current) {
        const last = incoming.matches[newMatches - 1]
        speak(buildMatchAnnouncement(last, incoming))
      }
      if (incoming.set_size > 0 && newSetsAnnounced > prevSetsAnnounced.current) {
        const setNum = newSetsAnnounced
        window.setTimeout(() => speak(buildSetEndAnnouncement(incoming, setNum)), 1500)
      }
      if (options.sessionEnd) {
        const text = buildSessionEndAnnouncement(incoming)
        window.setTimeout(() => speak(text), newMatches > prevMatchesCount.current ? 2500 : 0)
      }
    }
    initializedRef.current = true
    prevMatchesCount.current = newMatches
    prevSetsAnnounced.current = newSetsAnnounced
    setState(incoming)
  }, [])

  const connect = useCallback(() => {
    if (closedRef.current) return
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/tennis`)
    wsRef.current = ws

    ws.onopen = () => {
      reconnectAttempt.current = 0
      setStatus('connected')
      ws.send(JSON.stringify({ type: 'hello', init_data: initData || '' }))
    }

    ws.onmessage = (e) => {
      let data
      try { data = JSON.parse(e.data) } catch { return }
      switch (data.type) {
        case 'state':
          handleIncomingState(data.state)
          setStatus('connected')
          break
        case 'closed':
          if (data.state) {
            handleIncomingState(data.state, {
              sessionEnd: data.reason !== 'timeout' && !data.state.is_aggregate_only,
            })
          }
          setCloseReason(data.reason || '')
          setStatus('closed')
          break
        case 'no_active':
          setStatus('no_active')
          if (onBackToLobby) onBackToLobby()
          break
        case 'error':
          setErrorBanner(data.message || 'Ошибка')
          window.setTimeout(() => setErrorBanner(null), 3000)
          break
        default:
          break
      }
    }

    ws.onclose = () => {
      if (closedRef.current) return
      const attempt = reconnectAttempt.current
      const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)]
      reconnectAttempt.current = attempt + 1
      if (attempt >= 2) setStatus('reconnecting')
      reconnectTimer.current = window.setTimeout(connect, delay)
    }

    ws.onerror = () => { try { ws.close() } catch { /* noop */ } }
  }, [initData, handleIncomingState, onBackToLobby])

  useEffect(() => {
    closedRef.current = false
    connect()
    return () => {
      closedRef.current = true
      if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current)
      try { wsRef.current?.close() } catch { /* noop */ }
    }
  }, [connect])

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      const ws = wsRef.current
      if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
        if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current)
        reconnectAttempt.current = 0
        connect()
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [connect])

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])

  const elapsedSec = useMemo(() => {
    if (!state?.started_at) return 0
    const start = Date.parse(state.started_at)
    if (Number.isNaN(start)) return 0
    const end = state.ended_at ? Date.parse(state.ended_at) : now
    return (end - start) / 1000
  }, [state, now])

  const canEdit = Boolean(state?.permissions?.can_edit) && status === 'connected'
  const isClosed = status === 'closed' || Boolean(state?.ended_at)

  const handlePlus = (side) => {
    if (!canEdit || isClosed) return
    const t = Date.now()
    if (t - lastActivityTap.current < SHORT_GAP_MS) return
    lastActivityTap.current = t
    try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('medium') } catch { /* noop */ }
    send({ type: 'point', side })
  }
  const handleMinus = () => {
    if (!canEdit || isClosed) return
    try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('light') } catch { /* noop */ }
    send({ type: 'undo' })
  }
  const handleClose = () => {
    if (!canEdit || isClosed) return
    if (!window.confirm('Закрыть сессию?')) return
    send({ type: 'close' })
  }
  const handleServeToggle = async () => {
    if (!canEdit || isClosed || !state?.id) return
    try {
      await tennisApi.toggleServe(state.id)
    } catch (e) {
      setErrorBanner(e.message || 'Не получилось переключить подачу')
      window.setTimeout(() => setErrorBanner(null), 2500)
    }
  }

  const toggleMute = () => {
    setMuted((prev) => {
      const next = !prev
      try { window.localStorage?.setItem(MUTE_KEY, next ? '1' : '0') } catch { /* noop */ }
      if (next) {
        try { window.speechSynthesis?.cancel() } catch { /* noop */ }
      }
      return next
    })
  }

  if (!state) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-zinc-400 text-sm">
          {status === 'reconnecting' ? 'Восстанавливаем связь…' : 'Подключаемся…'}
        </div>
      </div>
    )
  }

  const nameA = state.player_a_name || 'Игрок A'
  const nameB = state.player_b_name || 'Игрок B'
  const youSideA = userId && state.player_a_id === userId
  const youSideB = userId && state.player_b_id === userId
  const [winsA, winsB] = state.wins ?? [0, 0]
  const [curA, curB] = state.current_score ?? [0, 0]
  const server = state.server || 'a'
  const setSize = state.set_size ?? 0
  const setsCompleted = computeSetsCompleted(state)
  const partyIndex = state.matches?.length ?? 0
  const currentPartyNumber = isClosed ? partyIndex : partyIndex + 1

  return (
    <div className="fixed inset-0 bg-black overflow-hidden">
      <div className="absolute inset-0 flex flex-col landscape:flex-row md:flex-row">
        <PlayerPanel
          name={nameA}
          isYou={youSideA}
          currentScore={curA}
          partyWins={winsA}
          isServing={server === 'a'}
          serverProgress={state.server_progress}
          color="from-rose-700/40 to-rose-950"
          accentText="text-rose-200"
          canEdit={canEdit}
          onPlus={() => handlePlus('a')}
          onMinus={handleMinus}
          isLeft
        />
        <PlayerPanel
          name={nameB}
          isYou={youSideB}
          currentScore={curB}
          partyWins={winsB}
          isServing={server === 'b'}
          serverProgress={state.server_progress}
          color="from-sky-700/40 to-sky-950"
          accentText="text-sky-200"
          canEdit={canEdit}
          onPlus={() => handlePlus('b')}
          onMinus={handleMinus}
        />
      </div>

      {/* Top bar */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-black/60 backdrop-blur-sm rounded-b-2xl px-3 py-1.5 text-white text-sm font-mono z-10">
        <button
          onClick={() => setHistoryOpen(true)}
          className="hover:bg-white/10 rounded px-1.5 py-0.5"
          title="История партий"
        >
          ⏱ {fmtClock(elapsedSec)}
        </button>
        <span className="text-zinc-400 text-xs">· партия {currentPartyNumber}</span>
        {setSize > 0 && (
          <span className="text-zinc-400 text-xs">· сет {setsCompleted + 1} ({partyIndex % setSize}/{setSize})</span>
        )}
        {!isClosed && canEdit && (
          <button
            onClick={handleServeToggle}
            className="ml-1 text-xs px-1.5 py-0.5 rounded hover:bg-white/10"
            title="Переключить первую подачу"
          >
            ↻🏓
          </button>
        )}
        <button
          onClick={toggleMute}
          className="ml-1 text-base leading-none px-1.5 py-0.5 rounded hover:bg-white/10"
          aria-label={muted ? 'Включить озвучку' : 'Выключить озвучку'}
          title={muted ? 'Включить озвучку' : 'Выключить озвучку'}
        >
          {muted ? '🔇' : '🔊'}
        </button>
        {status === 'reconnecting' && (
          <span className="text-amber-300 text-xs animate-pulse">· реконнект</span>
        )}
        {isClosed && (
          <span className="text-zinc-300 text-xs">· закрыта {closeReason === 'timeout' ? '(таймаут)' : ''}</span>
        )}
      </div>

      {/* Bottom bar */}
      <div
        className="absolute left-1/2 -translate-x-1/2 flex items-center gap-2 z-10"
        style={{ bottom: 'calc(env(safe-area-inset-bottom) + 8px)' }}
      >
        {!isClosed && canEdit && (
          <button
            onClick={handleClose}
            className="bg-zinc-900/80 backdrop-blur-sm text-zinc-200 hover:text-white text-xs px-4 py-2 rounded-full border border-zinc-700"
          >
            Завершить
          </button>
        )}
        {isClosed && onBackToLobby && (
          <button
            onClick={onBackToLobby}
            className="bg-zinc-900/80 backdrop-blur-sm text-zinc-200 hover:text-white text-xs px-4 py-2 rounded-full border border-zinc-700"
          >
            В лобби
          </button>
        )}
      </div>

      <AnimatePresence>
        {errorBanner && (
          <motion.div
            initial={{ y: -20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -20, opacity: 0 }}
            className="absolute top-12 left-1/2 -translate-x-1/2 bg-red-600 text-white px-4 py-2 rounded-lg text-sm shadow-lg z-20"
          >
            {errorBanner}
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {historyOpen && (
          <HistoryPanel state={state} onClose={() => setHistoryOpen(false)} />
        )}
      </AnimatePresence>
    </div>
  )
}
