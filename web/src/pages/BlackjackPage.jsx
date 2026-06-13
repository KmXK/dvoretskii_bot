import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Bot, Coins, Crown, Play, RefreshCw, Spade, Users, Volume2, VolumeX,
} from 'lucide-react'
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

  const inputCls = 'w-full rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white tabular-nums outline-none focus:bg-white/10 transition-colors'

  return (
    <div className="max-w-md mx-auto">
      <div className="flex items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="font-display text-2xl font-extrabold tracking-tight text-white flex items-center gap-2">
            <Spade size={22} className="text-gold" strokeWidth={2} fill="currentColor" />
            Блэкджек
          </h1>
          <p className="text-spotify-text text-sm mt-0.5">Играй против ботов и реальных игроков</p>
        </div>
        {Number.isFinite(monkeyBalance) && (
          <span className="shrink-0 inline-flex items-center gap-1.5 rounded-full bg-spotify-green/15 px-3 py-1.5 text-sm font-semibold text-spotify-green tabular-nums">
            {monkeyBalance} 🐵
          </span>
        )}
      </div>

      <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4 mb-4">
        <p className="text-xs font-bold uppercase tracking-[0.08em] text-spotify-text mb-3">Создать комнату</p>
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="Название комнаты"
          className="w-full mb-2.5 rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white placeholder:text-spotify-text/70 outline-none focus:bg-white/10 transition-colors"
          maxLength={40}
        />
        <div className="grid grid-cols-2 gap-2.5 mb-3">
          <label className="text-[11px] text-spotify-text flex flex-col gap-1">
            <span className="inline-flex items-center gap-1"><Coins size={12} className="text-spotify-green" /> Стартовый стек</span>
            <input
              type="number"
              value={startChips}
              onChange={e => setStartChips(Math.max(100, Number(e.target.value) || 100))}
              className={inputCls}
            />
          </label>
          <label className="text-[11px] text-spotify-text flex flex-col gap-1">
            <span className="inline-flex items-center gap-1"><Coins size={12} className="text-spotify-green" /> Ставка за раунд</span>
            <input
              type="number"
              value={tableBet}
              onChange={e => setTableBet(Math.max(5, Number(e.target.value) || 5))}
              className={inputCls}
            />
          </label>
          <label className="text-[11px] text-spotify-text flex flex-col gap-1">
            <span className="inline-flex items-center gap-1"><Bot size={12} className="text-indigo" /> Ботов за столом</span>
            <input
              type="number"
              value={botCount}
              onChange={e => setBotCount(Math.max(0, Math.min(5, Number(e.target.value) || 0)))}
              className={inputCls}
            />
          </label>
          <label className="bg-white/5 rounded-lg px-3 text-xs text-white/90 flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={playForMonkeys}
              onChange={e => setPlayForMonkeys(e.target.checked)}
              className="accent-gold w-4 h-4"
            />
            Обезьянки → фишки
          </label>
        </div>
        <motion.button
          whileTap={{ scale: 0.98 }}
          onClick={create}
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
        <div className="flex flex-col gap-2">
          {rooms.length === 0 && (
            <div className="text-center py-8">
              <Spade size={36} className="mx-auto mb-2 text-spotify-text/50" strokeWidth={1.75} />
              <p className="text-spotify-text text-sm">Нет доступных комнат — создай первую</p>
            </div>
          )}
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
                  <p className="text-white text-sm font-medium truncate">{r.name}</p>
                  <p className="text-spotify-text text-xs flex items-center gap-2 mt-0.5 flex-wrap">
                    <span className="inline-flex items-center gap-1"><Users size={12} />{r.playerCount}/{r.maxPlayers}</span>
                    <span className="inline-flex items-center gap-1 text-spotify-green tabular-nums"><Coins size={12} />{r.tableBet}</span>
                    <span className="tabular-nums">стек {r.startChips}</span>
                    {r.playForMonkeys && (
                      <span className="text-spotify-green tabular-nums">🐵{Math.floor((r.startChips || 0) / (r.monkeyChipRate || 10))}</span>
                    )}
                    {r.started && <span className="text-gold">В игре</span>}
                  </p>
                </div>
                <motion.button
                  whileTap={{ scale: 0.94 }}
                  onClick={() => send({ type: 'join_room', roomId: r.id })}
                  className={`shrink-0 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                    r.started ? 'bg-indigo-soft text-indigo hover:brightness-110' : 'bg-gold text-spotify-black hover:bg-gold-2'
                  }`}
                >
                  {r.started ? 'Наблюдать' : 'Войти'}
                </motion.button>
              </motion.div>
            ))}
          </AnimatePresence>
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
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={() => setShowLeave(false)}>
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.9, opacity: 0 }}
              className="bg-spotify-gray border border-white/10 rounded-2xl p-5 w-full max-w-xs"
              onClick={e => e.stopPropagation()}
            >
              <h3 className="font-display text-white font-extrabold text-base mb-3">Покинуть комнату?</h3>
              <div className="flex gap-2">
                <motion.button whileTap={{ scale: 0.96 }} onClick={() => setShowLeave(false)} className="flex-1 bg-white/5 hover:bg-white/10 text-white text-sm font-semibold py-2.5 rounded-xl transition-colors">Остаться</motion.button>
                <motion.button whileTap={{ scale: 0.96 }} onClick={() => send({ type: 'leave_room' })} className="flex-1 bg-red-500/90 hover:bg-red-500 text-white text-sm font-semibold py-2.5 rounded-xl transition-colors">Выйти</motion.button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex items-center justify-between gap-3 mb-3">
        <h1 className="font-display text-lg font-extrabold tracking-tight text-white truncate">{room.name}</h1>
        <div className="flex items-center gap-2 shrink-0">
          {room.playForMonkeys && Number.isFinite(monkeyBalance) && (
            <span className="inline-flex items-center gap-1 rounded-full bg-spotify-green/15 px-2.5 py-1 text-xs font-semibold text-spotify-green tabular-nums">
              {monkeyBalance} 🐵
            </span>
          )}
          <button onClick={() => setShowLeave(true)} className="text-red-400 text-xs hover:text-red-300 transition-colors">Выйти</button>
        </div>
      </div>

      <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4 mb-4">
        <p className="text-xs font-bold uppercase tracking-[0.08em] text-spotify-text mb-3 flex items-center gap-1.5">
          <Coins size={14} strokeWidth={2} className="text-spotify-green" />
          Параметры стола
        </p>
        <div className="flex flex-col gap-1.5 text-xs text-spotify-text">
          <p>Стартовые фишки: <span className="text-white/90 tabular-nums">{room.startChips}</span></p>
          <p>Ставка стола: <span className="text-white/90 tabular-nums">{room.tableBet}</span></p>
          <p>Режим: <span className="text-white/90">{room.playForMonkeys ? 'Обезьянки → фишки' : 'Фишки'}</span></p>
        </div>
      </div>

      <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4 mb-4">
        <p className="text-xs font-bold uppercase tracking-[0.08em] text-spotify-text mb-3 flex items-center gap-1.5">
          <Users size={14} strokeWidth={2} />
          Игроки
        </p>
        <div className="flex flex-col gap-2">
          {(room.players || []).map(p => (
            <div key={p.id} className="flex items-center gap-2.5 bg-spotify-dark rounded-xl px-3 py-2">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-bold ${p.isBot ? 'bg-indigo' : 'bg-spotify-green'}`}>
                {p.isBot ? <Bot size={16} /> : p.name[0]?.toUpperCase()}
              </div>
              <span className={`text-sm ${p.id === userId ? 'text-spotify-green font-semibold' : p.isBot ? 'text-indigo' : 'text-white'}`}>{p.name}</span>
              {p.id === room.creator_id && (
                <span className="ml-auto inline-flex items-center gap-1 text-[10px] bg-gold-soft text-gold px-2 py-0.5 rounded-full">
                  <Crown size={11} /> создатель
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      {isCreator ? (
        <motion.button
          whileTap={{ scale: 0.98 }}
          onClick={() => send({ type: 'start_game' })}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-gold py-3 text-sm font-semibold text-spotify-black transition-colors hover:bg-gold-2"
        >
          <Play size={16} strokeWidth={2.5} />
          Начать игру
        </motion.button>
      ) : (
        <p className="text-spotify-text text-sm text-center py-3">Ждём старта от создателя…</p>
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
      {!connected && <p className="text-spotify-text text-sm text-center py-6">Подключение…</p>}
      <button
        onClick={toggleMute}
        className="fixed top-4 right-4 z-50 bg-spotify-gray/90 border border-white/10 text-spotify-text hover:text-white rounded-full w-9 h-9 flex items-center justify-center transition-colors"
        title={muted ? 'Включить звук' : 'Выключить звук'}
      >
        {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
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
