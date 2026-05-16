import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import WebApp from '@twa-dev/sdk'
import { useAuth } from '../context/useAuth'
import { tennisApi } from './api'
import { useConfirmDialog } from './ConfirmDialog'

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000]
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

function fmtDuration(seconds) {
  if (seconds == null || !isFinite(seconds)) return '—'
  if (seconds < 60) return `${Math.round(seconds)}с`
  if (seconds < 3600) return `${Math.round(seconds / 60)} мин`
  return `${(seconds / 3600).toFixed(1)} ч`
}

function isValidPartyScore(a, b) {
  if (a === b) return false
  const hi = Math.max(a, b)
  const lo = Math.min(a, b)
  return hi >= 11 && hi - lo >= 2
}

function serverForNextPoint(firstServer, a, b) {
  const total = a + b
  const other = (s) => (s === 'a' ? 'b' : 'a')
  if (a >= 10 && b >= 10) {
    const deucePoints = total - 20
    return deucePoints % 2 === 0 ? firstServer : other(firstServer)
  }
  const pair = Math.floor(total / 2)
  return pair % 2 === 0 ? firstServer : other(firstServer)
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
  } catch { /* fall through */ }
  speakBrowser(text)
}

function computeSetsCompleted(state) {
  const size = state?.set_size ?? 0
  if (!size) return 0
  return Math.floor((state.matches?.length ?? 0) / size)
}

// ── PlayerHalf: тап = +1 в локальный entry ────────────────────────────────────

function PlayerHalf({ name, isYou, entry, partyWins, isServing, color, accentText, canEdit, onTap, onUndo, isLeft }) {
  return (
    <div
      className={`flex-1 flex flex-col bg-gradient-to-br ${color} relative select-none overflow-hidden`}
      onContextMenu={(e) => e.preventDefault()}
    >
      {/* Header */}
      <div className={`absolute ${isLeft ? 'top-3 left-3' : 'top-3 right-3'} z-10 flex items-center gap-1.5 max-w-[70%]`}>
        {isServing && (
          <motion.span
            animate={{ scale: [1, 1.18, 1] }}
            transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
            className="text-base"
          >🏓</motion.span>
        )}
        <span className={`text-xs uppercase tracking-wider ${accentText} opacity-90 truncate font-semibold`}>
          {name}{isYou ? ' · ты' : ''}
        </span>
      </div>
      <div className={`absolute ${isLeft ? 'top-3 right-3' : 'top-3 left-3'} z-10 text-zinc-300/70 text-xs font-mono`}>
        партий: {partyWins}
      </div>

      {/* Огромная тап-зона = +1 */}
      <motion.button
        whileTap={canEdit ? { scale: 0.97 } : {}}
        disabled={!canEdit}
        onClick={onTap}
        className={`flex-1 flex flex-col items-center justify-center w-full ${canEdit ? 'active:bg-white/5' : 'opacity-90'}`}
        aria-label={`Очко ${name}`}
      >
        <motion.div
          key={entry}
          initial={{ scale: 0.78, opacity: 0.4 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', damping: 14, stiffness: 240 }}
          className="text-white font-black tabular-nums leading-none"
          style={{ fontSize: 'clamp(140px, 36vw, 320px)' }}
        >
          {entry}
        </motion.div>
      </motion.button>

      {/* Undo — крупная кнопка в углу */}
      <button
        disabled={!canEdit || entry === 0}
        onClick={onUndo}
        className={`absolute ${isLeft ? 'bottom-4 right-4' : 'bottom-4 left-4'} w-16 h-16 rounded-full text-3xl font-bold text-white shadow-lg z-10 ${
          canEdit && entry > 0
            ? 'bg-white/15 hover:bg-white/25 active:bg-white/35'
            : 'bg-white/5 opacity-30'
        }`}
        aria-label="Отменить очко"
      >
        −
      </button>
    </div>
  )
}

// ── HistoryPanel ──────────────────────────────────────────────────────────────

function HistoryPanel({ state, elapsedSec, onClose }) {
  const matches = state.matches || []
  const [winsA, winsB] = state.wins ?? [0, 0]
  const durations = matches
    .map((m) => (m.ended_at && m.started_at) ? (Date.parse(m.ended_at) - Date.parse(m.started_at)) / 1000 : null)
    .filter((x) => x != null)
  const avgMatchSec = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null
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
      className="absolute right-0 top-0 bottom-0 w-80 max-w-[88vw] bg-zinc-900/95 backdrop-blur-md border-l border-zinc-700 z-30 overflow-y-auto"
      style={{ paddingTop: 'calc(env(safe-area-inset-top) + 12px)' }}
    >
      <div className="flex items-center justify-between px-4 pb-3 border-b border-zinc-800">
        <h3 className="text-white font-semibold">Сводка сессии</h3>
        <button onClick={onClose} className="text-zinc-400 hover:text-white text-3xl leading-none px-2">×</button>
      </div>

      <div className="px-4 py-3 border-b border-zinc-800 space-y-2 text-sm">
        <div className="flex justify-between"><span className="text-zinc-400">Длительность</span><span className="text-white font-mono">{fmtClock(elapsedSec)}</span></div>
        <div className="flex justify-between"><span className="text-zinc-400">Партий</span><span className="text-white font-mono">{matches.length}</span></div>
        <div className="flex justify-between"><span className="text-zinc-400">Счёт</span><span className="text-white font-mono tabular-nums">{winsA} : {winsB}</span></div>
        <div className="flex justify-between"><span className="text-zinc-400">Среднее партии</span><span className="text-white font-mono">{fmtDuration(avgMatchSec)}</span></div>
        <div className="flex justify-between"><span className="text-zinc-400">Средняя разница</span><span className="text-white font-mono">{avgDiff != null ? avgDiff.toFixed(1) : '—'}</span></div>
        {state.set_size > 0 && (
          <div className="flex justify-between"><span className="text-zinc-400">Сетов сыграно</span><span className="text-white font-mono">{computeSetsCompleted(state)}</span></div>
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
            const dur = (m.ended_at && m.started_at) ? (Date.parse(m.ended_at) - Date.parse(m.started_at)) / 1000 : null
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

  // ВАЖНО: основной флоу — локальный entry (счёт идущей партии). На submit шлём finish_party.
  const [entryA, setEntryA] = useState(0)
  const [entryB, setEntryB] = useState(0)
  const [lastScored, setLastScored] = useState([])  // история «кто получил очко» для undo

  const [muted, setMuted] = useState(() => {
    try { return window.localStorage?.getItem(MUTE_KEY) === '1' } catch { return false }
  })

  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const reconnectAttempt = useRef(0)
  const closedRef = useRef(false)
  const initializedRef = useRef(false)
  const prevMatchesCount = useRef(0)
  const prevSetsAnnounced = useRef(0)
  const mutedRef = useRef(muted)
  const { confirm, element: confirmEl } = useConfirmDialog()

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
    // После записи партии — сбрасываем локальный entry
    if (newMatches > prevMatchesCount.current) {
      setEntryA(0); setEntryB(0); setLastScored([])
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

  const handleTap = (side) => {
    if (!canEdit || isClosed) return
    try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('medium') } catch { /* noop */ }
    if (side === 'a') setEntryA((n) => n + 1)
    else setEntryB((n) => n + 1)
    setLastScored((arr) => [...arr, side])
  }

  const handleUndo = (side) => {
    if (!canEdit || isClosed) return
    try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('light') } catch { /* noop */ }
    if (side === 'a' && entryA > 0) {
      setEntryA((n) => n - 1)
    } else if (side === 'b' && entryB > 0) {
      setEntryB((n) => n - 1)
    }
    setLastScored((arr) => arr.filter((s, i) => !(i === arr.length - 1 && s === side)).length === arr.length
      ? arr.slice(0, -1)  // если последний — другой бок, просто срежем хвост на всякий
      : arr.filter((s, i, all) => !(i === all.length - 1 && s === side)))
  }

  const canSubmit = isValidPartyScore(entryA, entryB) && canEdit && !isClosed

  const handleSubmit = () => {
    if (!canSubmit) return
    try { window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred?.('success') } catch { /* noop */ }
    send({ type: 'finish_party', score_a: entryA, score_b: entryB })
    // entry сбросится когда придёт state с новой партией
  }

  const handleClose = async () => {
    if (!canEdit || isClosed) return
    const ok = await confirm({
      title: 'Закрыть сессию?',
      description: 'Сессия закроется и попадёт в историю.',
      confirmLabel: 'Закрыть',
      destructive: true,
    })
    if (!ok) return
    send({ type: 'close' })
  }

  const handleServeToggle = async () => {
    if (!canEdit || isClosed || !state?.id) return
    try { await tennisApi.toggleServe(state.id) }
    catch (e) {
      setErrorBanner(e.message || 'Не получилось')
      window.setTimeout(() => setErrorBanner(null), 2500)
    }
  }

  const toggleMute = () => {
    setMuted((prev) => {
      const next = !prev
      try { window.localStorage?.setItem(MUTE_KEY, next ? '1' : '0') } catch { /* noop */ }
      if (next) { try { window.speechSynthesis?.cancel() } catch { /* noop */ } }
      return next
    })
  }

  if (!state) {
    return (
      <div className="fixed inset-0 z-50 bg-black flex items-center justify-center">
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
  const setSize = state.set_size ?? 0
  const setsCompleted = computeSetsCompleted(state)
  const partyIndex = state.matches?.length ?? 0
  const currentPartyNumber = isClosed ? partyIndex : partyIndex + 1

  // Подача: для отображения вычисляем на основе локального entry
  const currentServer = serverForNextPoint(state.first_server || 'a', entryA, entryB)

  const submitLabel = canSubmit
    ? `✓ Записать партию ${entryA}:${entryB}`
    : entryA === 0 && entryB === 0
      ? 'Тапай по цифре чтобы добавить очки'
      : `${entryA}:${entryB} — нужно 11+ при разнице ≥2`

  return (
    <div className="fixed inset-0 z-50 bg-black overflow-hidden flex flex-col">
      {/* Top bar */}
      <div
        className="shrink-0 flex items-center justify-between gap-2 px-3 bg-black/80 backdrop-blur-sm border-b border-zinc-800 text-white text-sm font-mono"
        style={{ paddingTop: 'calc(env(safe-area-inset-top) + 6px)', paddingBottom: '6px' }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <button
            onClick={() => setHistoryOpen(true)}
            className="hover:bg-white/10 rounded px-2 py-1 flex items-center gap-1.5"
            title="Сводка"
          >
            <span>⏱ {fmtClock(elapsedSec)}</span>
          </button>
          <span className="text-zinc-400 text-xs hidden sm:inline">партия {currentPartyNumber}</span>
          {setSize > 0 && (
            <span className="text-zinc-400 text-xs hidden sm:inline">сет {setsCompleted + 1}</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {!isClosed && canEdit && (
            <button
              onClick={handleServeToggle}
              className="text-xs px-2 py-1 rounded hover:bg-white/10"
              title="Переключить первую подачу"
            >
              ↻🏓
            </button>
          )}
          <button
            onClick={toggleMute}
            className="text-base leading-none px-2 py-1 rounded hover:bg-white/10"
            aria-label={muted ? 'Включить озвучку' : 'Выключить'}
          >
            {muted ? '🔇' : '🔊'}
          </button>
          {status === 'reconnecting' && <span className="text-amber-300 text-xs animate-pulse">·реконн</span>}
          {isClosed && <span className="text-zinc-300 text-xs">·закрыта{closeReason === 'timeout' ? ' (таймаут)' : ''}</span>}
        </div>
      </div>

      {/* Player halves */}
      <div className="flex-1 flex flex-col landscape:flex-row min-h-0">
        <PlayerHalf
          name={nameA}
          isYou={youSideA}
          entry={entryA}
          partyWins={winsA}
          isServing={currentServer === 'a'}
          color="from-rose-700/40 to-rose-950"
          accentText="text-rose-200"
          canEdit={canEdit}
          onTap={() => handleTap('a')}
          onUndo={() => handleUndo('a')}
          isLeft
        />
        <PlayerHalf
          name={nameB}
          isYou={youSideB}
          entry={entryB}
          partyWins={winsB}
          isServing={currentServer === 'b'}
          color="from-sky-700/40 to-sky-950"
          accentText="text-sky-200"
          canEdit={canEdit}
          onTap={() => handleTap('b')}
          onUndo={() => handleUndo('b')}
        />
      </div>

      {/* Submit + close — большая кнопка снизу */}
      <div
        className="shrink-0 bg-black/80 backdrop-blur-sm border-t border-zinc-800 px-3 pt-3"
        style={{ paddingBottom: 'calc(env(safe-area-inset-bottom) + 12px)' }}
      >
        {!isClosed && (
          <motion.button
            whileTap={canSubmit ? { scale: 0.97 } : {}}
            onClick={handleSubmit}
            disabled={!canSubmit}
            className={`w-full rounded-2xl py-5 text-lg font-bold transition-colors ${
              canSubmit
                ? 'bg-gradient-to-br from-emerald-500 to-emerald-700 text-white shadow-lg'
                : 'bg-zinc-800 text-zinc-500'
            }`}
          >
            {submitLabel}
          </motion.button>
        )}
        <div className="flex items-center justify-between gap-2 mt-2">
          <div className="text-zinc-400 text-xs flex-1 truncate">
            🏓 Подаёт {currentServer === 'a' ? nameA : nameB}
            {(entryA > 0 || entryB > 0) && <span className="text-zinc-500"> · текущая партия</span>}
          </div>
          {!isClosed && canEdit && (
            <button
              onClick={handleClose}
              className="text-zinc-400 hover:text-white text-xs px-3 py-1.5 rounded-full border border-zinc-700"
            >
              Закрыть сессию
            </button>
          )}
          {isClosed && onBackToLobby && (
            <button
              onClick={onBackToLobby}
              className="text-zinc-200 hover:text-white text-xs px-4 py-2 rounded-full bg-zinc-800 border border-zinc-700"
            >
              В лобби
            </button>
          )}
        </div>
      </div>

      {/* Error toast */}
      <AnimatePresence>
        {errorBanner && (
          <motion.div
            initial={{ y: -20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -20, opacity: 0 }}
            className="absolute top-16 left-1/2 -translate-x-1/2 bg-red-600 text-white px-4 py-2 rounded-lg text-sm shadow-lg z-30"
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

      {confirmEl}
    </div>
  )
}
