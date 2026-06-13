import confetti from 'canvas-confetti'
import { AnimatePresence, motion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Bot, ChevronDown, Clock, Coins, Crown, Eye, Gamepad2, Handshake, LogOut,
  Play, RefreshCw, Send, Sparkles, Swords, Trophy, Users, WifiOff,
} from 'lucide-react'
import CheckersBoard from '../components/boardgames/CheckersBoard'
import ChessBoard from '../components/boardgames/ChessBoard'
import BackButton from '../components/BackButton'
import MascotLoader from '../components/MascotLoader'
import { useAuth } from '../context/useAuth'
import { useToast } from '../context/useToast'
import useCasinoSounds from '../hooks/useCasinoSounds'
import { api } from '../api/client'

const DIFFICULTIES = [
  { id: 'easy', label: 'Easy' },
  { id: 'medium', label: 'Medium' },
  { id: 'hard', label: 'Hard' },
]

function SegButton({ active, onClick, tone = 'gold', className = '', children }) {
  const activeCls = tone === 'indigo'
    ? 'bg-indigo-soft text-indigo'
    : tone === 'green'
      ? 'bg-spotify-green/15 text-spotify-green'
      : 'bg-gold-soft text-gold'
  return (
    <motion.button
      type="button"
      whileTap={{ scale: 0.96 }}
      onClick={onClick}
      className={`rounded-lg py-2 text-sm font-medium transition-colors ${active ? activeCls : 'bg-white/5 text-spotify-text hover:bg-white/10'} ${className}`}
    >
      {children}
    </motion.button>
  )
}

function Lobby({ rooms, send, balance }) {
  const [gameType, setGameType] = useState('chess')
  const [stake, setStake] = useState(0)
  const [botEnabled, setBotEnabled] = useState(true)
  const [botSide, setBotSide] = useState('black')
  const [botDifficulty, setBotDifficulty] = useState('medium')
  const [name, setName] = useState('')

  return (
    <div className="max-w-md mx-auto">
      <div className="flex items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="font-display text-2xl font-extrabold tracking-tight text-white flex items-center gap-2">
            <Swords size={22} className="text-gold" strokeWidth={2} />
            Шахматы и шашки
          </h1>
          <p className="text-spotify-text text-sm mt-0.5">PvP, боты, зрители и ставки</p>
        </div>
        <span className="shrink-0 inline-flex items-center gap-1.5 rounded-full bg-spotify-green/15 px-3 py-1.5 text-sm font-semibold text-spotify-green tabular-nums">
          {balance} 🐵
        </span>
      </div>

      <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4 mb-4">
        <p className="text-xs font-bold uppercase tracking-[0.08em] text-spotify-text mb-3">Создать матч</p>

        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="Название матча"
          className="w-full rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white placeholder:text-spotify-text/70 outline-none focus:bg-white/10 transition-colors mb-2.5"
        />

        <div className="grid grid-cols-2 gap-2 mb-3">
          <SegButton active={gameType === 'chess'} onClick={() => setGameType('chess')}>♟️ Шахматы</SegButton>
          <SegButton active={gameType === 'checkers'} onClick={() => setGameType('checkers')}>⚫ Шашки</SegButton>
        </div>

        <label className="flex items-center gap-1.5 text-xs font-medium text-spotify-text mb-1.5">
          <Coins size={14} strokeWidth={2} className="text-spotify-green" />
          Ставка игроков (0–200 🐵)
        </label>
        <input
          type="number"
          value={stake}
          onChange={e => setStake(Math.max(0, Math.min(200, Number(e.target.value) || 0)))}
          className="w-full rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white tabular-nums outline-none focus:bg-white/10 transition-colors mb-3"
        />

        <label className="flex items-center gap-2 text-sm text-white/90 mb-2.5 cursor-pointer">
          <input type="checkbox" checked={botEnabled} onChange={e => setBotEnabled(e.target.checked)} className="accent-gold w-4 h-4" />
          <Bot size={16} strokeWidth={2} className="text-indigo" />
          Играть против бота
        </label>

        <AnimatePresence initial={false}>
          {botEnabled && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="grid grid-cols-2 gap-2 mb-3">
                <SegButton tone="indigo" active={botSide === 'white'} onClick={() => setBotSide('white')}>Бот белыми</SegButton>
                <SegButton tone="indigo" active={botSide === 'black'} onClick={() => setBotSide('black')}>Бот чёрными</SegButton>
                {DIFFICULTIES.map(d => (
                  <SegButton
                    key={d.id}
                    tone="indigo"
                    active={botDifficulty === d.id}
                    onClick={() => setBotDifficulty(d.id)}
                    className={d.id === 'hard' ? 'col-span-2' : ''}
                  >
                    {d.label}
                  </SegButton>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <motion.button
          whileTap={{ scale: 0.98 }}
          onClick={() => send({ type: 'create_room', name, gameType, stake, botEnabled, botSide, botDifficulty })}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-gold py-2.5 text-sm font-semibold text-spotify-black transition-colors hover:bg-gold-2"
        >
          <Play size={16} strokeWidth={2.5} />
          Создать
        </motion.button>
      </div>

      <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4">
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs font-bold uppercase tracking-[0.08em] text-spotify-text flex items-center gap-1.5">
            <Users size={14} strokeWidth={2} />
            Комнаты
          </p>
          <motion.button
            whileTap={{ scale: 0.9, rotate: -90 }}
            onClick={() => send({ type: 'list_rooms' })}
            className="text-spotify-text hover:text-white transition-colors"
            aria-label="Обновить"
          >
            <RefreshCw size={16} strokeWidth={2} />
          </motion.button>
        </div>

        {rooms.length === 0 && (
          <div className="text-center py-8">
            <Gamepad2 size={36} className="mx-auto mb-2 text-spotify-text/50" strokeWidth={1.75} />
            <p className="text-spotify-text text-sm">Пока пусто — создай первый матч</p>
          </div>
        )}

        <div className="flex flex-col gap-2">
          <AnimatePresence initial={false}>
            {rooms.map((r, i) => (
              <motion.div
                key={r.id}
                layout
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.96 }}
                transition={{ delay: Math.min(i * 0.04, 0.2), type: 'spring', stiffness: 420, damping: 30 }}
                className="flex items-center justify-between gap-3 rounded-xl bg-spotify-dark px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="text-white text-sm font-medium truncate">
                    {r.gameType === 'chess' ? '♟️' : '⚫'} {r.name}
                  </p>
                  <p className="text-spotify-text text-xs flex items-center gap-2 mt-0.5 flex-wrap">
                    <span className="inline-flex items-center gap-1"><Users size={12} />{r.playerCount}</span>
                    <span className="inline-flex items-center gap-1"><Eye size={12} />{r.spectatorCount}</span>
                    <span className="inline-flex items-center gap-1 text-spotify-green"><Coins size={12} />{r.stake}</span>
                    <span className="inline-flex items-center gap-1"><Bot size={12} />{r.botDifficulty || 'medium'}</span>
                  </p>
                </div>
                <motion.button
                  whileTap={{ scale: 0.94 }}
                  onClick={() => send({ type: 'join_room', roomId: r.id })}
                  className={`shrink-0 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                    r.started ? 'bg-indigo-soft text-indigo hover:brightness-110' : 'bg-gold text-spotify-black hover:bg-gold-2'
                  }`}
                >
                  {r.started ? <><Eye size={13} />Смотреть</> : <><Play size={13} />Войти</>}
                </motion.button>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}

function InviteBlock({ room, userId }) {
  const [chats, setChats] = useState([])
  const [selected, setSelected] = useState(new Set())
  const [expanded, setExpanded] = useState(false)
  const [sent, setSent] = useState(false)

  useEffect(() => {
    if (!userId) return
    api.get(`/api/user/${userId}/chats`)
      .then(d => setChats(d.chats || []))
      .catch(() => { })
  }, [userId])

  useEffect(() => {
    if (!sent || !room?.id) return
    api.post('/api/boardgames/invite/update', {
      roomId: room.id,
      roomName: room.name,
      gameType: room.gameType,
      playerCount: room.playerCount,
      spectatorCount: room.spectatorCount,
    }).catch(() => { })
  }, [sent, room?.id, room?.name, room?.gameType, room?.playerCount, room?.spectatorCount])

  const toggle = (id) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const sendInvites = async () => {
    if (!room?.id || selected.size === 0) return
    await api.post('/api/boardgames/invite', {
      roomId: room.id,
      roomName: room.name,
      gameType: room.gameType,
      playerCount: room.playerCount,
      spectatorCount: room.spectatorCount,
      creatorName: room.players?.find(p => p.id === room.creatorId)?.name || 'Игрок',
      chatIds: [...selected],
    }).catch(() => { })
    setSent(true)
  }

  if (!room || chats.length === 0) return null

  return (
    <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4 mb-3">
      <button onClick={() => setExpanded(v => !v)} className="w-full flex items-center justify-between">
        <span className="text-white text-sm font-semibold flex items-center gap-2">
          <Send size={15} strokeWidth={2} className="text-indigo" />
          {sent ? 'Приглашения отправлены' : 'Пригласить в чаты'}
        </span>
        <motion.span animate={{ rotate: expanded ? 180 : 0 }} className="text-spotify-text">
          <ChevronDown size={16} />
        </motion.span>
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
            <div className="mt-3 flex flex-col gap-2">
              {chats.map(c => (
                <label key={c.id} className="bg-spotify-dark rounded-lg px-3 py-2 flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggle(c.id)} className="accent-indigo w-4 h-4" disabled={sent} />
                  <span className="text-white text-sm truncate">{c.name}</span>
                </label>
              ))}
            </div>
            {!sent && (
              <motion.button
                whileTap={{ scale: 0.98 }}
                onClick={sendInvites}
                disabled={selected.size === 0}
                className="w-full mt-3 flex items-center justify-center gap-2 rounded-xl bg-indigo py-2.5 text-sm font-semibold text-white transition-opacity disabled:opacity-40"
              >
                <Send size={15} />
                Отправить ({selected.size})
              </motion.button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function StatTile({ value, label, tone }) {
  const color = tone === 'gold' ? 'text-gold' : 'text-spotify-green'
  return (
    <div className="rounded-xl bg-spotify-dark p-2.5 text-center">
      <div className={`font-display text-xl font-extrabold tabular-nums ${color}`}>{value}</div>
      <div className="text-spotify-text text-[10px] mt-0.5">{label}</div>
    </div>
  )
}

export default function BoardGamesPage() {
  const { userId, initData } = useAuth()
  const { sound } = useCasinoSounds()
  const toast = useToast()
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)
  const celebratedResultRef = useRef('')
  const closingRef = useRef(false)
  const soundRef = useRef(sound)
  const toastRef = useRef(toast)
  const connectRef = useRef(null)
  const [connected, setConnected] = useState(false)
  const [rooms, setRooms] = useState([])
  const [room, setRoom] = useState(null)
  const [state, setState] = useState(null)
  const [balance, setBalance] = useState(0)
  const [stats, setStats] = useState(null)

  const send = useCallback((payload) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify(payload))
  }, [])

  const fetchBalance = useCallback(() => {
    api.get('/api/casino/balance')
      .then(d => { if (d?.monkeys != null) setBalance(d.monkeys) })
      .catch(() => { })
  }, [])

  const fetchStats = useCallback(() => {
    api.get('/api/casino/stats')
      .then(d => setStats(d))
      .catch(() => { })
  }, [])

  // Держим актуальные sound/toast в ref, чтобы они не пересоздавали connect.
  useEffect(() => { soundRef.current = sound }, [sound])
  useEffect(() => { toastRef.current = toast }, [toast])

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/boardgames`)
    wsRef.current = ws
    ws.onopen = () => {
      setConnected(true)
      ws.send(JSON.stringify({ type: 'auth', initData }))
      ws.send(JSON.stringify({ type: 'list_rooms' }))
      fetchBalance()
      fetchStats()
    }
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'rooms_list') setRooms(data.rooms || [])
      if (data.type === 'room_joined') { setRoom(data.room); setState(null) }
      if (data.type === 'room_updated') setRoom(data.room)
      if (data.type === 'room_state') {
        setState(data.state)
        if (!data.state?.finished) celebratedResultRef.current = ''
        const winner = data.state?.winner
        const roomId = data.state?.room?.id
        const resultKey = roomId && winner ? `${roomId}:${winner}` : ''
        if (data.state.finished && winner && winner !== 'draw' && celebratedResultRef.current !== resultKey) {
          celebratedResultRef.current = resultKey
          confetti({ particleCount: 80, spread: 55, origin: { y: 0.6 } })
          soundRef.current('bigWin')
          fetchBalance()
        }
      }
      if (data.type === 'bet_ok') { if (data.monkeys != null) setBalance(data.monkeys); soundRef.current('tick') }
      if (data.type === 'left_room') { setRoom(null); setState(null); fetchBalance(); fetchStats() }
      if (data.type === 'error') toastRef.current?.error(data.message || 'Ошибка')
    }
    ws.onclose = () => {
      // Игнорируем закрытие сокета, который уже заменён более новым.
      if (wsRef.current !== ws) return
      setConnected(false)
      // Не переподключаемся, если компонент размонтирован (намеренное закрытие).
      if (!closingRef.current) reconnectRef.current = setTimeout(() => connectRef.current?.(), 2000)
    }
    ws.onerror = () => ws.close()
  }, [fetchBalance, fetchStats, initData])

  useEffect(() => { connectRef.current = connect }, [connect])

  useEffect(() => {
    closingRef.current = false
    connect()
    return () => {
      closingRef.current = true
      clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  useEffect(() => {
    if (!room?.id) celebratedResultRef.current = ''
  }, [room?.id])

  useEffect(() => {
    if (!state?.room?.id || !state?.finished) return
    api.post('/api/boardgames/invite/delete', { roomId: state.room.id }).catch(() => { })
  }, [state?.room?.id, state?.finished])

  const myBet = useMemo(() => {
    if (!state?.bets || !userId) return null
    return state.bets.find(b => String(b.userId) === String(userId)) || null
  }, [state?.bets, userId])

  const boardStats = useMemo(() => {
    const bg = stats?.boardgames || {}
    return {
      matches: bg.matches || 0,
      wins: bg.wins || 0,
      chessMatches: bg.chessMatches || 0,
      chessWins: bg.chessWins || 0,
      checkersMatches: bg.checkersMatches || 0,
      checkersWins: bg.checkersWins || 0,
    }
  }, [stats?.boardgames])

  const offlinePlayers = room?.players?.filter(p => p.offline) || []
  const roleLabel = state?.role === 'white' ? 'Белые' : state?.role === 'black' ? 'Чёрные' : 'Зритель'
  const turnLabel = state?.turn === 'white' ? 'белых' : 'чёрных'

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="px-4 pt-6 pb-4 max-w-3xl mx-auto">
      <BackButton />

      {!connected && (
        <div className="flex flex-col items-center justify-center h-64 gap-3">
          <MascotLoader scale={0.7} />
          <p className="text-spotify-text text-sm">Подключение…</p>
        </div>
      )}

      {connected && !room && <Lobby rooms={rooms} send={send} balance={balance} />}

      {connected && !room && stats?.boardgames && (
        <div className="max-w-md mx-auto rounded-2xl border border-white/5 bg-spotify-gray p-4 mt-4">
          <p className="text-xs font-bold uppercase tracking-[0.08em] text-spotify-text mb-3 flex items-center gap-1.5">
            <Trophy size={14} strokeWidth={2} className="text-gold" />
            Статистика и достижения
          </p>
          <div className="grid grid-cols-2 gap-2 mb-2">
            <StatTile value={boardStats.matches} label="Партий" tone="green" />
            <StatTile value={boardStats.wins} label="Побед" tone="gold" />
          </div>
          <div className="grid grid-cols-2 gap-2 mb-3">
            <div className="rounded-xl bg-spotify-dark p-2.5">
              <p className="text-spotify-text text-[10px] mb-1 flex items-center gap-1">♟️ Шахматы</p>
              <p className="text-white text-xs">Матчи: <span className="font-semibold tabular-nums">{boardStats.chessMatches}</span></p>
              <p className="text-white text-xs">Победы: <span className="font-semibold tabular-nums text-gold">{boardStats.chessWins}</span></p>
            </div>
            <div className="rounded-xl bg-spotify-dark p-2.5">
              <p className="text-spotify-text text-[10px] mb-1 flex items-center gap-1">⚫ Шашки</p>
              <p className="text-white text-xs">Матчи: <span className="font-semibold tabular-nums">{boardStats.checkersMatches}</span></p>
              <p className="text-white text-xs">Победы: <span className="font-semibold tabular-nums text-gold">{boardStats.checkersWins}</span></p>
            </div>
          </div>
          {(stats.achievements || []).length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {stats.achievements.map(a => (
                <span key={a.id} className="inline-flex items-center gap-1 text-[10px] bg-gold-soft text-gold px-2 py-1 rounded-full">
                  <Trophy size={10} /> {a.title}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-spotify-text text-xs flex items-center gap-1.5">
              <Sparkles size={13} /> Достижения откроются по мере игр.
            </p>
          )}
        </div>
      )}

      {connected && room && (
        <div className="max-w-md mx-auto">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display text-lg font-extrabold tracking-tight text-white truncate">{room.name}</h2>
            <motion.button
              whileTap={{ scale: 0.94 }}
              onClick={() => send({ type: 'leave_room' })}
              className="shrink-0 inline-flex items-center gap-1 text-red-400 hover:text-red-300 text-xs transition-colors"
            >
              <LogOut size={14} /> Выйти
            </motion.button>
          </div>

          <div className="flex items-center gap-2 flex-wrap mb-2.5 text-xs">
            <span className="inline-flex items-center gap-1 rounded-full bg-white/5 px-2.5 py-1 text-spotify-text">
              <Crown size={12} /> {roleLabel}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white/5 px-2.5 py-1 text-white">
              <span className={`inline-block w-1.5 h-1.5 rounded-full ${state?.turn === 'white' ? 'bg-gold' : 'bg-indigo'} animate-pulse`} />
              Ход {turnLabel}
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-spotify-green/15 px-2.5 py-1 text-spotify-green font-semibold tabular-nums">
              {balance} 🐵
            </span>
          </div>

          <AnimatePresence>
            {state?.started && !state?.finished && offlinePlayers.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                className="flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/15 px-3 py-2 mb-2.5 text-xs text-amber-300"
              >
                <WifiOff size={14} className="shrink-0 animate-pulse" />
                <span>{offlinePlayers.map(p => p.name).join(', ')} переподключается… иначе техническое поражение</span>
              </motion.div>
            )}
          </AnimatePresence>

          {!state?.started && (
            <motion.button
              whileTap={{ scale: 0.98 }}
              onClick={() => send({ type: 'start_game' })}
              disabled={room.creatorId !== userId}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-gold py-2.5 text-sm font-semibold text-spotify-black transition-colors hover:bg-gold-2 disabled:bg-white/5 disabled:text-spotify-text mb-3"
            >
              {room.creatorId === userId ? <><Play size={16} strokeWidth={2.5} /> Начать матч</> : <><Clock size={16} /> Ждём старта</>}
            </motion.button>
          )}

          <InviteBlock room={room} userId={userId} />

          {state?.started && (
            <div className="mb-3">
              {state.room.gameType === 'chess' ? (
                <ChessBoard state={state} onMove={send} />
              ) : (
                <CheckersBoard state={state} onMove={send} />
              )}
            </div>
          )}

          {state?.role === 'spectator' && state?.started && !state?.finished && !myBet && (
            <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4 mb-3">
              <p className="text-white text-sm font-medium mb-3 flex items-center gap-1.5">
                <Coins size={15} className="text-spotify-green" /> Ставка на победителя
              </p>
              <div className="grid grid-cols-2 gap-2 mb-2">
                {[
                  { side: 'white', amount: 10, label: 'Белые 10' },
                  { side: 'black', amount: 10, label: 'Чёрные 10' },
                  { side: 'white', amount: 50, label: 'Белые 50' },
                  { side: 'black', amount: 50, label: 'Чёрные 50' },
                ].map(b => (
                  <motion.button
                    key={`${b.side}-${b.amount}`}
                    whileTap={{ scale: 0.95 }}
                    onClick={() => send({ type: 'place_bet', side: b.side, amount: b.amount })}
                    className="rounded-lg bg-spotify-dark hover:bg-white/10 text-white text-sm py-2.5 transition-colors"
                  >
                    {b.label} <span className="text-spotify-green">🐵</span>
                  </motion.button>
                ))}
              </div>
              <p className="text-spotify-text text-xs">Выплата ×1.9 при победе выбранной стороны.</p>
            </div>
          )}

          {myBet && (
            <div className="rounded-2xl border border-spotify-green/20 bg-spotify-green/10 p-3.5 mb-3">
              <p className="text-spotify-green text-sm font-semibold flex items-center gap-1.5">
                <Coins size={15} /> Ваша ставка: {myBet.side === 'white' ? 'Белые' : 'Чёрные'} · <span className="tabular-nums">{myBet.amount}</span> 🐵
              </p>
            </div>
          )}

          <AnimatePresence>
            {state?.finished && (
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ type: 'spring', stiffness: 400, damping: 22 }}
                className="rounded-2xl border border-white/5 bg-spotify-gray p-5 text-center"
              >
                {state.winner === 'draw' ? (
                  <Handshake size={40} className="mx-auto mb-2 text-indigo" strokeWidth={1.75} />
                ) : (
                  <Trophy size={40} className="mx-auto mb-2 text-gold" strokeWidth={1.75} />
                )}
                <p className="font-display text-lg font-extrabold text-white">
                  {state.winner === 'draw' ? 'Ничья' : `Победили ${state.winner === 'white' ? 'белые' : 'чёрные'}`}
                </p>
                <p className="text-spotify-text text-xs mt-2">Нажмите «Выйти», чтобы вернуться в лобби.</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  )
}
