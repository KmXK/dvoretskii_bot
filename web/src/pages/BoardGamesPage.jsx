import confetti from 'canvas-confetti'
import { AnimatePresence, motion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CheckersBoard from '../components/boardgames/CheckersBoard'
import ChessBoard from '../components/boardgames/ChessBoard'
import { useTelegram } from '../context/TelegramContext'
import useCasinoSounds from '../hooks/useCasinoSounds'

function Lobby({ rooms, send, balance }) {
  const [gameType, setGameType] = useState('chess')
  const [stake, setStake] = useState(0)
  const [botEnabled, setBotEnabled] = useState(true)
  const [botSide, setBotSide] = useState('black')
  const [botDifficulty, setBotDifficulty] = useState('medium')
  const [name, setName] = useState('')

  return (
    <div className="max-w-md mx-auto">
      <button onClick={() => window.history.back()} className="text-zinc-400 text-sm mb-4">← Назад</button>
      <h1 className="text-2xl font-bold text-white mb-1">Шахматы и шашки</h1>
      <p className="text-zinc-400 text-sm mb-4">PvP, боты, зрители и ставки</p>
      <p className="text-zinc-400 text-xs mb-4">Баланс: {balance} 🐵</p>

      <div className="bg-zinc-900 rounded-xl p-4 mb-4">
        <h2 className="text-white text-sm font-semibold mb-3">Создать матч</h2>
        <input value={name} onChange={e => setName(e.target.value)} placeholder="Название матча" className="w-full bg-zinc-800 rounded px-3 py-2 text-sm text-white mb-2" />
        <div className="grid grid-cols-2 gap-2 mb-2">
          <button onClick={() => setGameType('chess')} className={`py-2 rounded text-sm ${gameType === 'chess' ? 'bg-blue-600 text-white' : 'bg-zinc-800 text-zinc-400'}`}>♟️ Шахматы</button>
          <button onClick={() => setGameType('checkers')} className={`py-2 rounded text-sm ${gameType === 'checkers' ? 'bg-blue-600 text-white' : 'bg-zinc-800 text-zinc-400'}`}>⚫ Шашки</button>
        </div>
        <label className="text-zinc-400 text-xs block mb-1">Ставка игроков (0-200 🐵)</label>
        <input type="number" value={stake} onChange={e => setStake(Math.max(0, Math.min(200, Number(e.target.value) || 0)))} className="w-full bg-zinc-800 rounded px-3 py-2 text-sm text-white mb-2" />
        <label className="flex items-center gap-2 text-zinc-300 text-xs mb-2">
          <input type="checkbox" checked={botEnabled} onChange={e => setBotEnabled(e.target.checked)} className="accent-green-500" />
          Играть против бота
        </label>
        {botEnabled && (
          <div className="grid grid-cols-2 gap-2 mb-2">
            <button onClick={() => setBotSide('white')} className={`py-2 rounded text-xs ${botSide === 'white' ? 'bg-emerald-600 text-white' : 'bg-zinc-800 text-zinc-400'}`}>Бот белыми</button>
            <button onClick={() => setBotSide('black')} className={`py-2 rounded text-xs ${botSide === 'black' ? 'bg-emerald-600 text-white' : 'bg-zinc-800 text-zinc-400'}`}>Бот чёрными</button>
            <button onClick={() => setBotDifficulty('easy')} className={`py-2 rounded text-xs ${botDifficulty === 'easy' ? 'bg-sky-600 text-white' : 'bg-zinc-800 text-zinc-400'}`}>Easy</button>
            <button onClick={() => setBotDifficulty('medium')} className={`py-2 rounded text-xs ${botDifficulty === 'medium' ? 'bg-sky-600 text-white' : 'bg-zinc-800 text-zinc-400'}`}>Medium</button>
            <button onClick={() => setBotDifficulty('hard')} className={`col-span-2 py-2 rounded text-xs ${botDifficulty === 'hard' ? 'bg-sky-600 text-white' : 'bg-zinc-800 text-zinc-400'}`}>Hard</button>
          </div>
        )}
        <button
          onClick={() => send({ type: 'create_room', name, gameType, stake, botEnabled, botSide, botDifficulty })}
          className="w-full bg-green-600 hover:bg-green-500 text-white rounded py-2 text-sm font-semibold"
        >
          Создать
        </button>
      </div>

      <div className="bg-zinc-900 rounded-xl p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-white text-sm font-semibold">Комнаты</h3>
          <button onClick={() => send({ type: 'list_rooms' })} className="text-zinc-400 text-xs">Обновить</button>
        </div>
        <div className="flex flex-col gap-2">
          {rooms.length === 0 && <p className="text-zinc-500 text-sm text-center py-3">Пока пусто</p>}
          {rooms.map(r => (
            <div key={r.id} className="bg-zinc-800 rounded-lg px-3 py-2 flex items-center justify-between">
              <div>
                <p className="text-white text-sm">{r.gameType === 'chess' ? '♟️' : '⚫'} {r.name}</p>
                <p className="text-zinc-400 text-xs">Игроков: {r.playerCount} · Зрителей: {r.spectatorCount} · Ставка: {r.stake} 🐵 · Бот: {r.botDifficulty || 'medium'}</p>
              </div>
              <button onClick={() => send({ type: 'join_room', roomId: r.id })} className="bg-blue-600 hover:bg-blue-500 text-white text-xs rounded px-3 py-1.5">
                {r.started ? 'Смотреть' : 'Войти'}
              </button>
            </div>
          ))}
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
    fetch(`/api/user/${userId}/chats`)
      .then(r => r.ok ? r.json() : { chats: [] })
      .then(d => setChats(d.chats || []))
      .catch(() => { })
  }, [userId])

  useEffect(() => {
    if (!sent || !room?.id) return
    fetch('/api/boardgames/invite/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        roomId: room.id,
        roomName: room.name,
        gameType: room.gameType,
        playerCount: room.playerCount,
        spectatorCount: room.spectatorCount,
      }),
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
    await fetch('/api/boardgames/invite', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        roomId: room.id,
        roomName: room.name,
        gameType: room.gameType,
        playerCount: room.playerCount,
        spectatorCount: room.spectatorCount,
        creatorName: room.players?.find(p => p.id === room.creatorId)?.name || 'Игрок',
        chatIds: [...selected],
      }),
    }).catch(() => { })
    setSent(true)
  }

  if (!room || chats.length === 0) return null

  return (
    <div className="bg-zinc-900 rounded-xl p-4 mb-3">
      <button onClick={() => setExpanded(v => !v)} className="w-full flex items-center justify-between">
        <span className="text-white text-sm font-semibold">{sent ? '✓ Приглашения отправлены' : 'Пригласить в чаты'}</span>
        <span className="text-zinc-400 text-xs">{expanded ? '▲' : '▼'}</span>
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
            <div className="mt-3 flex flex-col gap-2">
              {chats.map(c => (
                <label key={c.id} className="bg-zinc-800 rounded-lg px-3 py-2 flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggle(c.id)} className="accent-green-500" disabled={sent} />
                  <span className="text-white text-sm truncate">{c.name}</span>
                </label>
              ))}
            </div>
            {!sent && (
              <button onClick={sendInvites} disabled={selected.size === 0} className="w-full mt-3 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 text-white text-sm font-semibold py-2 rounded-lg">
                Отправить ({selected.size})
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default function BoardGamesPage() {
  const { userId, initData } = useTelegram()
  const { sound } = useCasinoSounds()
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)
  const celebratedResultRef = useRef('')
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const [rooms, setRooms] = useState([])
  const [room, setRoom] = useState(null)
  const [state, setState] = useState(null)
  const [balance, setBalance] = useState(0)
  const [stats, setStats] = useState(null)

  const send = useCallback((payload) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify(payload))
  }, [])

  const fetchBalance = useCallback(() => {
    fetch('/api/casino/balance', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.monkeys != null) setBalance(d.monkeys) })
      .catch(() => { })
  }, [])

  const fetchStats = useCallback(() => {
    fetch('/api/casino/stats', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(d => setStats(d))
      .catch(() => { })
  }, [])

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
          sound('bigWin')
          fetchBalance()
        }
      }
      if (data.type === 'bet_ok') { if (data.monkeys != null) setBalance(data.monkeys); sound('tick') }
      if (data.type === 'left_room') { setRoom(null); setState(null); fetchBalance(); fetchStats() }
      if (data.type === 'error') {
        setError(data.message || 'Ошибка')
        setTimeout(() => setError(null), 2500)
      }
    }
    ws.onclose = () => {
      setConnected(false)
      reconnectRef.current = setTimeout(connect, 2000)
    }
    ws.onerror = () => ws.close()
  }, [fetchBalance, fetchStats, initData, sound])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  useEffect(() => {
    if (!room?.id) celebratedResultRef.current = ''
  }, [room?.id])

  useEffect(() => {
    if (!state?.room?.id || !state?.finished) return
    fetch('/api/boardgames/invite/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ roomId: state.room.id }),
    }).catch(() => { })
  }, [state?.room?.id, state?.finished])

  const myBet = useMemo(() => {
    if (!state?.bets || !userId) return null
    return state.bets.find(b => String(b.userId) === String(userId)) || null
  }, [state?.bets, userId])

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="px-4 pt-6 pb-20">
      {!connected && <p className="text-zinc-500 text-sm text-center py-6">Подключение...</p>}
      <AnimatePresence>
        {error && (
          <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            className="fixed top-4 left-4 right-4 z-50 bg-red-600 text-white text-sm rounded-lg px-4 py-2 text-center">
            {error}
          </motion.div>
        )}
      </AnimatePresence>

      {connected && !room && <Lobby rooms={rooms} send={send} balance={balance} />}
      {connected && !room && stats?.boardgames && (
        <div className="max-w-md mx-auto bg-zinc-900 rounded-xl p-4 mt-4">
          <h3 className="text-white text-sm font-semibold mb-2">Статистика и достижения</h3>
          <div className="grid grid-cols-2 gap-2 mb-2">
            <div className="bg-zinc-800 rounded-lg p-2 text-center">
              <div className="text-green-400 font-bold text-lg">{stats.boardgames.matches || 0}</div>
              <div className="text-zinc-500 text-[10px]">Партий</div>
            </div>
            <div className="bg-zinc-800 rounded-lg p-2 text-center">
              <div className="text-yellow-400 font-bold text-lg">{stats.boardgames.wins || 0}</div>
              <div className="text-zinc-500 text-[10px]">Побед</div>
            </div>
          </div>
          {(stats.achievements || []).length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {stats.achievements.map(a => (
                <span key={a.id} className="text-[10px] bg-emerald-600/20 text-emerald-300 px-2 py-1 rounded-full">
                  🏆 {a.title}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-zinc-500 text-xs">Достижения откроются по мере игр.</p>
          )}
        </div>
      )}

      {connected && room && (
        <div className="max-w-md mx-auto">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-white text-lg font-bold">{room.name}</h2>
            <button onClick={() => send({ type: 'leave_room' })} className="text-red-400 text-xs">Выйти</button>
          </div>

          <p className="text-zinc-400 text-xs mb-2">
            Роль: {state?.role === 'white' ? 'Белые' : state?.role === 'black' ? 'Чёрные' : 'Зритель'} ·
            Ход: {state?.turn === 'white' ? ' белых' : ' чёрных'} · Баланс: {balance} 🐵
          </p>

          {!state?.started && (
            <button
              onClick={() => send({ type: 'start_game' })}
              disabled={room.creatorId !== userId}
              className="w-full bg-green-600 hover:bg-green-500 disabled:bg-zinc-700 text-white rounded py-2 text-sm font-semibold mb-3"
            >
              {room.creatorId === userId ? 'Начать матч' : 'Ждём старта'}
            </button>
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
            <div className="bg-zinc-900 rounded-xl p-3 mb-3">
              <p className="text-white text-sm mb-2">Ставка на победителя</p>
              <div className="grid grid-cols-2 gap-2 mb-2">
                <button onClick={() => send({ type: 'place_bet', side: 'white', amount: 10 })} className="bg-zinc-800 hover:bg-zinc-700 text-white text-sm rounded py-2">Белые 10 🐵</button>
                <button onClick={() => send({ type: 'place_bet', side: 'black', amount: 10 })} className="bg-zinc-800 hover:bg-zinc-700 text-white text-sm rounded py-2">Чёрные 10 🐵</button>
                <button onClick={() => send({ type: 'place_bet', side: 'white', amount: 50 })} className="bg-zinc-800 hover:bg-zinc-700 text-white text-sm rounded py-2">Белые 50 🐵</button>
                <button onClick={() => send({ type: 'place_bet', side: 'black', amount: 50 })} className="bg-zinc-800 hover:bg-zinc-700 text-white text-sm rounded py-2">Чёрные 50 🐵</button>
              </div>
              <p className="text-zinc-500 text-xs">Выплата: x1.9 при победе выбранной стороны.</p>
            </div>
          )}

          {myBet && (
            <div className="bg-zinc-900 rounded-xl p-3 mb-3">
              <p className="text-green-400 text-sm font-semibold">Ваша ставка: {myBet.side === 'white' ? 'Белые' : 'Чёрные'} · {myBet.amount} 🐵</p>
            </div>
          )}

          {state?.finished && (
            <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="bg-zinc-900 rounded-xl p-4">
              <p className="text-white font-bold text-lg text-center">
                {state.winner === 'draw' ? '🤝 Ничья' : `🏆 Победили ${state.winner === 'white' ? 'белые' : 'чёрные'}`}
              </p>
              <p className="text-zinc-400 text-xs text-center mt-2">Завершите матч кнопкой «Выйти», чтобы вернуться в лобби.</p>
            </motion.div>
          )}
        </div>
      )}
    </motion.div>
  )
}
