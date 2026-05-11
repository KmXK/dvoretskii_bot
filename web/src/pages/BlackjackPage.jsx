import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useAuth } from '../context/useAuth'
import useCasinoSounds from '../hooks/useCasinoSounds'

const SUIT_SYMBOL = { h: '♥', d: '♦', c: '♣', s: '♠', '?': '•' }

function Card({ card }) {
  const hidden = card?.rank === '?' || card?.suit === '?'
  if (hidden) {
    return (
      <div className="w-12 h-16 rounded-lg bg-gradient-to-br from-blue-700 to-blue-900 border border-blue-500/40 flex items-center justify-center text-blue-200 text-xs font-bold">
        BJ
      </div>
    )
  }
  const isRed = card.suit === 'h' || card.suit === 'd'
  return (
    <div className={`w-12 h-16 rounded-lg bg-white border border-zinc-300 flex flex-col items-center justify-center ${isRed ? 'text-red-500' : 'text-zinc-900'}`}>
      <span className="text-sm font-bold leading-none">{card.rank}</span>
      <span className="text-xs leading-none">{SUIT_SYMBOL[card.suit]}</span>
    </div>
  )
}

function AnimatedTableCard({ card, revealSeed }) {
  const hidden = card?.rank === '?' || card?.suit === '?'
  return (
    <motion.div
      key={`${revealSeed}-${card?.rank}-${card?.suit}`}
      initial={{ opacity: 0, y: -10, rotateY: hidden ? 0 : 110 }}
      animate={{ opacity: 1, y: 0, rotateY: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      style={{ transformStyle: 'preserve-3d' }}
    >
      <Card card={card} />
    </motion.div>
  )
}

function Lobby({ rooms, send, monkeyBalance }) {
  const [name, setName] = useState('')
  const [startChips, setStartChips] = useState(1000)
  const [tableBet, setTableBet] = useState(25)
  const [botCount, setBotCount] = useState(1)
  const [playForMonkeys, setPlayForMonkeys] = useState(false)

  const create = () => {
    send({
      type: 'create_room',
      name: name.trim() || undefined,
      startChips,
      tableBet,
      botCount,
      playForMonkeys,
    })
    setName('')
  }

  return (
    <div className="max-w-md mx-auto">
      <button onClick={() => window.history.back()} className="text-zinc-400 text-sm hover:text-white transition-colors mb-4">
        ← Назад
      </button>
      <h1 className="text-2xl font-bold text-white mb-1">Блэкджек</h1>
      <p className="text-zinc-400 text-sm mb-4">Играй против ботов и реальных игроков</p>
      {Number.isFinite(monkeyBalance) && (
        <p className="text-zinc-400 text-xs mb-4">Баланс: {monkeyBalance} 🐵</p>
      )}

      <div className="bg-zinc-900 rounded-xl p-4 mb-4">
        <h2 className="text-white text-sm font-semibold mb-3">Создать комнату</h2>
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="Название комнаты"
          className="w-full mb-2 bg-zinc-800 rounded-lg px-3 py-2 text-sm text-white outline-none focus:ring-1 focus:ring-green-500"
          maxLength={40}
        />
        <div className="grid grid-cols-2 gap-2 mb-2">
          <label className="text-[11px] text-zinc-400 flex flex-col gap-1">
            Стартовый стек (фишки)
            <input
              type="number"
              value={startChips}
              onChange={e => setStartChips(Math.max(100, Number(e.target.value) || 100))}
              className="bg-zinc-800 rounded-lg px-2 py-2 text-sm text-white outline-none focus:ring-1 focus:ring-green-500"
            />
          </label>
          <label className="text-[11px] text-zinc-400 flex flex-col gap-1">
            Ставка за раунд (фишки)
            <input
              type="number"
              value={tableBet}
              onChange={e => setTableBet(Math.max(5, Number(e.target.value) || 5))}
              className="bg-zinc-800 rounded-lg px-2 py-2 text-sm text-white outline-none focus:ring-1 focus:ring-green-500"
            />
          </label>
          <label className="text-[11px] text-zinc-400 flex flex-col gap-1">
            Ботов за столом
            <input
              type="number"
              value={botCount}
              onChange={e => setBotCount(Math.max(0, Math.min(5, Number(e.target.value) || 0)))}
              className="bg-zinc-800 rounded-lg px-2 py-2 text-sm text-white outline-none focus:ring-1 focus:ring-green-500"
            />
          </label>
          <label className="bg-zinc-800 rounded-lg px-2 py-2 text-xs text-zinc-300 flex items-center gap-2">
            <input
              type="checkbox"
              checked={playForMonkeys}
              onChange={e => setPlayForMonkeys(e.target.checked)}
              className="accent-yellow-500"
            />
            Обезьянки → фишки
          </label>
        </div>
        <button onClick={create} className="w-full bg-green-600 hover:bg-green-500 text-white text-sm font-semibold py-2 rounded-lg transition-colors">
          Создать
        </button>
      </div>

      <div className="bg-zinc-900 rounded-xl p-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-white text-sm font-semibold">Комнаты</h2>
          <button onClick={() => send({ type: 'list_rooms' })} className="text-zinc-400 text-xs hover:text-white">
            Обновить
          </button>
        </div>
        <div className="flex flex-col gap-2">
          {rooms.length === 0 && <p className="text-zinc-500 text-sm py-3 text-center">Нет доступных комнат</p>}
          {rooms.map(r => (
            <div key={r.id} className="bg-zinc-800 rounded-lg px-3 py-2 flex items-center justify-between">
              <div>
                <p className="text-white text-sm">{r.name}</p>
                <p className="text-zinc-400 text-xs">
                  {r.playerCount}/{r.maxPlayers} · ставка {r.tableBet} фишек/раунд · стек {r.startChips} фишек
                  {r.playForMonkeys ? ` · 🐵 ${Math.floor((r.startChips || 0) / (r.monkeyChipRate || 10))}` : ''}
                </p>
              </div>
              <button
                onClick={() => send({ type: 'join_room', roomId: r.id })}
                className="bg-green-600 hover:bg-green-500 text-white text-xs font-semibold px-3 py-1.5 rounded"
              >
                {r.started ? 'Наблюдать' : 'Войти'}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function WaitingRoom({ room, send, userId, monkeyBalance }) {
  if (!room) return null
  const isCreator = room.creator_id === userId
  const [showLeave, setShowLeave] = useState(false)

  return (
    <div className="max-w-md mx-auto">
      <AnimatePresence>
        {showLeave && (
          <motion.div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4 w-full max-w-xs">
              <p className="text-white text-sm mb-3">Покинуть комнату?</p>
              <div className="flex gap-2">
                <button onClick={() => setShowLeave(false)} className="flex-1 bg-zinc-700 text-white text-xs py-2 rounded">Остаться</button>
                <button onClick={() => send({ type: 'leave_room' })} className="flex-1 bg-red-600 text-white text-xs py-2 rounded">Выйти</button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl text-white font-bold">{room.name}</h1>
        <button onClick={() => setShowLeave(true)} className="text-red-400 text-sm hover:text-red-300">Выйти</button>
      </div>
      {room.playForMonkeys && Number.isFinite(monkeyBalance) && (
        <p className="text-zinc-400 text-xs mb-3">Баланс: {monkeyBalance} 🐵</p>
      )}
      <div className="bg-zinc-900 rounded-xl p-4 mb-4">
        <p className="text-zinc-400 text-xs mb-1">Стартовые фишки: {room.startChips}</p>
        <p className="text-zinc-400 text-xs mb-1">Ставка стола: {room.tableBet}</p>
        <p className="text-zinc-400 text-xs">Режим: {room.playForMonkeys ? 'Обезьянки → фишки' : 'Фишки'}</p>
      </div>
      <div className="bg-zinc-900 rounded-xl p-4 mb-4">
        <h2 className="text-white text-sm font-semibold mb-2">Игроки</h2>
        <div className="flex flex-col gap-1.5">
          {(room.players || []).map(p => (
            <div key={p.id} className="bg-zinc-800 rounded px-3 py-2 text-sm text-white flex items-center gap-2">
              <span>{p.isBot ? '🤖' : '👤'}</span>
              <span className={p.id === userId ? 'text-green-400' : ''}>{p.name}</span>
              {p.id === room.creator_id && <span className="ml-auto text-xs text-yellow-400">создатель</span>}
            </div>
          ))}
        </div>
      </div>
      {isCreator ? (
        <button onClick={() => send({ type: 'start_game' })} className="w-full bg-green-600 hover:bg-green-500 text-white font-semibold text-sm py-3 rounded-xl">
          Начать игру
        </button>
      ) : (
        <p className="text-zinc-400 text-sm text-center">Ждём старта от создателя...</p>
      )}
    </div>
  )
}

function actionLabel(a) {
  if (!a) return ''
  const map = { hit: 'Взял карту', stand: 'Остановился', double: 'Удвоил ставку' }
  return map[a.action] || a.action
}

function outcomeLabel(outcome) {
  const map = {
    loss: 'Проигрыш',
    win: 'Победа',
    push: 'Ничья',
    blackjack: 'Блэкджек',
  }
  return map[outcome] || outcome
}

function Table({ state, send, userId, onLeave, sound }) {
  const [showLeave, setShowLeave] = useState(false)
  const [celebration, setCelebration] = useState(null)
  const [tableFlash, setTableFlash] = useState(null)
  const dealerHiddenRef = useRef(true)
  const safeState = state || {
    myIndex: -1,
    players: [],
    dealer: { cards: [], total: 0 },
    phase: 'waiting',
    readyPlayers: [],
    roundNum: 0,
  }
  const me = safeState.myIndex >= 0 ? safeState.players[safeState.myIndex] : null
  const dealer = safeState.dealer || { cards: [], total: 0 }
  const isShowdown = safeState.phase === 'showdown'
  const myReady = (safeState.readyPlayers || []).includes(userId)
  const roundSeed = `${safeState.roundNum}-${safeState.phase}`

  useEffect(() => {
    if (!isShowdown || !me?.result) return
    const outcome = me.result.outcome
    const isPositive = outcome === 'win' || outcome === 'blackjack'
    if (isPositive) {
      setCelebration({ outcome, id: `${safeState.roundNum}-${outcome}` })
    }
    setTableFlash({ outcome, id: `${safeState.roundNum}-${outcome}-flash` })
    if (outcome === 'blackjack') sound('blackjack')
    else if (outcome === 'win') sound('bigWin')
    else if (outcome === 'push') sound('tick')
    else sound('lose')
    const t1 = setTimeout(() => setCelebration(null), 1400)
    const t2 = setTimeout(() => setTableFlash(null), 900)
    return () => { clearTimeout(t1); clearTimeout(t2) }
  }, [isShowdown, me?.result, safeState.roundNum, sound])

  useEffect(() => {
    if (!state) return
    const cards = state.dealer?.cards || []
    const hasHidden = cards.some(c => c?.rank === '?' || c?.suit === '?')
    if (dealerHiddenRef.current && !hasHidden && cards.length >= 2) {
      sound('cardFlip')
    }
    dealerHiddenRef.current = hasHidden
  }, [state?.dealer?.cards, sound, state])

  if (!state) return null

  return (
    <div className="max-w-md mx-auto">
      <AnimatePresence>
        {tableFlash && (
          <motion.div
            key={tableFlash.id}
            className="fixed inset-0 z-30 pointer-events-none"
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 0.35, 0] }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.8 }}
            style={{
              background:
                tableFlash.outcome === 'loss'
                  ? 'radial-gradient(circle at center, rgba(239,68,68,0.35), transparent 65%)'
                  : tableFlash.outcome === 'push'
                    ? 'radial-gradient(circle at center, rgba(161,161,170,0.28), transparent 65%)'
                    : tableFlash.outcome === 'blackjack'
                      ? 'radial-gradient(circle at center, rgba(250,204,21,0.38), transparent 65%)'
                      : 'radial-gradient(circle at center, rgba(34,197,94,0.35), transparent 65%)',
            }}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {celebration && (
          <motion.div
            key={celebration.id}
            className="fixed inset-0 z-40 pointer-events-none"
            initial={{ opacity: 1 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            {Array.from({ length: 18 }, (_, i) => {
              const left = 8 + ((i * 5.3) % 84)
              const drift = ((i % 2 === 0 ? 1 : -1) * (14 + (i % 5) * 4))
              const symbol = celebration.outcome === 'blackjack' ? '🃏' : '✨'
              return (
                <motion.span
                  key={i}
                  className="absolute text-lg"
                  style={{ left: `${left}%`, top: '18%' }}
                  initial={{ opacity: 0, y: -10, scale: 0.7 }}
                  animate={{ opacity: [0, 1, 1, 0], y: [0, 190], x: [0, drift], rotate: [0, 240], scale: [0.7, 1, 0.9] }}
                  transition={{ duration: 1.2, delay: i * 0.025, ease: 'easeOut' }}
                >
                  {symbol}
                </motion.span>
              )
            })}
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showLeave && (
          <motion.div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4 w-full max-w-xs">
              <p className="text-white text-sm mb-3">Покинуть стол?</p>
              <div className="flex gap-2">
                <button onClick={() => setShowLeave(false)} className="flex-1 bg-zinc-700 text-white text-xs py-2 rounded">Остаться</button>
                <button onClick={onLeave} className="flex-1 bg-red-600 text-white text-xs py-2 rounded">Выйти</button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex items-center justify-between mb-3">
        <h2 className="text-white text-lg font-bold">Раздача #{state.roundNum}</h2>
        <button onClick={() => setShowLeave(true)} className="text-red-400 text-xs hover:text-red-300">Выйти</button>
      </div>

      <motion.div
        className="bg-zinc-900 rounded-xl p-4 mb-3 relative overflow-hidden"
        animate={{ boxShadow: ['0 0 0px rgba(59,130,246,0)', '0 0 18px rgba(59,130,246,0.2)', '0 0 0px rgba(59,130,246,0)'] }}
        transition={{ duration: 2.6, repeat: Infinity }}
      >
        <motion.div
          className="absolute inset-0 pointer-events-none"
          style={{ background: 'radial-gradient(circle at 20% 20%, rgba(34,197,94,0.12), transparent 55%)' }}
          animate={{ opacity: [0.5, 1, 0.5] }}
          transition={{ duration: 2.2, repeat: Infinity }}
        />
        <p className="text-zinc-400 text-xs mb-2">Дилер: {dealer.total}</p>
        <div className="flex gap-1.5">
          {(dealer.cards || []).map((c, i) => (
            <AnimatedTableCard
              key={i}
              card={c}
              revealSeed={`${roundSeed}-dealer-${i}`}
            />
          ))}
        </div>
      </motion.div>

      <div className="bg-zinc-900 rounded-xl p-4 mb-3">
        <h3 className="text-white text-sm font-semibold mb-2">Игроки</h3>
        <div className="flex flex-col gap-2">
          {state.players.map((p, i) => (
            <div key={p.id} className={`rounded-lg px-3 py-2 ${i === state.currentIndex ? 'bg-yellow-500/15 border border-yellow-400/40' : 'bg-zinc-800'}`}>
              <div className="flex items-center justify-between">
                <span className={`text-sm ${i === state.myIndex ? 'text-green-400 font-semibold' : 'text-white'}`}>
                  {p.name} {p.isBot ? '🤖' : ''}
                </span>
                <span className="text-xs text-zinc-400">{p.chips} фишек</span>
              </div>
              <div className="flex items-center justify-between mt-1">
                <span className="text-[11px] text-zinc-500">ставка {p.bet} фишек</span>
                <span className="text-[11px] text-zinc-500">
                  {p.busted ? 'перебор' : p.blackjack ? 'блэкджек' : p.done ? 'готов' : 'ходит'}
                </span>
              </div>
              {isShowdown && p.result && (
                <p className={`text-[11px] mt-1 ${p.result.outcome === 'loss' ? 'text-red-400' : 'text-green-400'}`}>
                  {outcomeLabel(p.result.outcome)} · выплата {p.result.payout} фишек
                </p>
              )}
            </div>
          ))}
        </div>
      </div>

      {me && (
        <motion.div className="bg-zinc-900 rounded-xl p-4 mb-3"
          animate={state.currentIndex === state.myIndex ? { boxShadow: ['0 0 0px rgba(250,204,21,0)', '0 0 20px rgba(250,204,21,0.25)', '0 0 0px rgba(250,204,21,0)'] } : {}}
          transition={{ duration: 1.4, repeat: state.currentIndex === state.myIndex ? Infinity : 0 }}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-white text-sm font-semibold">Ваши карты</h3>
            <span className="text-zinc-400 text-xs">ставка {me.bet} фишек</span>
          </div>
          <div className="flex gap-1.5 mb-2">
            {(me.cards || []).map((c, i) => (
              <AnimatedTableCard
                key={i}
                card={c}
                revealSeed={`${roundSeed}-me-${i}`}
              />
            ))}
          </div>
          {typeof me.total === 'number' && (
            <p className="text-zinc-400 text-xs">Сумма: {me.total}</p>
          )}
        </motion.div>
      )}

      {state.lastAction && (
        <p className="text-center text-zinc-400 text-xs mb-3">
          {state.players[state.lastAction.player]?.name}: {actionLabel(state.lastAction)}
        </p>
      )}

      {state.phase === 'playing' && (
        <div className="grid grid-cols-3 gap-2 mb-2">
          <motion.button whileTap={{ scale: 0.94 }} whileHover={state.actions.includes('hit') ? { scale: 1.02 } : {}}
            disabled={!state.actions.includes('hit')} onClick={() => send({ type: 'action', action: 'hit' })}
            className="bg-blue-600 disabled:bg-zinc-700 text-white text-sm font-semibold py-2 rounded-lg">Ещё карту</motion.button>
          <motion.button whileTap={{ scale: 0.94 }} whileHover={state.actions.includes('stand') ? { scale: 1.02 } : {}}
            disabled={!state.actions.includes('stand')} onClick={() => send({ type: 'action', action: 'stand' })}
            className="bg-zinc-700 disabled:bg-zinc-800 text-white text-sm font-semibold py-2 rounded-lg">Хватит</motion.button>
          <motion.button whileTap={{ scale: 0.94 }} whileHover={state.actions.includes('double') ? { scale: 1.02 } : {}}
            disabled={!state.actions.includes('double')} onClick={() => send({ type: 'action', action: 'double' })}
            className="bg-yellow-600 disabled:bg-zinc-700 text-black disabled:text-zinc-400 text-sm font-semibold py-2 rounded-lg">Удвоить</motion.button>
        </div>
      )}

      {state.phase === 'showdown' && (
        <div className="bg-zinc-900 rounded-xl p-4">
          {me?.result && (
            <motion.div
              initial={{ opacity: 0, y: 10, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              className={`rounded-lg px-3 py-2 mb-3 text-center ${
                me.result.outcome === 'loss' ? 'bg-red-500/15 border border-red-400/30' :
                  me.result.outcome === 'push' ? 'bg-zinc-700/40 border border-zinc-500/30' :
                    me.result.outcome === 'blackjack' ? 'bg-yellow-500/20 border border-yellow-400/40' :
                      'bg-green-500/15 border border-green-400/30'
              }`}
            >
              <p className={`font-semibold text-sm ${
                me.result.outcome === 'loss' ? 'text-red-300' :
                  me.result.outcome === 'push' ? 'text-zinc-200' :
                    me.result.outcome === 'blackjack' ? 'text-yellow-300' :
                      'text-green-300'
              }`}>
                {outcomeLabel(me.result.outcome)}
              </p>
              <p className="text-zinc-300 text-xs">
                Ставка: {me.result.bet} · Выплата: {me.result.payout} фишек
              </p>
            </motion.div>
          )}
          {!myReady ? (
            <button onClick={() => send({ type: 'ready' })} className="w-full bg-green-600 hover:bg-green-500 text-white font-semibold text-sm py-2.5 rounded-lg">
              Следующая раздача
            </button>
          ) : (
            <p className="text-green-400 text-center text-sm font-semibold">Готово ✓</p>
          )}
          <p className="text-zinc-500 text-center text-[11px] mt-2">
            {(state.readyPlayers || []).length} игроков готовы
          </p>
        </div>
      )}
    </div>
  )
}

export default function BlackjackPage() {
  const { userId, initData } = useAuth()
  const { sound, muted, toggleMute } = useCasinoSounds()
  const [view, setView] = useState('lobby')
  const [rooms, setRooms] = useState([])
  const [room, setRoom] = useState(null)
  const [state, setState] = useState(null)
  const [monkeyBalance, setMonkeyBalance] = useState(null)
  const [error, setError] = useState(null)
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)

  const send = useCallback((msg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/blackjack`)
    wsRef.current = ws
    ws.onopen = () => {
      setConnected(true)
      ws.send(JSON.stringify({ type: 'auth', initData }))
      ws.send(JSON.stringify({ type: 'list_rooms' }))
    }
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      switch (data.type) {
        case 'rooms_list':
          setRooms(data.rooms || [])
          break
        case 'room_joined':
          setRoom(data.room)
          setView('waiting')
          if (data.monkeysBalance !== undefined && data.monkeysBalance !== null) setMonkeyBalance(data.monkeysBalance)
          break
        case 'room_updated':
          setRoom(data.room)
          break
        case 'game_state':
          setState(data.state)
          setView('game')
          break
        case 'player_ready':
          setState(prev => prev ? { ...prev, readyPlayers: data.readyPlayers } : prev)
          break
        case 'left_room':
          setRoom(null)
          setState(null)
          setView('lobby')
          if (data.monkeysBalance !== undefined && data.monkeysBalance !== null) setMonkeyBalance(data.monkeysBalance)
          send({ type: 'list_rooms' })
          break
        case 'game_over':
          setState(null)
          setView('waiting')
          break
        case 'reconnected':
          setRoom(data.room)
          setView(data.room?.started ? 'game' : 'waiting')
          break
        case 'error':
          setError(data.message || 'Ошибка')
          setTimeout(() => setError(null), 2500)
          break
        default:
          break
      }
    }
    ws.onclose = () => {
      setConnected(false)
      reconnectRef.current = setTimeout(connect, 2000)
    }
    ws.onerror = () => ws.close()
  }, [initData, send])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  const leave = () => send({ type: 'leave_room' })

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="px-4 pt-6 pb-4 max-w-3xl mx-auto">
      {!connected && <p className="text-zinc-500 text-sm text-center py-6">Подключение...</p>}
      <button
        onClick={toggleMute}
        className="fixed top-4 right-4 z-50 bg-zinc-900/90 border border-zinc-700 text-white/80 hover:text-white text-sm rounded-full w-9 h-9 flex items-center justify-center"
        title={muted ? 'Включить звук' : 'Выключить звук'}
      >
        {muted ? '🔇' : '🔊'}
      </button>
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="fixed top-4 left-4 right-4 z-50 bg-red-600/90 text-white text-sm rounded-lg px-4 py-2 text-center"
          >
            {error}
          </motion.div>
        )}
      </AnimatePresence>
      {connected && view === 'lobby' && <Lobby rooms={rooms} send={send} monkeyBalance={monkeyBalance} />}
      {connected && view === 'waiting' && <WaitingRoom room={room} send={send} userId={userId} monkeyBalance={monkeyBalance} />}
      {connected && view === 'game' && <Table state={state} send={send} userId={userId} onLeave={leave} sound={sound} />}
    </motion.div>
  )
}
