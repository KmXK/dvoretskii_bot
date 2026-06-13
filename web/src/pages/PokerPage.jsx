import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Bot, ChevronDown, Crown, Play, RefreshCw, Send, Settings2,
  Spade, Trophy, Users,
} from 'lucide-react'
import BackButton from '../components/BackButton'
import { useAuth } from '../context/useAuth'
import { api } from '../api/client'

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

const SUIT_SYMBOL = { h: '♥', d: '♦', c: '♣', s: '♠' }
const HAND_NAMES_RU = {
  'High Card': 'Старшая карта',
  'Pair': 'Пара',
  'Two Pair': 'Две пары',
  'Three of a Kind': 'Тройка',
  'Straight': 'Стрит',
  'Flush': 'Флеш',
  'Full House': 'Фулл-хаус',
  'Four of a Kind': 'Каре',
  'Straight Flush': 'Стрит-флеш',
}
const handNameRu = (name) => HAND_NAMES_RU[name] || name

function triggerHaptic(kind = 'warning') {
  try {
    window?.Telegram?.WebApp?.HapticFeedback?.notificationOccurred(kind)
  } catch { /* not in telegram */ }
}
const DIFFICULTY_OPTIONS = [
  { value: 'easy', label: 'Легко', color: 'text-green-400' },
  { value: 'medium', label: 'Средне', color: 'text-yellow-400' },
  { value: 'hard', label: 'Сложно', color: 'text-red-400' },
]

function PokerCard({ rank, suit, hidden = false, small = false }) {
  const w = small ? 'w-10 h-14' : 'w-14 h-20'
  if (hidden) {
    return (
      <div className={`${w} rounded-lg bg-gradient-to-br from-green-700 to-green-900 border border-green-600 shadow-md flex items-center justify-center`}>
        <span className="text-green-400 text-sm font-bold">♠</span>
      </div>
    )
  }
  const isRed = suit === 'h' || suit === 'd'
  return (
    <div className={`${w} rounded-lg bg-white shadow-md flex flex-col items-center justify-center gap-0 ${isRed ? 'text-red-500' : 'text-zinc-900'}`}>
      <span className={`${small ? 'text-base' : 'text-xl'} font-bold leading-none`}>{rank}</span>
      <span className={`${small ? 'text-sm' : 'text-base'} leading-none`}>{SUIT_SYMBOL[suit]}</span>
    </div>
  )
}

function PlayerSeat({ player, isDealer, isSmallBlind, isBigBlind, isCurrent, isMe, showdown, index, actionBadge, secondsLeft, turnTotal }) {
  let border = 'border-zinc-700'
  if (player.folded) border = 'border-zinc-800'
  if (isMe) border = 'border-green-500/60'
  if (isCurrent) border = 'border-yellow-400'

  const showTimer = isCurrent && secondsLeft != null && !player.folded
  const timerFrac = showTimer && turnTotal > 0 ? Math.max(0, Math.min(1, secondsLeft / turnTotal)) : 0
  const timerLow = showTimer && secondsLeft <= 5

  let bg = 'bg-zinc-800/80'
  if (player.folded) bg = 'bg-zinc-900/60'

  let statusText = '\u00A0'
  let statusClass = 'text-transparent'
  if (player.allIn && !player.folded) {
    statusText = 'Олл-ин'
    statusClass = 'font-bold text-red-400 uppercase'
  } else if (player.folded) {
    statusText = 'Фолд'
    statusClass = 'text-zinc-500'
  } else if (player.bet > 0) {
    statusText = `Ставка: ${player.bet}`
    statusClass = 'text-yellow-300'
  }

  const showCards = !isMe && !player.sittingOut && !player.folded && !showdown
  const showShowdownCards = showdown && player.cards && player.cards.length > 0

  return (
    <div
      style={isCurrent ? { boxShadow: '0 0 16px 2px rgba(250,204,21,0.35)' } : undefined}
      className={`relative rounded-xl border-2 ${border} ${bg} p-2 w-[110px] h-[120px] flex flex-col items-center transition-shadow duration-400`}
    >
      {isDealer && (
        <span className="absolute -top-2 -left-2 bg-yellow-400 text-black text-[10px] font-bold rounded-full w-5 h-5 flex items-center justify-center shadow">D</span>
      )}
      {(isSmallBlind || isBigBlind) && (
        <span className={`absolute -bottom-2 -left-2 text-black text-[9px] font-bold rounded-full w-5 h-5 flex items-center justify-center shadow ${isBigBlind ? 'bg-indigo-400' : 'bg-zinc-300'}`}>
          {isBigBlind ? 'BB' : 'SB'}
        </span>
      )}
      {isCurrent && (
        <span className="absolute -top-2 -right-2 bg-yellow-400 text-black text-[9px] font-bold rounded-full px-1.5 py-0.5 shadow flex items-center gap-0.5">
          {showTimer && <span className="tabular-nums">{secondsLeft}</span>}
          ХОД
        </span>
      )}
      {showTimer && (
        <div className="absolute bottom-0 left-0 right-0 h-1 rounded-b-xl bg-black/30 overflow-hidden">
          <div
            className={`h-full transition-[width] duration-1000 ease-linear ${timerLow ? 'bg-red-500' : 'bg-yellow-400'}`}
            style={{ width: `${timerFrac * 100}%` }}
          />
        </div>
      )}
      <span className={`text-xs font-semibold truncate max-w-[90px] ${isMe ? 'text-green-400' : player.isBot ? 'text-blue-300' : 'text-white'}`}>
        {player.name}
      </span>
      <span className="text-[11px] text-zinc-400">{player.chips} фишек</span>
      <span className={`text-[10px] h-[14px] leading-[14px] ${statusClass}`}>{statusText}</span>

      <div className="flex gap-0.5 mt-auto h-[56px] items-end">
        {showShowdownCards && player.cards.map((c, i) => <PokerCard key={i} rank={c.rank} suit={c.suit} small />)}
        {showCards && <><PokerCard hidden small /><PokerCard hidden small /></>}
      </div>

      <AnimatePresence>
        {actionBadge && (
          <motion.div
            key="action-badge"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="absolute inset-0 z-10 rounded-xl bg-black/70 backdrop-blur-sm flex items-center justify-center"
          >
            <span className={`text-sm font-bold ${actionColor(actionBadge.action)}`}>
              {actionLabel(actionBadge)}
            </span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function LeaveConfirmDialog({ onConfirm, onCancel }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      onClick={onCancel}
    >
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.9, opacity: 0 }}
        className="bg-spotify-gray border border-white/10 rounded-2xl p-5 max-w-xs w-full"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="font-display text-white font-extrabold text-base mb-2">Покинуть стол?</h3>
        <p className="text-spotify-text text-sm mb-4">Ваши фишки сохранятся, если вы вернётесь в эту комнату.</p>
        <div className="flex gap-2">
          <motion.button whileTap={{ scale: 0.96 }} onClick={onCancel} className="flex-1 bg-white/5 hover:bg-white/10 text-white text-sm font-semibold py-2.5 rounded-xl transition-colors">
            Остаться
          </motion.button>
          <motion.button whileTap={{ scale: 0.96 }} onClick={onConfirm} className="flex-1 bg-red-500/90 hover:bg-red-500 text-white text-sm font-semibold py-2.5 rounded-xl transition-colors">
            Выйти
          </motion.button>
        </div>
      </motion.div>
    </motion.div>
  )
}

function StatCell({ value, label, color = 'text-white' }) {
  return (
    <div className="bg-spotify-dark rounded-xl p-2.5 text-center">
      <div className={`font-display text-xl font-extrabold tabular-nums ${color}`}>{value}</div>
      <div className="text-[10px] text-spotify-text mt-0.5">{label}</div>
    </div>
  )
}

function PokerStatsBlock({ stats }) {
  const [expanded, setExpanded] = useState(false)
  const s = stats
  const winRate = s.hands > 0 ? Math.round((s.handsWon / s.hands) * 100) : 0
  const netChips = (s.chipsWon || 0) - (s.chipsLost || 0)

  return (
    <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4 mb-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between w-full text-left mb-3"
      >
        <span className="text-xs font-bold uppercase tracking-[0.08em] text-spotify-text flex items-center gap-1.5">
          <Trophy size={14} strokeWidth={2} className="text-gold" />
          Ваша статистика
        </span>
        <motion.span animate={{ rotate: expanded ? 180 : 0 }} className="text-spotify-text">
          <ChevronDown size={16} />
        </motion.span>
      </button>

      <div className="grid grid-cols-3 gap-2">
        <StatCell value={s.games || 0} label="Игр" />
        <StatCell value={s.gamesWon || 0} label="Побед" color="text-gold" />
        <StatCell value={s.hands || 0} label="Раздач" />
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="grid grid-cols-3 gap-2 mt-2">
              <StatCell value={s.handsWon || 0} label="Выиграно" color="text-spotify-green" />
              <StatCell value={s.handsLost || 0} label="Проиграно" color="text-red-400" />
              <StatCell value={s.handsFolded || 0} label="Фолды" color="text-spotify-text" />
            </div>

            <div className="grid grid-cols-3 gap-2 mt-2">
              <StatCell value={s.chipsWon || 0} label="Выиграно фишек" color="text-spotify-green" />
              <StatCell value={s.chipsLost || 0} label="Проиграно фишек" color="text-red-400" />
              <StatCell value={netChips} label="Итог" color={netChips >= 0 ? 'text-spotify-green' : 'text-red-400'} />
            </div>

            {s.hands > 0 && (
              <div className="mt-3 bg-spotify-dark rounded-xl p-2.5">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-spotify-text text-[11px]">Винрейт</span>
                  <span className="text-white text-xs font-bold tabular-nums">{winRate}%</span>
                </div>
                <div className="w-full bg-white/10 rounded-full h-1.5 overflow-hidden">
                  <div
                    className="bg-spotify-green h-1.5 rounded-full transition-all"
                    style={{ width: `${winRate}%` }}
                  />
                </div>
              </div>
            )}

            {s.combos && s.combos.length > 0 && (
              <div className="mt-3">
                <h3 className="text-spotify-text text-[11px] mb-2">Комбинации</h3>
                <div className="flex flex-col gap-1">
                  {s.combos.map((c, i) => (
                    <div key={i} className="flex items-center justify-between bg-spotify-dark rounded-xl px-2.5 py-1.5">
                      <span className="text-white/90 text-xs">{c.name}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-spotify-text text-[10px]">собрано {c.collected}</span>
                        <span className="text-spotify-green text-[10px] font-semibold">выиграно {c.won}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

const BLIND_INTERVAL_OPTIONS = [
  { value: 2, label: '2 мин' },
  { value: 3, label: '3 мин' },
  { value: 5, label: '5 мин' },
  { value: 10, label: '10 мин' },
  { value: 15, label: '15 мин' },
]

function Lobby({ rooms, send, userId, pokerStats, monkeyBalance }) {
  const [name, setName] = useState('')
  const [sb, setSb] = useState(10)
  const [bb, setBb] = useState(20)
  const [sc, setSc] = useState(1000)
  const [bc, setBc] = useState(0)
  const [bd, setBd] = useState('medium')
  const [biEnabled, setBiEnabled] = useState(true)
  const [biInterval, setBiInterval] = useState(5)
  const [playForMonkeys, setPlayForMonkeys] = useState(false)
  const [showSettings, setShowSettings] = useState(false)

  const create = () => {
    send({
      type: 'create_room', name: name.trim() || undefined,
      smallBlind: sb, bigBlind: bb, startChips: sc,
      botCount: Number(bc) || 0, botDifficulty: bd,
      blindIncreaseEnabled: biEnabled, blindIncreaseInterval: biInterval,
      playForMonkeys,
    })
    setName('')
  }

  const refresh = () => send({ type: 'list_rooms' })

  const inputCls = 'w-full rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white tabular-nums outline-none focus:bg-white/10 transition-colors'

  return (
    <div className="max-w-md mx-auto">
      <BackButton force />
      <div className="flex items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="font-display text-2xl font-extrabold tracking-tight text-white flex items-center gap-2">
            <Spade size={22} className="text-gold" strokeWidth={2} fill="currentColor" />
            Покер
          </h1>
          <p className="text-spotify-text text-sm mt-0.5">Техасский холдем — создай комнату или войди</p>
        </div>
        {Number.isFinite(monkeyBalance) && (
          <span className="shrink-0 inline-flex items-center gap-1.5 rounded-full bg-spotify-green/15 px-3 py-1.5 text-sm font-semibold text-spotify-green tabular-nums">
            {monkeyBalance} 🐵
          </span>
        )}
      </div>

      {pokerStats && <PokerStatsBlock stats={pokerStats} />}

      <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4 mb-4">
        <p className="text-xs font-bold uppercase tracking-[0.08em] text-spotify-text mb-3">Создать комнату</p>
        <div className="flex gap-2 mb-2.5">
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Название комнаты"
            className="flex-1 rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white placeholder:text-spotify-text/70 outline-none focus:bg-white/10 transition-colors"
            maxLength={40}
            onKeyDown={e => e.key === 'Enter' && create()}
          />
          <motion.button
            whileTap={{ scale: 0.96 }}
            onClick={create}
            className="shrink-0 inline-flex items-center gap-1.5 rounded-xl bg-gold px-4 text-sm font-semibold text-spotify-black transition-colors hover:bg-gold-2"
          >
            <Play size={15} strokeWidth={2.5} />
            Создать
          </motion.button>
        </div>
        <button
          onClick={() => setShowSettings(!showSettings)}
          className="inline-flex items-center gap-1.5 text-spotify-text hover:text-white text-xs transition-colors"
        >
          <Settings2 size={13} strokeWidth={2} />
          {showSettings ? 'Скрыть настройки' : 'Настройки'}
          <motion.span animate={{ rotate: showSettings ? 180 : 0 }} className="inline-flex">
            <ChevronDown size={13} />
          </motion.span>
        </button>
        <AnimatePresence>
          {showSettings && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div className="grid grid-cols-2 gap-2.5 mt-3">
                <div>
                  <label className="text-spotify-text text-[10px] block mb-1">Малый блайнд</label>
                  <input
                    type="number"
                    value={sb}
                    onChange={e => { const v = Math.max(1, Number(e.target.value)); setSb(v); if (bb < v * 2) setBb(v * 2) }}
                    className={inputCls}
                    min={1}
                  />
                </div>
                <div>
                  <label className="text-spotify-text text-[10px] block mb-1">Большой блайнд</label>
                  <input
                    type="number"
                    value={bb}
                    onChange={e => setBb(Math.max(sb * 2, Number(e.target.value)))}
                    className={inputCls}
                    min={sb * 2}
                  />
                </div>
                <div>
                  <label className="text-spotify-text text-[10px] block mb-1">Стартовые фишки</label>
                  <input
                    type="number"
                    value={sc}
                    onChange={e => {
                      const minChips = Math.max(bb * 10, playForMonkeys ? 10 : 0)
                      const raw = Math.max(minChips, Number(e.target.value))
                      setSc(playForMonkeys ? Math.floor(raw / 10) * 10 : raw)
                    }}
                    className={inputCls}
                    min={bb * 10}
                    step={playForMonkeys ? 10 : 100}
                  />
                  {playForMonkeys && (
                    <p className="text-spotify-text text-[10px] mt-1">
                      Бай-ин: {Math.floor(sc / 10)} 🐵 ({sc} фишек)
                    </p>
                  )}
                </div>
                <div>
                  <label className="text-spotify-text text-[10px] block mb-1">Боты</label>
                  <input
                    type="number"
                    value={bc}
                    onChange={e => setBc(e.target.value === '' ? '' : Math.min(7, Number(e.target.value)))}
                    onBlur={() => setBc(prev => Math.max(0, Math.min(7, Number(prev) || 0)))}
                    className={inputCls}
                    min={0}
                    max={7}
                  />
                </div>
                {Number(bc) > 0 && (
                  <div className="col-span-2">
                    <label className="text-spotify-text text-[10px] block mb-1">Сложность ботов</label>
                    <div className="grid grid-cols-3 gap-2">
                      {DIFFICULTY_OPTIONS.map(opt => (
                        <SegButton key={opt.value} tone="indigo" active={bd === opt.value} onClick={() => setBd(opt.value)}>
                          {opt.label}
                        </SegButton>
                      ))}
                    </div>
                  </div>
                )}
                <div className="col-span-2">
                  <label className="text-spotify-text text-[10px] block mb-1">Валюта</label>
                  <div className="grid grid-cols-2 gap-2">
                    <SegButton tone="green" active={!playForMonkeys} onClick={() => setPlayForMonkeys(false)}>
                      Только фишки
                    </SegButton>
                    <SegButton
                      tone="green"
                      active={playForMonkeys}
                      onClick={() => {
                        setPlayForMonkeys(true)
                        setSc(prev => Math.floor(Math.max(bb * 10, prev) / 10) * 10)
                      }}
                    >
                      Обезьянки → фишки
                    </SegButton>
                  </div>
                  {playForMonkeys && (
                    <p className="text-spotify-text text-[10px] mt-1">Курс: 1 🐵 = 10 фишек. Обмен при входе в комнату.</p>
                  )}
                </div>
                <div className="col-span-2">
                  <label className="flex items-center gap-2 cursor-pointer text-sm text-white/90">
                    <input
                      type="checkbox"
                      checked={biEnabled}
                      onChange={e => setBiEnabled(e.target.checked)}
                      className="accent-gold w-4 h-4"
                    />
                    Автоувеличение блайндов
                  </label>
                </div>
                {biEnabled && (
                  <div className="col-span-2">
                    <label className="text-spotify-text text-[10px] block mb-1">Повышать каждые</label>
                    <div className="grid grid-cols-5 gap-1.5">
                      {BLIND_INTERVAL_OPTIONS.map(opt => (
                        <SegButton key={opt.value} active={biInterval === opt.value} onClick={() => setBiInterval(opt.value)} className="px-0">
                          {opt.label}
                        </SegButton>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4">
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs font-bold uppercase tracking-[0.08em] text-spotify-text flex items-center gap-1.5">
            <Users size={14} strokeWidth={2} />
            Комнаты
          </p>
          <motion.button
            whileTap={{ scale: 0.9, rotate: -90 }}
            onClick={refresh}
            className="text-spotify-text hover:text-white transition-colors"
            aria-label="Обновить"
          >
            <RefreshCw size={16} strokeWidth={2} />
          </motion.button>
        </div>

        {rooms.length === 0 && (
          <div className="text-center py-8">
            <Spade size={36} className="mx-auto mb-2 text-spotify-text/50" strokeWidth={1.75} />
            <p className="text-spotify-text text-sm">Нет доступных комнат — создай первую</p>
          </div>
        )}

        <div className="flex flex-col gap-2">
          <AnimatePresence initial={false}>
            {rooms.map((room, i) => (
              <motion.div
                key={room.id}
                layout
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.96 }}
                transition={{ delay: Math.min(i * 0.04, 0.2), type: 'spring', stiffness: 420, damping: 30 }}
                className="flex items-center justify-between gap-3 rounded-xl bg-spotify-dark px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="text-white text-sm font-medium truncate">{room.name}</p>
                  <p className="text-spotify-text text-xs flex items-center gap-2 mt-0.5 flex-wrap">
                    <span className="inline-flex items-center gap-1"><Users size={12} />{room.playerCount}/{room.maxPlayers}</span>
                    {room.botCount > 0 && <span className="inline-flex items-center gap-1 text-indigo"><Bot size={12} />{room.botCount}</span>}
                    {room.playForMonkeys && (
                      <span className="inline-flex items-center gap-1 text-spotify-green tabular-nums">
                        🐵{Math.floor((room.startChips || 0) / (room.monkeyChipRate || 10))}
                      </span>
                    )}
                    <span className="tabular-nums">{room.smallBlind}/{room.bigBlind}{room.blindIncreaseEnabled ? ' ↑' : ''}</span>
                    {room.started && <span className="text-gold">В игре</span>}
                  </p>
                </div>
                <motion.button
                  whileTap={{ scale: 0.94 }}
                  onClick={() => send({ type: 'join_room', roomId: room.id })}
                  disabled={room.playerCount >= room.maxPlayers}
                  className={`shrink-0 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                    room.started ? 'bg-indigo-soft text-indigo hover:brightness-110' : 'bg-gold text-spotify-black hover:bg-gold-2'
                  } disabled:bg-white/5 disabled:text-spotify-text`}
                >
                  {room.started ? 'Наблюдать' : 'Войти'}
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
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    api.get(`/api/user/${userId}/chats`)
      .then(d => setChats(d.chats || []))
      .catch(() => {})
  }, [userId])

  useEffect(() => {
    if (sent && room) {
      api.post('/api/poker/invite/update', {
        roomId: room.id,
        roomName: room.name,
        playerCount: room.playerCount,
        maxPlayers: room.maxPlayers,
      }).catch(() => {})
    }
  }, [room, sent])

  const sendInvites = async () => {
    if (selected.size === 0) return
    setSending(true)
    try {
      await api.post('/api/poker/invite', {
        chatIds: [...selected],
        roomName: room.name,
        roomId: room.id,
        playerCount: room.playerCount,
        maxPlayers: room.maxPlayers,
        creatorName: room.players?.[0]?.name || 'Кто-то',
      })
      setSent(true)
    } catch { /* noop */ }
    setSending(false)
  }

  const toggle = (id) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  if (chats.length === 0) return null

  return (
    <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4 mb-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between w-full text-left"
      >
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
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="flex flex-col gap-2 mt-3">
              {chats.map(c => (
                <label key={c.id} className="flex items-center gap-2 bg-spotify-dark rounded-lg px-3 py-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selected.has(c.id)}
                    onChange={() => toggle(c.id)}
                    className="accent-indigo w-4 h-4"
                    disabled={sent}
                  />
                  <span className="text-white text-sm truncate">{c.name}</span>
                </label>
              ))}
            </div>
            {!sent && (
              <motion.button
                whileTap={{ scale: 0.98 }}
                onClick={sendInvites}
                disabled={selected.size === 0 || sending}
                className="w-full mt-3 flex items-center justify-center gap-2 rounded-xl bg-indigo py-2.5 text-sm font-semibold text-white transition-opacity disabled:opacity-40"
              >
                <Send size={15} />
                {sending ? 'Отправка...' : `Отправить (${selected.size})`}
              </motion.button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function WaitingRoom({ room, send, userId, monkeyBalance }) {
  if (!room) return null
  const isCreator = room.creator_id === userId
  const [editBlinds, setEditBlinds] = useState(false)
  const [sb, setSb] = useState(room.smallBlind || 10)
  const [bb, setBb] = useState(room.bigBlind || 20)
  const [sc, setSc] = useState(room.startChips || 1000)
  const [bc, setBc] = useState(room.botCount || 0)
  const [bd, setBd] = useState(room.botDifficulty || 'medium')
  const [biEnabled, setBiEnabled] = useState(room.blindIncreaseEnabled ?? true)
  const [biInterval, setBiInterval] = useState(room.blindIncreaseInterval || 5)
  const [playForMonkeys, setPlayForMonkeys] = useState(room.playForMonkeys || false)
  const [showLeave, setShowLeave] = useState(false)

  useEffect(() => {
    setSb(room.smallBlind || 10)
    setBb(room.bigBlind || 20)
    setSc(room.startChips || 1000)
    setBc(room.botCount || 0)
    setBd(room.botDifficulty || 'medium')
    setBiEnabled(room.blindIncreaseEnabled ?? true)
    setBiInterval(room.blindIncreaseInterval || 5)
    setPlayForMonkeys(room.playForMonkeys || false)
  }, [room.smallBlind, room.bigBlind, room.startChips, room.botCount, room.botDifficulty, room.blindIncreaseEnabled, room.blindIncreaseInterval, room.playForMonkeys])

  const saveSettings = () => {
    send({
      type: 'update_settings', smallBlind: sb, bigBlind: bb, startChips: sc,
      botCount: Number(bc) || 0, botDifficulty: bd,
      blindIncreaseEnabled: biEnabled, blindIncreaseInterval: biInterval,
      playForMonkeys,
    })
    setEditBlinds(false)
  }

  const inputCls = 'w-full rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white tabular-nums outline-none focus:bg-white/10 transition-colors'

  return (
    <div className="max-w-md mx-auto">
      <AnimatePresence>
        {showLeave && (
          <LeaveConfirmDialog
            onConfirm={() => { send({ type: 'leave_room' }); setShowLeave(false) }}
            onCancel={() => setShowLeave(false)}
          />
        )}
      </AnimatePresence>

      <div className="flex items-center justify-between gap-3 mb-3">
        <h1 className="font-display text-lg font-extrabold tracking-tight text-white truncate">{room.name}</h1>
        <div className="flex items-center gap-2 shrink-0">
          {playForMonkeys && Number.isFinite(monkeyBalance) && (
            <span className="inline-flex items-center gap-1 rounded-full bg-spotify-green/15 px-2.5 py-1 text-xs font-semibold text-spotify-green tabular-nums">
              {monkeyBalance} 🐵
            </span>
          )}
          <button onClick={() => setShowLeave(true)} className="text-red-400 hover:text-red-300 text-xs transition-colors">
            Выйти
          </button>
        </div>
      </div>

      <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4 mb-4">
        <p className="text-xs font-bold uppercase tracking-[0.08em] text-spotify-text mb-3 flex items-center gap-1.5">
          <Users size={14} strokeWidth={2} />
          Игроки ({room.playerCount}/8)
        </p>
        <div className="flex flex-col gap-2">
          {(room.players || []).map((p) => (
            <div key={p.id} className="flex items-center gap-2.5 bg-spotify-dark rounded-xl px-3 py-2">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-bold ${p.isBot ? 'bg-indigo' : 'bg-spotify-green'}`}>
                {p.isBot ? <Bot size={16} /> : p.name[0]?.toUpperCase()}
              </div>
              <span className={`text-sm ${p.id === userId ? 'text-spotify-green font-semibold' : p.isBot ? 'text-indigo' : 'text-white'}`}>
                {p.name}
              </span>
              {p.id === room.creator_id && (
                <span className="ml-auto inline-flex items-center gap-1 text-[10px] bg-gold-soft text-gold px-2 py-0.5 rounded-full">
                  <Crown size={11} /> Создатель
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      <InviteBlock room={room} userId={userId} />

      <div className="rounded-2xl border border-white/5 bg-spotify-gray p-4 mb-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-bold uppercase tracking-[0.08em] text-spotify-text flex items-center gap-1.5">
            <Settings2 size={14} strokeWidth={2} />
            Настройки
          </span>
          {isCreator && !editBlinds && (
            <button onClick={() => setEditBlinds(true)} className="text-gold text-xs hover:text-gold-2 transition-colors">
              Изменить
            </button>
          )}
        </div>

        {editBlinds && isCreator ? (
          <div className="flex flex-col gap-2.5">
            <div className="grid grid-cols-2 gap-2.5">
              <div>
                <label className="text-spotify-text text-[10px] block mb-1">Малый блайнд</label>
                <input type="number" value={sb}
                  onChange={e => { const v = Math.max(1, Number(e.target.value)); setSb(v); if (bb < v * 2) setBb(v * 2) }}
                  className={inputCls} min={1} />
              </div>
              <div>
                <label className="text-spotify-text text-[10px] block mb-1">Большой блайнд</label>
                <input type="number" value={bb}
                  onChange={e => setBb(Math.max(sb * 2, Number(e.target.value)))}
                  className={inputCls} min={sb * 2} />
              </div>
              <div>
                <label className="text-spotify-text text-[10px] block mb-1">Стартовые фишки</label>
                <input type="number" value={sc}
                  onChange={e => {
                    const minChips = Math.max(bb * 10, playForMonkeys ? 10 : 0)
                    const raw = Math.max(minChips, Number(e.target.value))
                    setSc(playForMonkeys ? Math.floor(raw / 10) * 10 : raw)
                  }}
                  className={inputCls} min={bb * 10} step={playForMonkeys ? 10 : 100} />
              </div>
              <div>
                <label className="text-spotify-text text-[10px] block mb-1">Боты</label>
                <input type="number" value={bc}
                  onChange={e => setBc(e.target.value === '' ? '' : Math.min(7, Number(e.target.value)))}
                  onBlur={() => setBc(prev => Math.max(0, Math.min(7, Number(prev) || 0)))}
                  className={inputCls} min={0} max={7} />
              </div>
              {Number(bc) > 0 && (
                <div className="col-span-2">
                  <label className="text-spotify-text text-[10px] block mb-1">Сложность ботов</label>
                  <div className="grid grid-cols-3 gap-2">
                    {DIFFICULTY_OPTIONS.map(opt => (
                      <SegButton key={opt.value} tone="indigo" active={bd === opt.value} onClick={() => setBd(opt.value)}>
                        {opt.label}
                      </SegButton>
                    ))}
                  </div>
                </div>
              )}
              <div className="col-span-2">
                <label className="text-spotify-text text-[10px] block mb-1">Валюта</label>
                <div className="bg-spotify-dark rounded-lg px-3 py-2 flex items-center justify-between">
                  <span className="text-white/90 text-xs">{playForMonkeys ? 'Обезьянки → фишки' : 'Только фишки'}</span>
                  <span className="text-spotify-text text-[10px]">Блокируется после создания</span>
                </div>
              </div>
              <div className="col-span-2">
                <label className="flex items-center gap-2 cursor-pointer text-sm text-white/90">
                  <input
                    type="checkbox"
                    checked={biEnabled}
                    onChange={e => setBiEnabled(e.target.checked)}
                    className="accent-gold w-4 h-4"
                  />
                  Автоувеличение блайндов
                </label>
              </div>
              {biEnabled && (
                <div className="col-span-2">
                  <label className="text-spotify-text text-[10px] block mb-1">Повышать каждые</label>
                  <div className="grid grid-cols-5 gap-1.5">
                    {BLIND_INTERVAL_OPTIONS.map(opt => (
                      <SegButton key={opt.value} active={biInterval === opt.value} onClick={() => setBiInterval(opt.value)} className="px-0">
                        {opt.label}
                      </SegButton>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="flex gap-2">
              <motion.button whileTap={{ scale: 0.97 }} onClick={() => setEditBlinds(false)} className="flex-1 bg-white/5 hover:bg-white/10 text-white text-xs font-semibold py-2 rounded-lg transition-colors">Отмена</motion.button>
              <motion.button whileTap={{ scale: 0.97 }} onClick={saveSettings} className="flex-1 bg-gold hover:bg-gold-2 text-spotify-black text-xs font-semibold py-2 rounded-lg transition-colors">Сохранить</motion.button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5 text-xs text-spotify-text">
            <p>Блайнды: <span className="text-white/90 tabular-nums">{room.smallBlind || 10} / {room.bigBlind || 20}</span></p>
            <p>Стартовые фишки: <span className="text-white/90 tabular-nums">{room.startChips || 1000}</span></p>
            <p>Валюта: <span className="text-white/90">{room.playForMonkeys ? `Обезьянки (бай-ин ${Math.floor((room.startChips || 0) / (room.monkeyChipRate || 10))} 🐵)` : 'Фишки'}</span></p>
            <p>Боты: <span className="text-white/90">{room.botCount || 0}{room.botCount > 0 ? ` (${DIFFICULTY_OPTIONS.find(o => o.value === (room.botDifficulty || 'medium'))?.label || 'Средне'})` : ''}</span></p>
            <p>Повышение блайндов: <span className="text-white/90">{(room.blindIncreaseEnabled ?? true) ? `каждые ${room.blindIncreaseInterval || 5} мин` : 'выключено'}</span></p>
            <p>Мин. игроков: <span className="text-white/90">2 (включая ботов)</span></p>
          </div>
        )}
      </div>

      {isCreator ? (
        <motion.button
          whileTap={{ scale: 0.98 }}
          onClick={() => send({ type: 'start_game' })}
          disabled={(room.playerCount || 0) < 2}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-gold py-3 text-sm font-semibold text-spotify-black transition-colors hover:bg-gold-2 disabled:bg-white/5 disabled:text-spotify-text"
        >
          {(room.playerCount || 0) < 2 ? 'Нужно минимум 2 игрока — добавьте ботов или пригласите' : <><Play size={16} strokeWidth={2.5} /> Начать игру</>}
        </motion.button>
      ) : (
        <div className="text-center text-spotify-text text-sm py-3">Ждём, пока создатель начнёт игру…</div>
      )}
    </div>
  )
}

function GameTable({ state, send, userId, onLeave }) {
  const [raiseAmount, setRaiseAmount] = useState(0)
  const [raiseInput, setRaiseInput] = useState('')
  const [showLeave, setShowLeave] = useState(false)
  const prevPhaseRef = useRef(null)
  const [visibleAction, setVisibleAction] = useState(null)
  const actionTimerRef = useRef(null)

  useEffect(() => {
    if (state) {
      setRaiseAmount(state.minRaiseTo || 0)
      setRaiseInput(String(state.minRaiseTo || 0))
    }
  }, [state?.minRaiseTo, state?.handNum, state?.phase])

  useEffect(() => {
    if (state && prevPhaseRef.current !== state.phase) {
      prevPhaseRef.current = state.phase
    }
  }, [state?.phase])

  const actionKey = state?.lastAction
    ? `${state.lastAction.player}:${state.lastAction.action}:${state.currentIndex}:${state.handNum}`
    : null

  useEffect(() => {
    if (actionKey && state?.lastAction) {
      setVisibleAction(state.lastAction)
      clearTimeout(actionTimerRef.current)
      actionTimerRef.current = setTimeout(() => setVisibleAction(null), 2500)
    } else {
      setVisibleAction(null)
    }
    return () => clearTimeout(actionTimerRef.current)
  }, [actionKey])

  if (!state) return null

  const { phase, community, pot, pots, myHand, currentBet, dealerIndex, currentIndex, myIndex,
    smallBlindIndex, bigBlindIndex, myCards, players, actions, results, lastAction, handNum,
    callAmount, minRaiseTo, readyPlayers, smallBlind, bigBlind, blindIncreaseEnabled, blindLevel,
    blindIncreaseInterval, blindNextIncreaseIn, turnTimeLeft, turnTimeout } = state

  const [blindCountdown, setBlindCountdown] = useState(blindNextIncreaseIn || 0)
  const [turnLeft, setTurnLeft] = useState(null)
  const [foldArmed, setFoldArmed] = useState(false)
  const foldTimerRef = useRef(null)

  useEffect(() => {
    if (!blindIncreaseEnabled || blindNextIncreaseIn == null) {
      setBlindCountdown(0)
      return
    }
    setBlindCountdown(blindNextIncreaseIn)
    const interval = setInterval(() => {
      setBlindCountdown(prev => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(interval)
  }, [blindNextIncreaseIn, blindIncreaseEnabled, handNum])

  useEffect(() => {
    if (turnTimeLeft == null) {
      setTurnLeft(null)
      return
    }
    setTurnLeft(Math.ceil(turnTimeLeft))
    const t = setInterval(() => setTurnLeft(prev => (prev == null ? null : Math.max(0, prev - 1))), 1000)
    return () => clearInterval(t)
  }, [turnTimeLeft, currentIndex, handNum])

  const isShowdown = phase === 'showdown'
  const isMyTurn = actions && actions.length > 0

  useEffect(() => {
    if (isMyTurn) triggerHaptic('warning')
  }, [isMyTurn, handNum, phase])

  useEffect(() => {
    setFoldArmed(false)
    clearTimeout(foldTimerRef.current)
  }, [currentIndex, handNum, phase])
  const me = myIndex >= 0 ? players[myIndex] : null
  const myChips = me ? me.chips : 0
  const maxRaise = me ? me.chips + me.bet : 0
  const callIsAllIn = me && callAmount >= myChips && callAmount > 0
  const imReady = readyPlayers?.includes(userId)

  const doAction = (action, amount) => {
    send({ type: 'action', action, amount })
  }

  const handleRaiseSlider = (val) => {
    setRaiseAmount(val)
    setRaiseInput(String(val))
  }

  const handleRaiseInput = (val) => {
    setRaiseInput(val)
    const n = Number(val)
    if (!isNaN(n) && n >= (minRaiseTo || 0)) {
      setRaiseAmount(Math.min(n, maxRaise))
    }
  }

  const commitRaiseInput = () => {
    const n = Number(raiseInput)
    if (isNaN(n) || n < minRaiseTo) {
      setRaiseInput(String(minRaiseTo))
      setRaiseAmount(minRaiseTo)
    } else {
      const clamped = Math.min(n, maxRaise)
      setRaiseAmount(clamped)
      setRaiseInput(String(clamped))
    }
  }

  const opponents = players.map((p, i) => ({ ...p, idx: i })).filter((p, i) => i !== myIndex && !p.sittingOut)

  return (
    <div className="max-w-md mx-auto flex flex-col gap-3">
      <AnimatePresence>
        {showLeave && (
          <LeaveConfirmDialog
            onConfirm={() => { onLeave(); setShowLeave(false) }}
            onCancel={() => setShowLeave(false)}
          />
        )}
      </AnimatePresence>

      <div className="flex items-center justify-between">
        <h2 className="text-white font-bold text-lg">Раздача #{handNum}</h2>
        <div className="flex items-center gap-3">
          <span className="text-zinc-400 text-xs uppercase">{phaseLabel(phase)}</span>
          <button onClick={() => setShowLeave(true)} className="text-red-400 hover:text-red-300 text-xs transition-colors">
            Выйти
          </button>
        </div>
      </div>

      {smallBlind && (
        <div className="text-zinc-500 text-[10px] text-center -mt-2 flex items-center justify-center gap-2">
          <span>Блайнды {smallBlind}/{bigBlind}</span>
          {blindIncreaseEnabled && blindLevel > 0 && (
            <span className="text-yellow-500/70">Ур. {blindLevel + 1}</span>
          )}
          {blindIncreaseEnabled && blindCountdown > 0 && (
            <span className="text-zinc-600">
              ↑ {Math.floor(blindCountdown / 60)}:{String(blindCountdown % 60).padStart(2, '0')}
            </span>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2 justify-center">
        {opponents.map((p) => (
          <PlayerSeat
            key={p.id}
            player={p}
            isDealer={p.idx === dealerIndex}
            isSmallBlind={p.idx === smallBlindIndex}
            isBigBlind={p.idx === bigBlindIndex}
            isCurrent={p.idx === currentIndex}
            isMe={false}
            showdown={isShowdown}
            index={p.idx}
            actionBadge={visibleAction && visibleAction.player === p.idx ? visibleAction : null}
            secondsLeft={p.idx === currentIndex ? turnLeft : null}
            turnTotal={turnTimeout}
          />
        ))}
      </div>

      <div className="bg-zinc-900/80 rounded-xl p-4 flex flex-col items-center gap-3">
        <AnimatePresence mode="popLayout">
          <div className="flex gap-1.5 justify-center min-h-[68px] items-center">
            {community.length === 0 && <span className="text-zinc-600 text-sm">Ожидание карт...</span>}
            {community.map((c, i) => (
              <motion.div
                key={`card-${i}`}
                initial={{ opacity: 0, rotateY: 90, scale: 0.8 }}
                animate={{ opacity: 1, rotateY: 0, scale: 1 }}
                transition={{ duration: 0.4, delay: i * 0.1 }}
              >
                <PokerCard rank={c.rank} suit={c.suit} />
              </motion.div>
            ))}
            {community.length > 0 && community.length < 5 && (
              Array.from({ length: 5 - community.length }).map((_, i) => (
                <div key={`empty-${i}`} className="w-14 h-20 rounded-lg border-2 border-dashed border-zinc-700" />
              ))
            )}
          </div>
        </AnimatePresence>
        <div className="flex flex-col items-center gap-1">
          <div className="flex items-center gap-3">
            <span className="text-spotify-green font-bold text-lg tabular-nums">Банк: {pot}</span>
            {currentBet > 0 && <span className="text-zinc-400 text-xs tabular-nums">Ставка: {currentBet}</span>}
          </div>
          {pots && pots.length > 1 && (
            <div className="flex items-center gap-1.5 flex-wrap justify-center">
              {pots.map((amt, i) => (
                <span key={i} className="text-[10px] tabular-nums rounded-full px-2 py-0.5 bg-spotify-green/15 text-spotify-green">
                  {i === 0 ? 'Основной' : `Сайд ${i}`}: {amt}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {isShowdown && results && (
        <ShowdownResults
          results={results}
          players={players}
          myIndex={myIndex}
          userId={userId}
          readyPlayers={readyPlayers || []}
          imReady={imReady}
          onReady={() => send({ type: 'ready' })}
        />
      )}

      {myIndex >= 0 && (
        <div
          style={myIndex === currentIndex ? { boxShadow: '0 0 20px 3px rgba(250,204,21,0.3)' } : undefined}
          className="bg-zinc-900/95 backdrop-blur rounded-xl p-3 transition-shadow duration-400 sticky bottom-2 z-20"
        >
          <div className="flex items-center justify-between mb-2">
            <PlayerSeat
              player={players[myIndex]}
              isDealer={myIndex === dealerIndex}
              isSmallBlind={myIndex === smallBlindIndex}
              isBigBlind={myIndex === bigBlindIndex}
              isCurrent={myIndex === currentIndex}
              isMe={true}
              showdown={isShowdown}
              index={myIndex}
              actionBadge={visibleAction && visibleAction.player === myIndex ? visibleAction : null}
              secondsLeft={myIndex === currentIndex ? turnLeft : null}
              turnTotal={turnTimeout}
            />
            <div className="flex flex-col items-end gap-1.5">
              <div className="flex gap-1.5">
                {myCards.map((c, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.15, duration: 0.4 }}
                  >
                    <PokerCard rank={c.rank} suit={c.suit} />
                  </motion.div>
                ))}
              </div>
              {myHand && !players[myIndex].folded && (
                <span className="text-[11px] text-spotify-green font-medium">
                  У вас: {handNameRu(myHand.name)}
                </span>
              )}
            </div>
          </div>

          <AnimatePresence initial={false}>
          {isMyTurn && (
            <motion.div
              key="betting-panel"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="overflow-hidden"
            >
              <div className="flex flex-col gap-2 mt-2">
              <div className="flex gap-2">
                {actions.includes('fold') && (
                  <button
                    onClick={() => {
                      if (actions.includes('check') && !foldArmed) {
                        setFoldArmed(true)
                        clearTimeout(foldTimerRef.current)
                        foldTimerRef.current = setTimeout(() => setFoldArmed(false), 3000)
                        return
                      }
                      doAction('fold')
                    }}
                    className={`flex-1 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors ${foldArmed ? 'bg-red-500 animate-pulse' : 'bg-red-600/80 hover:bg-red-500'}`}
                  >
                    {foldArmed ? 'Точно фолд?' : 'Фолд'}
                  </button>
                )}
                {actions.includes('check') && (
                  <button onClick={() => doAction('check')} className="flex-1 bg-zinc-700 hover:bg-zinc-600 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors">
                    Чек
                  </button>
                )}
                {actions.includes('call') && !callIsAllIn && (
                  <button onClick={() => doAction('call')} className="flex-1 bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors">
                    Колл {callAmount}
                  </button>
                )}
              </div>
              {actions.includes('raise') && (
                <div className="flex flex-col gap-1.5">
                  <div className="flex gap-2 items-center">
                    <input
                      type="range"
                      min={minRaiseTo}
                      max={maxRaise}
                      step={bigBlind || 1}
                      value={raiseAmount}
                      onChange={e => handleRaiseSlider(Number(e.target.value))}
                      className="flex-1 accent-green-500"
                    />
                  </div>
                  <div className="flex gap-2 items-center">
                    <input
                      type="number"
                      value={raiseInput}
                      onChange={e => handleRaiseInput(e.target.value)}
                      onBlur={commitRaiseInput}
                      onKeyDown={e => e.key === 'Enter' && (commitRaiseInput(), doAction('raise', raiseAmount))}
                      className="flex-1 bg-zinc-800 rounded-lg px-2 py-2 text-sm text-white outline-none focus:ring-1 focus:ring-green-500 text-center"
                      min={minRaiseTo}
                      max={maxRaise}
                    />
                    <button
                      onClick={() => doAction('raise', raiseAmount)}
                      className="bg-green-600 hover:bg-green-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors whitespace-nowrap"
                    >
                      Рейз
                    </button>
                  </div>
                  <div className="flex gap-1.5 justify-center flex-wrap">
                    {[
                      { v: minRaiseTo, label: 'Мин' },
                      { v: currentBet + (bigBlind || 0) * 2, label: '2ББ' },
                      { v: currentBet + (bigBlind || 0) * 3, label: '3ББ' },
                      { v: Math.floor(pot / 2) + (me?.bet || 0), label: '½ банк' },
                      { v: pot + (me?.bet || 0), label: 'Банк' },
                      { v: maxRaise, label: 'Макс' },
                    ]
                      .filter((o, i, a) => o.v >= minRaiseTo && o.v <= maxRaise && a.findIndex(x => x.v === o.v) === i)
                      .map(o => (
                        <button key={o.label} onClick={() => handleRaiseSlider(o.v)}
                          className={`text-[10px] px-2 py-1 rounded transition-colors ${raiseAmount === o.v ? 'bg-spotify-green/20 text-spotify-green' : 'bg-zinc-800 hover:bg-zinc-700 text-zinc-300'}`}>
                          {o.label}
                        </button>
                      ))}
                  </div>
                </div>
              )}
              {actions.includes('all_in') && (
                <button onClick={() => doAction('all_in')} className="bg-red-700 hover:bg-red-600 text-white text-sm font-bold py-2.5 rounded-lg transition-colors">
                  Олл-ин ({myChips}{callIsAllIn ? ' — колл' : ''})
                </button>
              )}
              </div>
            </motion.div>
          )}
          </AnimatePresence>

          {!isMyTurn && phase !== 'showdown' && phase !== 'waiting' && !players[myIndex].folded && !players[myIndex].sittingOut && (
            <p className="text-zinc-500 text-xs text-center mt-2">Ожидание соперника...</p>
          )}
          {players[myIndex].folded && phase !== 'showdown' && (
            <p className="text-zinc-500 text-xs text-center mt-2">Вы сбросили карты</p>
          )}
          {players[myIndex].sittingOut && (
            <p className="text-zinc-500 text-xs text-center mt-2">Вы вне раздачи — подключитесь к следующей</p>
          )}
        </div>
      )}

    </div>
  )
}

function ShowdownResults({ results, players, myIndex, userId, readyPlayers, imReady, onReady }) {
  const [showWhy, setShowWhy] = useState(false)

  if (!results) return null

  const totalEligible = players.filter(p => !p.sittingOut && p.chips > 0 && !p.isBot).length
  const hands = results.hands || {}
  const hasHands = Object.keys(hands).length > 0

  const sorted = Object.entries(hands)
    .map(([idx, hand]) => ({ idx: Number(idx), ...hand }))
    .sort((a, b) => {
      const aw = results.winners.includes(a.idx) ? 1 : 0
      const bw = results.winners.includes(b.idx) ? 1 : 0
      if (bw !== aw) return bw - aw
      return b.score - a.score
    })

  const winnerNames = results.winners
    .map(i => players[i]?.name)
    .filter(Boolean)
    .join(', ')

  const winnerHands = results.winners
    .map(i => hands[i])
    .filter(Boolean)

  const loserEntries = sorted.filter(e => !results.winners.includes(e.idx))

  let summaryLines = []
  if (winnerHands.length > 0 && loserEntries.length > 0) {
    const wDesc = winnerHands[0].description || winnerHands[0].name
    summaryLines.push(`${winnerNames} выигрывает с комбинацией: ${wDesc}`)
    for (const l of loserEntries) {
      const lName = players[l.idx]?.name || '?'
      const lDesc = l.description || l.name
      if (winnerHands[0].score > l.score) {
        summaryLines.push(`${winnerHands[0].name} (ранг ${winnerHands[0].score}) сильнее ${l.name} (ранг ${l.score}) у ${lName}`)
      } else if (winnerHands[0].score === l.score) {
        summaryLines.push(`${lName} тоже собрал ${l.name}, но проиграл по кикерам`)
      }
    }
  } else if (!hasHands && results.winners.length > 0) {
    summaryLines.push(`${winnerNames} выигрывает — все соперники сбросили карты`)
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-zinc-900 border border-yellow-500/30 rounded-xl p-4"
    >
      <h3 className="text-yellow-400 font-bold text-sm mb-2 text-center">
        Результаты
      </h3>
      <div className="flex flex-col gap-1.5">
        {Object.entries(hands).map(([idx, hand]) => {
          const i = Number(idx)
          const p = players[i]
          const isWinner = results.winners.includes(i)
          return (
            <div key={i} className={`flex items-center justify-between text-sm px-2 py-1 rounded ${isWinner ? 'bg-yellow-500/10' : ''}`}>
              <span className={isWinner ? 'text-yellow-400 font-semibold' : 'text-zinc-400'}>
                {isWinner && '🏆 '}{p?.name}
              </span>
              <div className="flex items-center gap-2">
                <span className="text-zinc-400 text-xs">{hand.name}</span>
                {hand.won > 0 && <span className="text-green-400 text-xs font-semibold">+{hand.won}</span>}
              </div>
            </div>
          )
        })}
        {results.winners?.length > 0 && !hasHands && (
          <div className="text-center text-yellow-400 text-sm">
            🏆 {players[results.winners[0]]?.name} победил
          </div>
        )}
      </div>

      {(hasHands || (!hasHands && results.winners.length > 0)) && (
        <button
          onClick={() => setShowWhy(v => !v)}
          className="w-full mt-2 text-blue-400 hover:text-blue-300 text-xs font-medium transition-colors"
        >
          {showWhy ? 'Скрыть ▲' : 'Почему? ▼'}
        </button>
      )}

      <AnimatePresence>
        {showWhy && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-2 border-t border-zinc-800 pt-3 flex flex-col gap-3">
              {sorted.map(entry => {
                const p = players[entry.idx]
                const isWinner = results.winners.includes(entry.idx)
                return (
                  <div key={entry.idx} className={`rounded-lg p-2.5 ${isWinner ? 'bg-yellow-500/5 border border-yellow-500/20' : 'bg-zinc-800/50'}`}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className={`text-xs font-semibold ${isWinner ? 'text-yellow-400' : 'text-zinc-400'}`}>
                        {isWinner ? '🏆 ' : '❌ '}{p?.name}
                      </span>
                      {entry.won > 0 && <span className="text-green-400 text-[11px] font-bold">+{entry.won}</span>}
                    </div>
                    <p className={`text-[11px] mb-1.5 ${isWinner ? 'text-yellow-300/80' : 'text-zinc-500'}`}>
                      {entry.description || entry.name}
                    </p>
                    {entry.cards && entry.cards.length > 0 && (
                      <div className="flex gap-0.5">
                        {entry.cards.map((c, ci) => (
                          <PokerCard key={ci} rank={c.rank} suit={c.suit} small />
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}

              {summaryLines.length > 0 && (
                <div className="bg-zinc-800/60 rounded-lg p-2.5">
                  {summaryLines.map((line, li) => (
                    <p key={li} className={`text-[11px] ${li === 0 ? 'text-zinc-300 font-medium' : 'text-zinc-500'}`}>
                      {line}
                    </p>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="mt-3 flex flex-col items-center gap-2">
        {!imReady ? (
          <button
            onClick={onReady}
            className="w-full bg-green-600 hover:bg-green-500 text-white text-sm font-bold py-2.5 rounded-lg transition-colors"
          >
            Продолжить
          </button>
        ) : (
          <span className="text-green-400 text-xs font-semibold">✓ Готово</span>
        )}
        <span className="text-zinc-600 text-[11px]">
          {readyPlayers.length}/{Math.max(totalEligible, 1)} игроков готовы
        </span>
      </div>
    </motion.div>
  )
}

function phaseLabel(phase) {
  const map = {
    waiting: 'Ожидание',
    preflop: 'Префлоп',
    flop: 'Flop',
    turn: 'Тёрн',
    river: 'Ривер',
    showdown: 'Вскрытие',
  }
  return map[phase] || phase
}

function actionLabel(la) {
  if (!la) return ''
  const map = { fold: 'Фолд', check: 'Чек', call: 'Колл', raise: 'Рейз', all_in: 'Олл-ин' }
  const label = map[la.action] || la.action
  if (la.amount) return `${label} ${la.amount}`
  return label
}

function actionBg(action) {
  const map = {
    fold: 'bg-red-900/40 border border-red-700/30',
    check: 'bg-zinc-800 border border-zinc-700/30',
    call: 'bg-blue-900/40 border border-blue-700/30',
    raise: 'bg-green-900/40 border border-green-700/30',
    all_in: 'bg-red-900/50 border border-red-600/40',
  }
  return map[action] || 'bg-zinc-800 border border-zinc-700/30'
}

function actionColor(action) {
  const map = {
    fold: 'text-red-400',
    check: 'text-zinc-300',
    call: 'text-blue-400',
    raise: 'text-green-400',
    all_in: 'text-red-300 font-bold',
  }
  return map[action] || 'text-zinc-300'
}

export default function PokerPage() {
  const { userId, initData } = useAuth()
  const [view, setView] = useState('lobby')
  const [rooms, setRooms] = useState([])
  const [room, setRoom] = useState(null)
  const [gameState, setGameState] = useState(null)
  const [error, setError] = useState(null)
  const [connected, setConnected] = useState(false)
  const [pokerStats, setPokerStats] = useState(null)
  const [monkeyBalance, setMonkeyBalance] = useState(null)
  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)

  const effectiveId = userId || Math.floor(Math.random() * 900000) + 100000

  const send = useCallback((msg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  useEffect(() => {
    if (effectiveId && view === 'lobby') {
      api.get(`/api/poker/stats/${effectiveId}`)
        .then(data => { if (data) setPokerStats(data) })
        .catch(() => {})
    }
  }, [effectiveId, view])

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/poker`)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      ws.send(JSON.stringify({ type: 'auth', initData }))
      ws.send(JSON.stringify({ type: 'list_rooms' }))
    }

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data)
      switch (data.type) {
        case 'authed':
          break
        case 'rooms_list':
          setRooms(data.rooms)
          break
        case 'room_joined':
          setRoom(data.room)
          if (data.monkeysBalance !== undefined && data.monkeysBalance !== null) {
            setMonkeyBalance(data.monkeysBalance)
          }
          setView('waiting')
          setError(null)
          break
        case 'room_updated':
          setRoom(data.room)
          break
        case 'game_state':
          setGameState(data.state)
          setView('game')
          break
        case 'player_ready':
          setGameState(prev => prev ? { ...prev, readyPlayers: data.readyPlayers } : prev)
          break
        case 'blinds_increased':
          setGameState(prev => prev ? {
            ...prev,
            smallBlind: data.smallBlind,
            bigBlind: data.bigBlind,
            blindLevel: data.blindLevel,
          } : prev)
          setError(`Блайнды повышены: ${data.smallBlind}/${data.bigBlind}`)
          setTimeout(() => setError(null), 3000)
          break
        case 'reconnected':
          setRoom(data.room)
          if (data.room.started) setView('game')
          else setView('waiting')
          break
        case 'left_room':
          setRoom(null)
          if (data.monkeysBalance !== undefined && data.monkeysBalance !== null) {
            setMonkeyBalance(data.monkeysBalance)
          }
          setGameState(null)
          setView('lobby')
          send({ type: 'list_rooms' })
          break
        case 'game_over':
          setGameState(null)
          setView('waiting')
          break
        case 'error':
          setError(data.message)
          setTimeout(() => setError(null), 3000)
          break
      }
    }

    ws.onclose = () => {
      setConnected(false)
      reconnectTimer.current = setTimeout(connect, 2000)
    }

    ws.onerror = () => ws.close()
  }, [effectiveId, initData])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const handleLeave = () => {
    if (room?.id) {
      api.post('/api/poker/invite/delete', { roomId: room.id }).catch(() => {})
    }
    send({ type: 'leave_room' })
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6 pb-4 max-w-3xl mx-auto"
    >
      {!connected && (
        <div className="text-center text-spotify-text text-sm py-8">Подключение…</div>
      )}

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

      {connected && view === 'lobby' && (
        <Lobby rooms={rooms} send={send} userId={effectiveId} pokerStats={pokerStats} monkeyBalance={monkeyBalance} />
      )}
      {connected && view === 'waiting' && (
        <WaitingRoom room={room} send={send} userId={effectiveId} monkeyBalance={monkeyBalance} />
      )}
      {connected && view === 'game' && <GameTable state={gameState} send={send} userId={effectiveId} onLeave={handleLeave} />}
    </motion.div>
  )
}
