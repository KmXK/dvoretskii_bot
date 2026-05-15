import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import WebApp from '@twa-dev/sdk'
import { useAuth } from '../context/useAuth'
import { tennisApi } from './api'
import { createVoiceController, parseVoiceCommand } from './voice'
import { useConfirmDialog } from './ConfirmDialog'

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000]
const SHORT_GAP_MS = 250
const MUTE_KEY = 'tennis:muted'
const SERVE_REMINDER_MS = 2000

function fmtClock(seconds) {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  const mm = String(m).padStart(2, '0')
  const sec = String(ss).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${sec}` : `${mm}:${sec}`
}

function fmtDuration(seconds) {
  if (seconds == null || !isFinite(seconds)) return '—'
  if (seconds < 60) return `${Math.round(seconds)}с`
  if (seconds < 3600) return `${Math.round(seconds / 60)} мин`
  return `${(seconds / 3600).toFixed(1)} ч`
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

const ttsCache = new Map()
const ttsAudioRef = { current: null }

async function speakServer(text) {
  let blob = ttsCache.get(text)
  if (!blob) {
    blob = await tennisApi.tts(text)
    if (!blob) return false
    if (ttsCache.size > 64) ttsCache.delete(ttsCache.keys().next().value)
    ttsCache.set(text, blob)
  }
  try { ttsAudioRef.current?.pause?.() } catch { /* noop */ }
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  ttsAudioRef.current = audio
  audio.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true })
  await audio.play().catch(() => {})
  return true
}

async function speak(text) {
  try {
    const ok = await speakServer(text)
    if (ok) return
  } catch { /* fallthrough */ }
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
      className={`flex-1 flex flex-col bg-gradient-to-br ${color} relative select-none overflow-hidden`}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className={`absolute ${isLeft ? 'top-3 left-3' : 'top-3 right-3'} flex items-center gap-1.5 max-w-[55%] truncate z-10`}>
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
      <div className={`absolute ${isLeft ? 'top-3 right-3' : 'top-3 left-3'} text-zinc-300/70 text-xs font-mono z-10`}>
        партий: {partyWins}
      </div>

      {/* Большая зона +1: занимает весь центр + низ */}
      <motion.button
        whileTap={canEdit ? { scale: 0.97 } : {}}
        disabled={!canEdit}
        onClick={onPlus}
        className={`flex-1 flex flex-col items-center justify-center w-full ${canEdit ? 'active:bg-white/5' : 'opacity-90'}`}
        aria-label="Добавить очко"
      >
        <motion.div
          key={currentScore}
          initial={{ scale: 0.78, opacity: 0.4 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', damping: 14, stiffness: 240 }}
          className="text-white font-black tabular-nums leading-none"
          style={{ fontSize: 'clamp(120px, 30vw, 280px)' }}
        >
          {currentScore}
        </motion.div>
        <span className="text-white/30 text-xs mt-3 uppercase tracking-wider">тап = +1</span>
      </motion.button>

      {/* Маленький undo внизу */}
      <button
        disabled={!canEdit}
        onClick={onMinus}
        className={`absolute ${isLeft ? 'bottom-3 right-3' : 'bottom-3 left-3'} w-12 h-12 rounded-full text-2xl font-bold text-white shadow-lg z-10 ${
          canEdit ? 'bg-white/10 hover:bg-white/20 active:bg-white/30' : 'bg-white/5 opacity-30'
        }`}
        aria-label="Отменить последний поинт"
        title="Отменить"
      >
        −
      </button>
    </div>
  )
}

// ── Sheet быстрого финиша ─────────────────────────────────────────────────────

function FinishPartySheet({ state, onSubmit, onClose }) {
  const [winnerSide, setWinnerSide] = useState('a')
  const [loserScore, setLoserScore] = useState(7)

  const winnerScoreDisplay = loserScore < 10 ? 11 : loserScore + 2

  const handleConfirm = () => {
    const a = winnerSide === 'a' ? winnerScoreDisplay : loserScore
    const b = winnerSide === 'b' ? winnerScoreDisplay : loserScore
    onSubmit(a, b)
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm flex items-end justify-center"
      onClick={onClose}
    >
      <motion.div
        initial={{ y: '100%' }}
        animate={{ y: 0 }}
        exit={{ y: '100%' }}
        transition={{ type: 'spring', damping: 26, stiffness: 280 }}
        className="bg-zinc-900 border-t border-zinc-700 w-full max-w-2xl rounded-t-2xl shadow-2xl"
        style={{ paddingBottom: 'calc(env(safe-area-inset-bottom) + 14px)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
          <h2 className="text-white font-semibold">Записать партию счётом</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-white text-2xl leading-none">×</button>
        </div>
        <div className="px-4 py-3">
          <div className="text-xs uppercase tracking-wider text-zinc-500 mb-2">Победил</div>
          <div className="grid grid-cols-2 gap-2 mb-4">
            <button
              onClick={() => setWinnerSide('a')}
              className={`py-3 rounded-lg font-medium ${
                winnerSide === 'a' ? 'bg-rose-700 text-white' : 'bg-zinc-800 text-zinc-300'
              }`}
            >
              {state.player_a_name}
            </button>
            <button
              onClick={() => setWinnerSide('b')}
              className={`py-3 rounded-lg font-medium ${
                winnerSide === 'b' ? 'bg-sky-700 text-white' : 'bg-zinc-800 text-zinc-300'
              }`}
            >
              {state.player_b_name}
            </button>
          </div>

          <div className="text-xs uppercase tracking-wider text-zinc-500 mb-2">
            Счёт партии — {winnerScoreDisplay}:{loserScore}
          </div>
          <div className="grid grid-cols-5 gap-1.5 mb-3">
            {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
              <button
                key={n}
                onClick={() => setLoserScore(n)}
                className={`py-3 rounded-lg text-xl font-bold ${
                  loserScore === n ? 'bg-zinc-600 text-white' : 'bg-zinc-800 text-zinc-300'
                }`}
              >
                {n}
              </button>
            ))}
          </div>

          {/* Большой счёт проигравшего (deuce): incrementer */}
          <div className="flex items-center gap-2 mb-3">
            <button
              onClick={() => setLoserScore((n) => Math.max(0, n - 1))}
              className="w-12 h-12 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-white text-2xl font-bold"
              aria-label="-1"
            >
              −
            </button>
            <div className="flex-1 bg-zinc-800 rounded-lg py-3 text-center">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">проиграл</div>
              <div className="text-3xl font-bold text-white tabular-nums">{loserScore}</div>
            </div>
            <button
              onClick={() => setLoserScore((n) => Math.min(50, n + 1))}
              className="w-12 h-12 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-white text-2xl font-bold"
              aria-label="+1"
            >
              +
            </button>
          </div>

          <p className="text-zinc-500 text-[11px] mb-4">
            Победитель получает {winnerScoreDisplay}
            {loserScore >= 10 && ' (deuce — победа с разницей в 2)'}
          </p>

          <button
            onClick={handleConfirm}
            className="w-full bg-gradient-to-br from-emerald-600 to-emerald-800 text-white py-3 rounded-xl font-semibold"
          >
            Записать партию {winnerScoreDisplay}:{loserScore}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

// ── HistoryPanel со сводкой ───────────────────────────────────────────────────

function HistoryPanel({ state, elapsedSec, onClose }) {
  const matches = state.matches || []
  const [winsA, winsB] = state.wins ?? [0, 0]
  const totalMatches = matches.length

  const durations = matches
    .map((m) => (m.ended_at && m.started_at)
      ? (Date.parse(m.ended_at) - Date.parse(m.started_at)) / 1000
      : null)
    .filter((x) => x != null)
  const avgMatchSec = durations.length
    ? durations.reduce((a, b) => a + b, 0) / durations.length
    : null

  const scoredMatches = matches.filter((m) => m.score_a != null && m.score_b != null)
  const avgDiff = scoredMatches.length
    ? scoredMatches.reduce((a, m) => a + Math.abs((m.score_a ?? 0) - (m.score_b ?? 0)), 0) / scoredMatches.length
    : null

  return (
    <motion.div
      initial={{ x: '100%' }}
      animate={{ x: 0 }}
      exit={{ x: '100%' }}
      transition={{ type: 'tween', duration: 0.25 }}
      className="absolute right-0 top-0 bottom-0 w-80 max-w-[85vw] bg-zinc-900/95 backdrop-blur-md border-l border-zinc-700 z-20 overflow-y-auto"
      style={{ paddingTop: 'calc(env(safe-area-inset-top) + 12px)' }}
    >
      <div className="flex items-center justify-between px-4 pb-3 border-b border-zinc-800">
        <h3 className="text-white font-semibold">Сводка сессии</h3>
        <button onClick={onClose} className="text-zinc-400 hover:text-white text-2xl leading-none">×</button>
      </div>

      <div className="px-4 py-3 border-b border-zinc-800 space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-zinc-400">Длительность</span>
          <span className="text-white font-mono">{fmtClock(elapsedSec)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-400">Партий</span>
          <span className="text-white font-mono">{totalMatches}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-400">Счёт</span>
          <span className="text-white font-mono tabular-nums">
            {winsA} : {winsB}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-400">Среднее партии</span>
          <span className="text-white font-mono">{fmtDuration(avgMatchSec)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-400">Средняя разница</span>
          <span className="text-white font-mono">{avgDiff != null ? avgDiff.toFixed(1) : '—'}</span>
        </div>
        {state.set_size > 0 && (
          <div className="flex justify-between">
            <span className="text-zinc-400">Сетов сыграно</span>
            <span className="text-white font-mono">{computeSetsCompleted(state)}</span>
          </div>
        )}
      </div>

      <div className="px-4 py-2 text-xs uppercase tracking-wider text-zinc-500">Партии</div>
      {matches.length === 0 ? (
        <p className="px-4 py-3 text-zinc-500 text-sm">Партий пока нет</p>
      ) : (
        <ol className="divide-y divide-zinc-800 text-sm">
          {matches.map((m, i) => {
            const winnerName = m.winner === 'a' ? state.player_a_name : state.player_b_name
            const score = (m.score_a != null && m.score_b != null) ? `${m.score_a}:${m.score_b}` : '—'
            const dur = (m.ended_at && m.started_at)
              ? (Date.parse(m.ended_at) - Date.parse(m.started_at)) / 1000 : null
            return (
              <li key={i} className="px-4 py-2 flex items-center justify-between gap-2">
                <span className="text-zinc-500 w-7">#{i + 1}</span>
                <span className="text-zinc-100 font-mono w-14">{score}</span>
                <span className="text-zinc-400 text-xs truncate flex-1">{winnerName}</span>
                {dur != null && <span className="text-zinc-500 text-xs font-mono">{fmtDuration(dur)}</span>}
              </li>
            )
          })}
        </ol>
      )}
    </motion.div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function TennisScoreboard({ onBackToLobby }) {
  const { userId, initData } = useAuth()
  const [state, setState] = useState(null)
  const [status, setStatus] = useState('connecting')
  const [closeReason, setCloseReason] = useState('')
  const [errorBanner, setErrorBanner] = useState(null)
  const [now, setNow] = useState(Date.now())
  const [historyOpen, setHistoryOpen] = useState(false)
  const [finishOpen, setFinishOpen] = useState(false)
  const [voiceActive, setVoiceActive] = useState(false)
  const [voiceHint, setVoiceHint] = useState(null)
  const [muted, setMuted] = useState(() => {
    try { return window.localStorage?.getItem(MUTE_KEY) === '1' } catch { return false }
  })
  const { confirm, element: confirmEl } = useConfirmDialog()

  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const reconnectAttempt = useRef(0)
  const lastActivityTap = useRef(0)
  const closedRef = useRef(false)
  const initializedRef = useRef(false)
  const prevMatchesCount = useRef(0)
  const prevSetsAnnounced = useRef(0)
  const mutedRef = useRef(muted)
  const serveReminderTimer = useRef(null)
  const lastServeHash = useRef(null)
  const voiceCtrlRef = useRef(null)
  const stateRef = useRef(null)

  useEffect(() => { mutedRef.current = muted }, [muted])
  useEffect(() => { stateRef.current = state }, [state])

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

  // TTS-напоминалка о подаче: через 2с после последнего изменения state.
  // Один раз на уникальное состояние (server + current_score + matches_len).
  useEffect(() => {
    if (!state || muted) return
    if (state.ended_at || status !== 'connected') return
    if (serveReminderTimer.current) window.clearTimeout(serveReminderTimer.current)
    serveReminderTimer.current = window.setTimeout(() => {
      const [a, b] = state.current_score ?? [0, 0]
      if (a === 0 && b === 0) return  // только что началась партия — без напоминалки
      const hash = `${state.server}|${a}|${b}|${state.matches?.length ?? 0}`
      if (lastServeHash.current === hash) return
      lastServeHash.current = hash
      const serverName = state.server === 'a' ? state.player_a_name : state.player_b_name
      speak(`Подаёт ${serverName}.`)
    }, SERVE_REMINDER_MS)
    return () => { if (serveReminderTimer.current) window.clearTimeout(serveReminderTimer.current) }
  }, [state, muted, status])

  // Voice control — continuous listening + парсер команд
  useEffect(() => {
    if (!voiceActive) {
      if (voiceCtrlRef.current) voiceCtrlRef.current.stop()
      return
    }
    if (!voiceCtrlRef.current) {
      voiceCtrlRef.current = createVoiceController({
        onTranscript: (t) => {
          setVoiceHint(t)
          window.setTimeout(() => setVoiceHint(null), 2500)
        },
        onCommand: (text) => {
          const cur = stateRef.current
          if (!cur || cur.ended_at) return
          const cmd = parseVoiceCommand(text, cur)
          if (!cmd) return
          try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('light') } catch { /* noop */ }
          send(cmd)
        },
        onError: (err) => {
          if (err === 'not-allowed' || err === 'service-not-allowed') {
            setVoiceActive(false)
            setErrorBanner('Микрофон не разрешён')
            window.setTimeout(() => setErrorBanner(null), 3000)
          }
        },
      })
    }
    if (!voiceCtrlRef.current.supported) {
      setVoiceActive(false)
      setErrorBanner('Голос не поддерживается в этом браузере')
      window.setTimeout(() => setErrorBanner(null), 3000)
      return
    }
    voiceCtrlRef.current.start()
    return () => { voiceCtrlRef.current?.stop?.() }
  }, [voiceActive, send])

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
  const handleClose = async () => {
    if (!canEdit || isClosed) return
    const ok = await confirm({
      title: 'Закрыть сессию?',
      description: 'Сессия закроется и попадёт в историю — больше очки в ней не добавить.',
      confirmLabel: 'Закрыть',
      destructive: true,
    })
    if (!ok) return
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
  const handleFinishParty = (a, b) => {
    setFinishOpen(false)
    send({ type: 'finish_party', score_a: a, score_b: b })
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
      <div className="absolute top-0 left-1/2 -translate-x-1/2 flex items-center gap-1.5 bg-black/60 backdrop-blur-sm rounded-b-2xl px-3 py-1.5 text-white text-sm font-mono z-10 flex-wrap max-w-[96vw] justify-center">
        <button
          onClick={() => setHistoryOpen(true)}
          className="hover:bg-white/10 rounded px-1.5 py-0.5"
          title="Сводка сессии"
        >
          ⏱ {fmtClock(elapsedSec)}
        </button>
        <span className="text-zinc-400 text-xs">партия {currentPartyNumber}</span>
        {setSize > 0 && (
          <span className="text-zinc-400 text-xs">сет {setsCompleted + 1} ({partyIndex % setSize}/{setSize})</span>
        )}
        {!isClosed && canEdit && (
          <>
            <button
              onClick={() => setFinishOpen(true)}
              className="text-xs px-1.5 py-0.5 rounded hover:bg-white/10"
              title="Записать партию счётом"
            >
              📝
            </button>
            <button
              onClick={handleServeToggle}
              className="text-xs px-1.5 py-0.5 rounded hover:bg-white/10"
              title="Переключить первую подачу"
            >
              ↻🏓
            </button>
            <button
              onClick={() => setVoiceActive((v) => !v)}
              className={`text-base leading-none px-1.5 py-0.5 rounded ${voiceActive ? 'bg-rose-700' : 'hover:bg-white/10'}`}
              aria-label={voiceActive ? 'Выключить голос' : 'Голосовое управление'}
              title={voiceActive ? 'Голос активен — тапни чтобы выключить' : 'Голосовое управление'}
            >
              🎤
            </button>
          </>
        )}
        <button
          onClick={toggleMute}
          className="text-base leading-none px-1.5 py-0.5 rounded hover:bg-white/10"
          aria-label={muted ? 'Включить озвучку' : 'Выключить озвучку'}
          title={muted ? 'Включить озвучку' : 'Выключить озвучку'}
        >
          {muted ? '🔇' : '🔊'}
        </button>
        {status === 'reconnecting' && (
          <span className="text-amber-300 text-xs animate-pulse">реконнект</span>
        )}
        {isClosed && (
          <span className="text-zinc-300 text-xs">закрыта {closeReason === 'timeout' ? '(таймаут)' : ''}</span>
        )}
      </div>

      {/* Voice hint */}
      <AnimatePresence>
        {voiceActive && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="absolute top-14 left-1/2 -translate-x-1/2 bg-rose-700/90 text-white text-xs px-3 py-1.5 rounded-full z-10 max-w-[80vw] truncate"
          >
            🎤 {voiceHint || 'слушаю…'}
          </motion.div>
        )}
      </AnimatePresence>

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
            Завершить сессию
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
          <HistoryPanel state={state} elapsedSec={elapsedSec} onClose={() => setHistoryOpen(false)} />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {finishOpen && (
          <FinishPartySheet
            state={state}
            onClose={() => setFinishOpen(false)}
            onSubmit={handleFinishParty}
          />
        )}
      </AnimatePresence>

      {confirmEl}
    </div>
  )
}
