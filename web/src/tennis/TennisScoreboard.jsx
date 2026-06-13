import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import WebApp from '@twa-dev/sdk'
import { useAuth } from '../context/useAuth'
import { tennisApi } from './api'
import { useConfirmDialog } from './ConfirmDialog'
import { EditMatchSheet } from './Modals'
import { sportMeta } from './sports'

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

function buildMatchAnnouncement(match, state) {
  const winnerName = match.winner === 'a' ? state.player_a_name : state.player_b_name
  if (match.score_a == null || match.score_b == null) {
    return `Партия! Победил ${winnerName}.`
  }
  const winnerScore = match.winner === 'a' ? match.score_a : match.score_b
  const loserScore = match.winner === 'a' ? match.score_b : match.score_a
  return `Партия! Победил ${winnerName}. Счёт ${winnerScore} на ${loserScore}.`
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
async function speakServer(text, { noCancel = false } = {}) {
  let blob = ttsCache.get(text)
  if (!blob) {
    blob = await tennisApi.tts(text)
    if (!blob) return false
    if (ttsCache.size > 64) ttsCache.delete(ttsCache.keys().next().value)
    ttsCache.set(text, blob)
  }
  if (!noCancel) {
    try { ttsAudioRef.current?.pause?.() } catch { /* noop */ }
  }
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  ttsAudioRef.current = audio
  audio.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true })
  await audio.play().catch(() => {})
  return true
}
async function speak(text, { waitForCurrent = false } = {}) {
  if (waitForCurrent) {
    const current = ttsAudioRef.current
    if (current && !current.paused && !current.ended) {
      await new Promise((resolve) => {
        current.addEventListener('ended', resolve, { once: true })
        current.addEventListener('error', resolve, { once: true })
        window.setTimeout(resolve, 8000) // safety cap
      })
    }
  }
  try {
    const ok = await speakServer(text, { noCancel: waitForCurrent })
    if (ok) return
  } catch { /* fall through */ }
  speakBrowser(text)
}

// ── Визуальные примитивы: мяч, корт, счёт ─────────────────────────────────────

// Чёткий SVG-мяч (вместо эмодзи) — фирменный «теннисный» жёлто-лаймовый с швами.
function TennisBall({ size = 28, className = '', style }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} style={style} aria-hidden>
      <circle cx="32" cy="32" r="30" fill="#cdfa3f" />
      <circle cx="32" cy="32" r="30" fill="none" stroke="#9bd61f" strokeWidth="2" />
      <path d="M11 13 Q31 32 11 51" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinecap="round" opacity="0.95" />
      <path d="M53 13 Q33 32 53 51" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinecap="round" opacity="0.95" />
      <ellipse cx="23" cy="20" rx="9" ry="6" fill="#fff" opacity="0.18" />
    </svg>
  )
}

// Подсветка линий корта за счётом — еле заметная.
function CourtLines() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden flex items-center justify-center">
      <div className="absolute inset-y-10 left-1/2 -translate-x-1/2 border-l-2 border-dashed border-white/[0.05]" />
      <div className="absolute left-8 right-8 top-[22%] h-px bg-white/[0.05]" />
      <div className="absolute left-8 right-8 bottom-[22%] h-px bg-white/[0.05]" />
      <div className="absolute left-1/2 top-[22%] bottom-[22%] -translate-x-1/2 w-[55%] border-x border-white/[0.04]" />
    </div>
  )
}

// Имя игрока с «мячом подачи» на его стороне.
function ServeName({ name, side, isServer }) {
  const colorCls = side === 'a' ? 'text-rose-300' : 'text-sky-300'
  const ball = isServer && (
    <motion.span
      initial={{ scale: 0, rotate: -90 }}
      animate={{ scale: 1, rotate: 0 }}
      transition={{ type: 'spring', stiffness: 360, damping: 18 }}
      className="inline-flex drop-shadow-[0_0_8px_rgba(205,250,63,0.6)]"
    >
      <TennisBall size={16} />
    </motion.span>
  )
  return (
    <div className="flex items-center gap-1.5 min-w-0 max-w-[42vw]">
      {side === 'a' && ball}
      <span className={`${colorCls} text-sm font-semibold uppercase tracking-wider truncate`}>{name}</span>
      {side === 'b' && ball}
    </div>
  )
}

// Большое «прыгающее» число очка — приземляется как мяч при каждом изменении.
function BounceNumber({ value, side, active, big = true }) {
  const colorCls = side === 'a'
    ? (active ? 'text-rose-400' : 'text-rose-300/40')
    : (active ? 'text-sky-400' : 'text-sky-300/40')
  const glow = active
    ? side === 'a'
      ? { textShadow: '0 0 32px rgba(244,63,94,0.45)' }
      : { textShadow: '0 0 32px rgba(56,189,248,0.45)' }
    : undefined
  return (
    <motion.span
      key={`${side}-${value}`}
      initial={{ y: -34, scale: 1.35, opacity: 0.5 }}
      animate={{ y: 0, scale: 1, opacity: 1 }}
      transition={{ type: 'spring', stiffness: 520, damping: 17 }}
      className={`font-black tabular-nums leading-none ${colorCls}`}
      style={{ fontSize: big ? 'clamp(76px, 23vw, 184px)' : 'clamp(40px, 12vw, 90px)', ...glow }}
    >
      {value}
    </motion.span>
  )
}

// Маленькая плашка счёта по партиям; пульсирует, когда партия завершилась.
function WinsPill({ winsA, winsB, label, celebrate }) {
  return (
    <motion.div
      animate={celebrate
        ? { scale: [1, 1.55, 1.18], y: [0, -4, 0] }
        : { scale: 1, y: 0 }}
      transition={{ duration: celebrate ? 0.9 : 0.3, ease: 'easeOut' }}
      className={`mt-6 inline-flex items-center gap-2.5 rounded-full px-4 py-1.5 border transition-colors ${
        celebrate
          ? 'border-lime-400/60 bg-lime-400/10 shadow-[0_0_28px_rgba(205,250,63,0.45)]'
          : 'border-zinc-700/80 bg-zinc-900/50'
      }`}
    >
      <span className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</span>
      <span className="text-rose-300 font-black tabular-nums text-lg leading-none">{winsA}</span>
      <span className="text-zinc-600 text-sm">:</span>
      <span className="text-sky-300 font-black tabular-nums text-lg leading-none">{winsB}</span>
    </motion.div>
  )
}

// Загрузка: прыгающий, вращающийся мяч с тенью.
function BouncingBallLoader({ label }) {
  const dur = 0.72
  return (
    <div className="flex flex-col items-center gap-7">
      <div className="relative h-28 w-20">
        <motion.div
          className="absolute left-1/2 top-0 -translate-x-1/2"
          animate={{ y: [0, 72, 0] }}
          transition={{ duration: dur, repeat: Infinity, ease: [0.36, 0, 0.66, 1] }}
        >
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: dur * 2, repeat: Infinity, ease: 'linear' }}
          >
            <TennisBall size={48} className="drop-shadow-[0_0_14px_rgba(205,250,63,0.4)]" />
          </motion.div>
        </motion.div>
        <motion.div
          className="absolute bottom-0 left-1/2 -translate-x-1/2 h-2 w-12 rounded-[100%] bg-lime-400/40 blur-[2px]"
          animate={{ scaleX: [1, 0.45, 1], opacity: [0.5, 0.18, 0.5] }}
          transition={{ duration: dur, repeat: Infinity, ease: [0.36, 0, 0.66, 1] }}
        />
      </div>
      <div className="text-zinc-400 text-sm tracking-wide">{label}</div>
    </div>
  )
}

// ── FinishPartySheet: ввод итогового счёта ────────────────────────────────────

function FinishPartySheet({ state, defaultWinnerSide, onSubmit, onClose }) {
  const [winnerSide, setWinnerSide] = useState(defaultWinnerSide || 'a')
  const [loserScore, setLoserScore] = useState(7)
  const winnerScore = loserScore < 10 ? 11 : loserScore + 2

  const scoreA = winnerSide === 'a' ? winnerScore : loserScore
  const scoreB = winnerSide === 'b' ? winnerScore : loserScore

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[55] bg-black/70 backdrop-blur-sm flex items-end justify-center"
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
          <h2 className="text-white font-bold text-lg">Записать партию</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-white text-3xl leading-none px-2">×</button>
        </div>
        <div className="px-4 py-3">
          <div className="text-xs uppercase tracking-wider text-zinc-500 mb-2">Победил</div>
          <div className="grid grid-cols-2 gap-2 mb-5">
            <button
              onClick={() => setWinnerSide('a')}
              className={`py-4 rounded-xl text-base font-bold ${
                winnerSide === 'a' ? 'bg-rose-600 text-white' : 'bg-zinc-800 text-zinc-300'
              }`}
            >
              {state.player_a_name}
            </button>
            <button
              onClick={() => setWinnerSide('b')}
              className={`py-4 rounded-xl text-base font-bold ${
                winnerSide === 'b' ? 'bg-sky-600 text-white' : 'bg-zinc-800 text-zinc-300'
              }`}
            >
              {state.player_b_name}
            </button>
          </div>

          <div className="flex items-center justify-center mb-4 gap-3">
            <span className="text-5xl font-black text-white tabular-nums">{winnerScore}</span>
            <span className="text-3xl text-zinc-500">:</span>
            <span className="text-5xl font-black text-white tabular-nums">{loserScore}</span>
          </div>

          <div className="text-xs uppercase tracking-wider text-zinc-500 mb-2 text-center">
            Очков у проигравшего
          </div>
          <div className="grid grid-cols-5 gap-2 mb-3">
            {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
              <button
                key={n}
                onClick={() => setLoserScore(n)}
                className={`py-4 rounded-xl text-2xl font-bold ${
                  loserScore === n ? 'bg-zinc-500 text-white' : 'bg-zinc-800 text-zinc-300'
                }`}
              >
                {n}
              </button>
            ))}
          </div>
          {/* Deuce — инкрементер */}
          <div className="flex items-center gap-2 mb-4">
            <button
              onClick={() => setLoserScore((n) => Math.max(0, n - 1))}
              className="w-14 h-14 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-3xl font-bold"
            >−</button>
            <div className="flex-1 bg-zinc-800 rounded-xl py-3 text-center">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">deuce / любое число</div>
              <div className="text-3xl font-bold text-white tabular-nums">{loserScore}</div>
            </div>
            <button
              onClick={() => setLoserScore((n) => Math.min(50, n + 1))}
              className="w-14 h-14 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-3xl font-bold"
            >+</button>
          </div>

          <button
            onClick={() => onSubmit(scoreA, scoreB)}
            className="w-full bg-gradient-to-br from-emerald-500 to-emerald-700 text-white py-5 rounded-2xl font-bold text-xl shadow-lg active:scale-[0.98] transition-transform"
          >
            ✓ Записать {scoreA}:{scoreB}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

// ── HistoryPanel ──────────────────────────────────────────────────────────────

function HistoryPanel({ state, elapsedSec, onClose, onEditMatch }) {
  const matches = state.matches || []
  const [winsA, winsB] = state.wins ?? [0, 0]
  const canEditMatches = state.can_edit_matches !== false  // по дефолту в live-state считаем что можно
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
        <h3 className="text-white font-bold">Сводка</h3>
        <button onClick={onClose} className="text-zinc-400 hover:text-white text-3xl leading-none px-2">×</button>
      </div>
      <div className="px-4 py-3 border-b border-zinc-800 space-y-2 text-sm">
        <div className="flex justify-between"><span className="text-zinc-400">Длительность</span><span className="text-white font-mono">{fmtClock(elapsedSec)}</span></div>
        <div className="flex justify-between"><span className="text-zinc-400">Партий</span><span className="text-white font-mono">{matches.length}</span></div>
        <div className="flex justify-between"><span className="text-zinc-400">Счёт</span><span className="text-white font-mono tabular-nums">{winsA} : {winsB}</span></div>
        <div className="flex justify-between"><span className="text-zinc-400">Среднее партии</span><span className="text-white font-mono">{fmtDuration(avgMatchSec)}</span></div>
        <div className="flex justify-between"><span className="text-zinc-400">Средняя разница</span><span className="text-white font-mono">{avgDiff != null ? avgDiff.toFixed(1) : '—'}</span></div>
        {state.serve_streak > 0 && (
          <div className="flex justify-between"><span className="text-zinc-400">Партий за подачу</span><span className="text-white font-mono">{state.serve_streak}</span></div>
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
              <li key={i} className="px-4 py-2.5 flex items-center justify-between gap-2">
                <span className="text-zinc-500 w-7">#{i + 1}</span>
                <span className="text-zinc-100 font-mono w-14">{score}</span>
                <span className="text-zinc-400 text-xs truncate flex-1">{winnerName}</span>
                {dur != null && <span className="text-zinc-500 text-xs font-mono">{fmtDuration(dur)}</span>}
                {canEditMatches && m.score_a != null && (
                  <button
                    onClick={() => onEditMatch(i)}
                    className="text-amber-300 hover:text-amber-200 text-base px-1"
                    title="Поправить счёт"
                  >
                    ✏️
                  </button>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </motion.div>
  )
}

// ── PadelHero: очки матча — герой, сеты/геймы — мелким ────────────────────────

function PadelMiniRow({ label, a, b }) {
  return (
    <div className="flex items-center justify-center gap-2.5 text-zinc-400">
      <span className="tabular-nums font-bold text-base w-6 text-right">{a}</span>
      <span className="text-zinc-600 text-[10px] w-12 text-center uppercase tracking-wider">{label}</span>
      <span className="tabular-nums font-bold text-base w-6 text-left">{b}</span>
    </div>
  )
}

function PadelHero({ padel, currentServer }) {
  const [setsA, setsB] = padel.sets ?? [0, 0]
  const [gamesA, gamesB] = padel.games ?? [0, 0]
  const [ptA, ptB] = padel.points ?? ['0', '0']
  const completed = padel.completed_sets ?? []

  return (
    <div className="relative z-10 flex flex-col items-center gap-1">
      {completed.length > 0 && (
        <div className="text-zinc-500 text-xs font-mono mb-0.5">
          {completed.map((s, i) => (
            <span key={i} className="mx-1">{s[0]}-{s[1]}</span>
          ))}
        </div>
      )}
      <PadelMiniRow label="сеты" a={setsA} b={setsB} />
      <PadelMiniRow label="геймы" a={gamesA} b={gamesB} />
      <div className="flex items-end justify-center gap-5 mt-1">
        <BounceNumber value={ptA} side="a" active={currentServer !== 'b'} />
        <span className="text-zinc-700 font-light pb-3" style={{ fontSize: 'clamp(34px, 9vw, 64px)' }}>:</span>
        <BounceNumber value={ptB} side="b" active={currentServer !== 'a'} />
      </div>
      <span className="text-[10px] uppercase tracking-wider text-zinc-500 mt-1">
        {padel.in_tiebreak ? 'тай-брейк' : 'очки'}
      </span>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function TennisScoreboard({ onBackToLobby }) {
  const { initData } = useAuth()
  const [state, setState] = useState(null)
  const [status, setStatus] = useState('connecting')
  const [closeReason, setCloseReason] = useState('')
  const [errorBanner, setErrorBanner] = useState(null)
  const [now, setNow] = useState(Date.now())
  const [historyOpen, setHistoryOpen] = useState(false)
  const [finishOpen, setFinishOpen] = useState(false)
  const [editIdx, setEditIdx] = useState(null)
  const [winsCelebrate, setWinsCelebrate] = useState(false)
  const [muted, setMuted] = useState(() => {
    try { return window.localStorage?.getItem(MUTE_KEY) === '1' } catch { return false }
  })
  const { confirm, element: confirmEl } = useConfirmDialog()

  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const reconnectAttempt = useRef(0)
  const closedRef = useRef(false)
  const initializedRef = useRef(false)
  const prevMatchesCount = useRef(0)
  const prevCommentarySeq = useRef(0)
  const prevWinsTotalRef = useRef(null)
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
    const seq = incoming.last_commentary_seq ?? 0
    if (initializedRef.current && !mutedRef.current) {
      const newPartyArrived = newMatches > prevMatchesCount.current
      // AI-комментарий пришёл позже, когда счёт уже был обновлён
      const lateCommentary = seq > prevCommentarySeq.current && newMatches === prevMatchesCount.current

      if (newPartyArrived) {
        // Стандартная озвучка: счёт партии, сразу
        const last = incoming.matches[newMatches - 1]
        const text = last ? buildMatchAnnouncement(last, incoming) : null
        if (text) speak(text)
      }
      if (lateCommentary && incoming.last_commentary) {
        // Комментарий: ждём пока закончится текущая озвучка, потом воспроизводим
        const text = incoming.last_commentary
        ;(async () => { await speak(text, { waitForCurrent: true }) })()
      }
      if (options.sessionEnd) {
        const text = buildSessionEndAnnouncement(incoming)
        window.setTimeout(() => speak(text), newPartyArrived ? 2500 : 0)
      }
    }
    initializedRef.current = true
    prevMatchesCount.current = newMatches
    prevCommentarySeq.current = seq
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

  // Когда счёт по партиям меняется (партия завершилась) — кратко «подсвечиваем»
  // и увеличиваем плашку партий, чтобы итог было видно.
  const winsTotal = (state?.wins?.[0] ?? 0) + (state?.wins?.[1] ?? 0)
  useEffect(() => {
    const prev = prevWinsTotalRef.current
    prevWinsTotalRef.current = winsTotal
    if (prev != null && winsTotal > prev) {
      setWinsCelebrate(true)
      const t = window.setTimeout(() => setWinsCelebrate(false), 2200)
      return () => window.clearTimeout(t)
    }
  }, [winsTotal])

  const canEdit = Boolean(state?.permissions?.can_edit) && status === 'connected'
  const isClosed = status === 'closed' || Boolean(state?.ended_at)

  const handleSubmit = (a, b) => {
    if (!isValidPartyScore(a, b)) {
      setErrorBanner('Невалидный счёт')
      window.setTimeout(() => setErrorBanner(null), 2500)
      return
    }
    try { window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred?.('success') } catch { /* noop */ }
    send({ type: 'finish_party', score_a: a, score_b: b })
    setFinishOpen(false)
  }

  const handlePoint = (side) => {
    if (!canEdit || isClosed) return
    try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('medium') } catch { /* noop */ }
    send({ type: 'point', side })
  }

  const handleUndoPoint = () => {
    if (!canEdit || isClosed) return
    try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('light') } catch { /* noop */ }
    send({ type: 'undo_point' })
  }

  const handleEditSubmit = (a, b) => {
    if (editIdx == null) return
    send({ type: 'edit_match', idx: editIdx, score_a: a, score_b: b })
    setEditIdx(null)
  }

  const handleUndo = async () => {
    if (!canEdit || isClosed) return
    const ok = await confirm({
      title: 'Отменить последнюю партию?',
      description: 'Партия удалится из истории, подача вернётся обратно.',
      confirmLabel: 'Отменить',
      destructive: true,
    })
    if (!ok) return
    send({ type: 'undo' })
  }

  const handleClose = async () => {
    if (!canEdit || isClosed) return
    const ok = await confirm({
      title: 'Закрыть сессию?',
      description: 'Сессия попадёт в историю.',
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
      <div className="fixed inset-0 z-50 bg-gradient-to-b from-zinc-950 to-black flex items-center justify-center">
        <BouncingBallLoader label={status === 'reconnecting' ? 'Восстанавливаем связь…' : 'Подаём…'} />
      </div>
    )
  }

  const nameA = state.player_a_name || 'Игрок A'
  const nameB = state.player_b_name || 'Игрок B'
  const [winsA, winsB] = state.wins ?? [0, 0]
  const partyIndex = state.matches?.length ?? 0
  const currentPartyNumber = isClosed ? partyIndex : partyIndex + 1
  const firstServerName = state.first_server === 'a' ? nameA : nameB
  const sp = sportMeta(state.sport)
  const isPadel = state.sport === 'padel'
  const padel = state.padel
  const [curA, curB] = state.current_score ?? [0, 0]
  // Для падела «партия в процессе» определяется по journal'у очков, а не по сетам.
  const partyInProgress = isPadel
    ? (state.points_log?.length ?? 0) > 0
    : (curA > 0 || curB > 0)
  const currentServer = state.current_server

  return (
    <div className="fixed inset-0 z-50 bg-gradient-to-b from-zinc-950 to-black overflow-hidden flex flex-col">
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: 'radial-gradient(120% 60% at 50% 42%, rgba(205,250,63,0.07), transparent 60%)' }}
      />
      {/* Top bar */}
      <div
        className="shrink-0 flex items-center justify-between gap-2 px-3 bg-black/80 backdrop-blur-sm border-b border-zinc-800 text-white text-sm font-mono"
        style={{ paddingTop: 'calc(env(safe-area-inset-top) + 6px)', paddingBottom: '6px' }}
      >
        <button
          onClick={() => setHistoryOpen(true)}
          className="hover:bg-white/10 active:bg-white/20 rounded-lg px-2 py-1 flex items-center gap-1.5"
          title="Сводка"
        >
          <span>⏱ {fmtClock(elapsedSec)}</span>
        </button>
        <div className="flex items-center gap-1">
          {!isClosed && canEdit && !sp.winnerServes && (
            <button
              onClick={handleServeToggle}
              className="text-base px-2 py-1 rounded hover:bg-white/10"
              title="Переключить первую подачу"
            >↻{sp.emoji}</button>
          )}
          <button
            onClick={toggleMute}
            className="text-base leading-none px-2 py-1 rounded hover:bg-white/10"
          >
            {muted ? '🔇' : '🔊'}
          </button>
          {status === 'reconnecting' && <span className="text-amber-300 text-xs animate-pulse">·реконн</span>}
          {isClosed && <span className="text-zinc-300 text-xs">·закрыта{closeReason === 'timeout' ? ' (таймаут)' : ''}</span>}
        </div>
      </div>

      {/* Центр: крупно — счёт текущей партии, мелко — счёт по партиям */}
      <div className="flex-1 flex flex-col items-center justify-center px-6 min-h-0 relative">
        <CourtLines />

        {/* Имена + мяч подачи */}
        <div className="relative z-10 flex items-center justify-center gap-3 w-full max-w-md mb-3">
          <ServeName name={nameA} side="a" isServer={!isClosed && currentServer === 'a'} />
          <span className="text-zinc-600 text-[11px] font-semibold uppercase tracking-wider shrink-0">vs</span>
          <ServeName name={nameB} side="b" isServer={!isClosed && currentServer === 'b'} />
        </div>

        {/* Герой: либо очки текущей партии, либо (если закрыто) итог по партиям */}
        {isClosed ? (
          <div className="relative z-10 flex items-end justify-center gap-5">
            <BounceNumber value={winsA} side="a" active />
            <span className="text-zinc-700 font-light pb-3" style={{ fontSize: 'clamp(40px, 11vw, 80px)' }}>:</span>
            <BounceNumber value={winsB} side="b" active />
          </div>
        ) : isPadel && padel ? (
          <PadelHero padel={padel} currentServer={currentServer} />
        ) : (
          <div className="relative z-10 flex items-end justify-center gap-5">
            <BounceNumber value={curA} side="a" active={currentServer !== 'b'} />
            <span className="text-zinc-700 font-light pb-3" style={{ fontSize: 'clamp(40px, 11vw, 80px)' }}>:</span>
            <BounceNumber value={curB} side="b" active={currentServer !== 'a'} />
          </div>
        )}

        {/* Мелкий счёт по партиям; на финише плашка пульсирует и крупнеет */}
        {!isClosed && (
          <WinsPill winsA={winsA} winsB={winsB} celebrate={winsCelebrate} label={isPadel ? 'Сеты' : 'Партии'} />
        )}

        <div className="relative z-10 text-zinc-400 text-sm mt-5">
          {isPadel ? 'Матч' : 'Партия'} <span className="text-white font-semibold">{currentPartyNumber}</span>
        </div>
        {!isClosed && (
          <div className="relative z-10 text-zinc-500 text-xs mt-1.5">
            {sp.emoji} {sp.winnerServes ? 'подаёт' : 'первая подача —'} {firstServerName}
          </div>
        )}

        {state.last_commentary && (
          <motion.div
            key={state.last_commentary_seq}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="relative z-10 mt-4 text-zinc-300 text-sm max-w-md text-center italic px-4 leading-snug"
          >
            “{state.last_commentary}”
          </motion.div>
        )}
      </div>

      {/* Нижняя зона: главная кнопка + действия */}
      <div
        className="shrink-0 bg-black/80 backdrop-blur-sm border-t border-zinc-800 px-3 pt-3"
        style={{ paddingBottom: 'calc(env(safe-area-inset-bottom) + 12px)' }}
      >
        {/* Point-by-point: тап = очко. Две большие зоны под каждого игрока. */}
        {!isClosed && canEdit && (
          <div className="grid grid-cols-2 gap-2">
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={() => handlePoint('a')}
              className="relative overflow-hidden bg-gradient-to-br from-rose-600 to-rose-800 text-white py-6 rounded-2xl font-bold shadow-lg flex flex-col items-center ring-1 ring-rose-400/30"
            >
              <TennisBall size={56} className="absolute -right-3 -top-3 opacity-15 rotate-12" />
              <span className="relative text-3xl leading-none">+1</span>
              <span className="relative text-xs opacity-80 mt-1 truncate max-w-[90%]">{nameA}</span>
            </motion.button>
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={() => handlePoint('b')}
              className="relative overflow-hidden bg-gradient-to-br from-sky-600 to-sky-800 text-white py-6 rounded-2xl font-bold shadow-lg flex flex-col items-center ring-1 ring-sky-400/30"
            >
              <TennisBall size={56} className="absolute -left-3 -top-3 opacity-15 -rotate-12" />
              <span className="relative text-3xl leading-none">+1</span>
              <span className="relative text-xs opacity-80 mt-1 truncate max-w-[90%]">{nameB}</span>
            </motion.button>
          </div>
        )}
        <div className="flex items-center justify-between gap-2 mt-2 flex-wrap">
          {!isClosed && canEdit && partyInProgress && (
            <button
              onClick={handleUndoPoint}
              className="text-zinc-400 hover:text-white text-xs px-3 py-1.5 rounded-full border border-zinc-700"
            >
              ↩ убрать очко
            </button>
          )}
          {!isClosed && canEdit && !isPadel && (
            <button
              onClick={() => setFinishOpen(true)}
              className="text-zinc-400 hover:text-white text-xs px-3 py-1.5 rounded-full border border-zinc-700"
            >
              ✎ счёт вручную
            </button>
          )}
          {!isClosed && canEdit && partyIndex > 0 && (
            <button
              onClick={handleUndo}
              className="text-zinc-400 hover:text-white text-xs px-3 py-1.5 rounded-full border border-zinc-700"
            >
              ↶ отменить партию
            </button>
          )}
          <div className="flex-1" />
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
          <HistoryPanel
            state={state}
            elapsedSec={elapsedSec}
            onClose={() => setHistoryOpen(false)}
            onEditMatch={(i) => { setHistoryOpen(false); setEditIdx(i) }}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {finishOpen && (
          <FinishPartySheet
            state={state}
            onSubmit={handleSubmit}
            onClose={() => setFinishOpen(false)}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {editIdx != null && state.matches?.[editIdx] && (
          <EditMatchSheet
            open
            nameA={nameA}
            nameB={nameB}
            initialScoreA={state.matches[editIdx].score_a}
            initialScoreB={state.matches[editIdx].score_b}
            onSave={handleEditSubmit}
            onClose={() => setEditIdx(null)}
          />
        )}
      </AnimatePresence>

      {confirmEl}
    </div>
  )
}
