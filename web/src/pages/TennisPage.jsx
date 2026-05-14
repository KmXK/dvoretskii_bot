import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useAuth } from '../context/useAuth'

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000]
const SHORT_GAP_MS = 800

function fmtClock(seconds) {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  const mm = String(m).padStart(2, '0')
  const sec = String(ss).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${sec}` : `${mm}:${sec}`
}

function ScorePicker({ side, onPick, onSkip, onClose, opponentName }) {
  const QUICK = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
  return (
    <motion.div
      initial={{ y: 200, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      exit={{ y: 200, opacity: 0 }}
      transition={{ type: 'spring', damping: 22, stiffness: 280 }}
      className="absolute bottom-0 left-0 right-0 bg-zinc-900 border-t border-zinc-700 rounded-t-2xl p-5 shadow-2xl"
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-zinc-400 text-xs uppercase tracking-wider">Победил {side === 'a' ? 'A' : 'B'}</p>
          <p className="text-white font-semibold text-lg">Сколько очков у {opponentName}?</p>
        </div>
        <button
          onClick={onClose}
          className="text-zinc-500 hover:text-zinc-300 text-2xl leading-none px-2"
          aria-label="Закрыть"
        >
          ×
        </button>
      </div>
      <div className="grid grid-cols-5 gap-2 mb-3">
        {QUICK.map((n) => (
          <motion.button
            key={n}
            whileTap={{ scale: 0.9 }}
            onClick={() => onPick(n)}
            className="bg-zinc-800 hover:bg-zinc-700 active:bg-zinc-600 text-white font-bold text-2xl py-4 rounded-xl"
          >
            {n}
          </motion.button>
        ))}
      </div>
      <button
        onClick={onSkip}
        className="w-full bg-zinc-800/60 hover:bg-zinc-800 text-zinc-300 py-3 rounded-xl font-medium"
      >
        Пропустить (не вводить счёт)
      </button>
    </motion.div>
  )
}

function PlayerPanel({ label, wins, color, accentText, canEdit, onPlus, onMinus, isLeft }) {
  return (
    <div className={`flex-1 flex flex-col items-center justify-center bg-gradient-to-br ${color} relative ${isLeft ? '' : ''}`}>
      <div className={`absolute ${isLeft ? 'top-3 left-3' : 'top-3 right-3'} text-xs uppercase tracking-wider ${accentText} opacity-70`}>
        {label}
      </div>
      <motion.div
        key={wins}
        initial={{ scale: 0.7, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', damping: 14, stiffness: 220 }}
        className="text-white font-black tabular-nums leading-none"
        style={{ fontSize: 'clamp(80px, 22vw, 200px)' }}
      >
        {wins}
      </motion.div>
      <div className="flex gap-3 mt-6">
        <motion.button
          whileTap={canEdit ? { scale: 0.85 } : {}}
          disabled={!canEdit}
          onClick={onPlus}
          className={`w-20 h-20 rounded-full text-4xl font-bold text-white shadow-lg ${
            canEdit ? 'bg-white/20 hover:bg-white/30 active:bg-white/40' : 'bg-white/5 opacity-40'
          }`}
          aria-label="Добавить победу"
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

export default function TennisPage() {
  const { userId, initData } = useAuth()
  const [state, setState] = useState(null)        // server-pushed session state
  const [status, setStatus] = useState('connecting')  // connecting | connected | reconnecting | no_active | closed
  const [closeReason, setCloseReason] = useState('')
  const [errorBanner, setErrorBanner] = useState(null)
  const [picker, setPicker] = useState(null)      // {side: 'a'|'b'}
  const [now, setNow] = useState(Date.now())

  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const reconnectAttempt = useRef(0)
  const lastActivityTap = useRef(0)
  const closedRef = useRef(false)

  const send = useCallback((msg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
      return true
    }
    return false
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
          setState(data.state)
          setStatus('connected')
          break
        case 'closed':
          setState(data.state)
          setCloseReason(data.reason || '')
          setStatus('closed')
          break
        case 'no_active':
          setStatus('no_active')
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
  }, [initData])

  useEffect(() => {
    closedRef.current = false
    connect()
    return () => {
      closedRef.current = true
      if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current)
      try { wsRef.current?.close() } catch { /* noop */ }
    }
  }, [connect])

  // Force reconnect when tab regains focus (phone unlock case)
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

  // Local clock tick (1 Hz)
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
  const wins = state?.wins ?? [0, 0]
  const isClosed = status === 'closed' || Boolean(state?.ended_at)

  const handlePlus = (side) => {
    if (!canEdit || isClosed) return
    const t = Date.now()
    if (t - lastActivityTap.current < SHORT_GAP_MS) return // дабл-тап защита
    lastActivityTap.current = t
    try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('medium') } catch { /* noop */ }
    setPicker({ side })
  }

  const handleMinus = (side) => {
    if (!canEdit || isClosed) return
    const last = state?.matches?.[state.matches.length - 1]
    if (!last || last.winner !== side) {
      setErrorBanner('Последняя партия была не за этого игрока')
      window.setTimeout(() => setErrorBanner(null), 2500)
      return
    }
    try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('light') } catch { /* noop */ }
    send({ type: 'undo' })
  }

  const submitScore = (loserScore, withScore = true) => {
    if (!picker) return
    const { side } = picker
    if (withScore) {
      const winnerScore = 11
      send({
        type: 'win',
        side,
        score_a: side === 'a' ? winnerScore : loserScore,
        score_b: side === 'b' ? winnerScore : loserScore,
      })
    } else {
      send({ type: 'win', side, score_a: null, score_b: null })
    }
    setPicker(null)
  }

  const handleClose = () => {
    if (!canEdit || isClosed) return
    if (!window.confirm('Закрыть сессию?')) return
    send({ type: 'close' })
  }

  // ── Render ───────────────────────────────────────────────────────────────

  if (status === 'no_active') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-6 text-center">
        <div className="text-6xl mb-4">🏓</div>
        <h2 className="text-white text-xl font-bold mb-2">Нет активной сессии</h2>
        <p className="text-zinc-400 max-w-xs">
          Запусти live-сессию в чате командой <code className="text-zinc-200">/tennis start</code> — табло откроется здесь.
        </p>
      </div>
    )
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

  const youSideA = userId && state.player_a_id === userId
  const labelA = youSideA ? 'Ты (A)' : `Игрок A`
  const labelB = youSideA ? 'Игрок B' : (userId === state.player_b_id ? 'Ты (B)' : 'Игрок B')
  const opponentNameA = labelB
  const opponentNameB = labelA

  return (
    <div className="fixed inset-0 bg-black overflow-hidden">
      <div className="absolute inset-0 flex flex-col landscape:flex-row md:flex-row">
        <PlayerPanel
          label={labelA}
          wins={wins[0]}
          color="from-rose-700/40 to-rose-950"
          accentText="text-rose-200"
          canEdit={canEdit}
          onPlus={() => handlePlus('a')}
          onMinus={() => handleMinus('a')}
          isLeft
        />
        <PlayerPanel
          label={labelB}
          wins={wins[1]}
          color="from-sky-700/40 to-sky-950"
          accentText="text-sky-200"
          canEdit={canEdit}
          onPlus={() => handlePlus('b')}
          onMinus={() => handleMinus('b')}
        />
      </div>

      {/* Top bar */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-black/60 backdrop-blur-sm rounded-b-2xl px-4 py-1.5 text-white text-sm font-mono z-10">
        <span>⏱ {fmtClock(elapsedSec)}</span>
        {status === 'reconnecting' && (
          <span className="text-amber-300 text-xs animate-pulse">· реконнект</span>
        )}
        {isClosed && (
          <span className="text-zinc-300 text-xs">· закрыта {closeReason === 'timeout' ? '(таймаут)' : ''}</span>
        )}
      </div>

      {/* Bottom action bar */}
      <div className="absolute bottom-0 left-1/2 -translate-x-1/2 flex items-center gap-2 z-10 pb-2">
        {!isClosed && canEdit && (
          <button
            onClick={handleClose}
            className="bg-zinc-900/80 backdrop-blur-sm text-zinc-200 hover:text-white text-xs px-4 py-2 rounded-full border border-zinc-700"
          >
            Завершить
          </button>
        )}
      </div>

      {/* Error toast */}
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

      {/* Score picker modal */}
      <AnimatePresence>
        {picker && (
          <ScorePicker
            side={picker.side}
            opponentName={picker.side === 'a' ? opponentNameA : opponentNameB}
            onPick={(n) => submitScore(n, true)}
            onSkip={() => submitScore(null, false)}
            onClose={() => setPicker(null)}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
