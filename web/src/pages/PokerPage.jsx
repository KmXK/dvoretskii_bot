import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useTelegram } from '../context/TelegramContext'

const SUIT_SYMBOL = { h: '♥', d: '♦', c: '♣', s: '♠' }
const DIFFICULTY_OPTIONS = [
  { value: 'easy', label: 'Easy', color: 'text-green-400' },
  { value: 'medium', label: 'Medium', color: 'text-yellow-400' },
  { value: 'hard', label: 'Hard', color: 'text-red-400' },
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

function PlayerSeat({ player, isDealer, isCurrent, isMe, showdown, index, actionBadge }) {
  let border = 'border-zinc-700'
  if (player.folded) border = 'border-zinc-800'
  if (isMe) border = 'border-green-500/60'
  if (isCurrent) border = 'border-yellow-400'

  let bg = 'bg-zinc-800/80'
  if (player.folded) bg = 'bg-zinc-900/60'

  let statusText = '\u00A0'
  let statusClass = 'text-transparent'
  if (player.allIn && !player.folded) {
    statusText = 'All-in'
    statusClass = 'font-bold text-red-400 uppercase'
  } else if (player.folded) {
    statusText = 'Fold'
    statusClass = 'text-zinc-500'
  } else if (player.bet > 0) {
    statusText = `Bet: ${player.bet}`
    statusClass = 'text-yellow-300'
  }

  const showCards = !isMe && !player.sittingOut && !player.folded && !showdown
  const showShowdownCards = showdown && player.cards && player.cards.length > 0

  return (
    <div
      style={isCurrent ? { boxShadow: '0 0 16px 2px rgba(250,204,21,0.35)' } : undefined}
      className={`relative rounded-xl border-2 ${border} ${bg} p-2 w-[110px] h-[120px] flex flex-col items-center transition-colors transition-shadow duration-400`}
    >
      {isDealer && (
        <span className="absolute -top-2 -left-2 bg-yellow-400 text-black text-[10px] font-bold rounded-full w-5 h-5 flex items-center justify-center shadow">D</span>
      )}
      {isCurrent && (
        <span className="absolute -top-2 -right-2 bg-yellow-400 text-black text-[9px] font-bold rounded-full px-1.5 py-0.5 shadow">
          TURN
        </span>
      )}
      <span className={`text-xs font-semibold truncate max-w-[90px] ${isMe ? 'text-green-400' : player.isBot ? 'text-blue-300' : 'text-white'}`}>
        {player.name}
      </span>
      <span className="text-[11px] text-zinc-400">{player.chips} chips</span>
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
        className="bg-zinc-900 border border-zinc-700 rounded-xl p-5 max-w-xs w-full"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="text-white font-bold text-base mb-2">Leave Table?</h3>
        <p className="text-zinc-400 text-sm mb-4">Your chips will be saved if you return to this room.</p>
        <div className="flex gap-2">
          <button onClick={onCancel} className="flex-1 bg-zinc-700 hover:bg-zinc-600 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors">
            Stay
          </button>
          <button onClick={onConfirm} className="flex-1 bg-red-600 hover:bg-red-500 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors">
            Leave
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

function StatCell({ value, label, color = 'text-white' }) {
  return (
    <div className="bg-zinc-800 rounded-lg p-2 text-center">
      <div className={`text-lg font-bold ${color}`}>{value}</div>
      <div className="text-[10px] text-zinc-400">{label}</div>
    </div>
  )
}

function PokerStatsBlock({ stats }) {
  const [expanded, setExpanded] = useState(false)
  const s = stats
  const winRate = s.hands > 0 ? Math.round((s.handsWon / s.hands) * 100) : 0
  const netChips = (s.chipsWon || 0) - (s.chipsLost || 0)

  return (
    <div className="bg-zinc-900 rounded-xl p-4 mb-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between w-full text-left mb-3"
      >
        <h2 className="text-white font-semibold text-sm">Your Stats</h2>
        <span className="text-zinc-400 text-xs">{expanded ? 'Less ▲' : 'More ▼'}</span>
      </button>

      <div className="grid grid-cols-3 gap-2">
        <StatCell value={s.games || 0} label="Games" />
        <StatCell value={s.gamesWon || 0} label="Games won" color="text-green-400" />
        <StatCell value={s.hands || 0} label="Hands" />
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
              <StatCell value={s.handsWon || 0} label="Hands won" color="text-green-400" />
              <StatCell value={s.handsLost || 0} label="Hands lost" color="text-red-400" />
              <StatCell value={s.handsFolded || 0} label="Folded" color="text-zinc-400" />
            </div>

            <div className="grid grid-cols-3 gap-2 mt-2">
              <StatCell value={s.chipsWon || 0} label="Chips won" color="text-green-400" />
              <StatCell value={s.chipsLost || 0} label="Chips lost" color="text-red-400" />
              <StatCell value={netChips} label="Net chips" color={netChips >= 0 ? 'text-green-400' : 'text-red-400'} />
            </div>

            {s.hands > 0 && (
              <div className="mt-3 bg-zinc-800 rounded-lg p-2.5">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-zinc-400 text-[11px]">Win rate</span>
                  <span className="text-white text-xs font-bold">{winRate}%</span>
                </div>
                <div className="w-full bg-zinc-700 rounded-full h-1.5">
                  <div
                    className="bg-green-500 h-1.5 rounded-full transition-all"
                    style={{ width: `${winRate}%` }}
                  />
                </div>
              </div>
            )}

            {s.combos && s.combos.length > 0 && (
              <div className="mt-3">
                <h3 className="text-zinc-400 text-[11px] mb-2">Combinations</h3>
                <div className="flex flex-col gap-1">
                  {s.combos.map((c, i) => (
                    <div key={i} className="flex items-center justify-between bg-zinc-800 rounded-lg px-2.5 py-1.5">
                      <span className="text-zinc-300 text-xs">{c.name}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-zinc-500 text-[10px]">collected {c.collected}</span>
                        <span className="text-green-400 text-[10px] font-semibold">won {c.won}</span>
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

function Lobby({ rooms, send, userId, pokerStats }) {
  const [name, setName] = useState('')
  const [sb, setSb] = useState(10)
  const [bb, setBb] = useState(20)
  const [sc, setSc] = useState(1000)
  const [bc, setBc] = useState(0)
  const [bd, setBd] = useState('medium')
  const [showSettings, setShowSettings] = useState(false)

  const create = () => {
    send({ type: 'create_room', name: name.trim() || undefined, smallBlind: sb, bigBlind: bb, startChips: sc, botCount: Number(bc) || 0, botDifficulty: bd })
    setName('')
  }

  const refresh = () => send({ type: 'list_rooms' })

  return (
    <div className="max-w-md mx-auto">
      <h1 className="text-2xl font-bold text-white mb-1">Poker</h1>
      <p className="text-zinc-400 text-sm mb-6">Texas Hold'em — create a room or join one</p>

      {pokerStats && <PokerStatsBlock stats={pokerStats} />}

      <div className="bg-zinc-900 rounded-xl p-4 mb-4">
        <h2 className="text-white font-semibold text-sm mb-3">Create Room</h2>
        <div className="flex gap-2 mb-2">
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Room name"
            className="flex-1 bg-zinc-800 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-500 outline-none focus:ring-1 focus:ring-green-500"
            maxLength={40}
            onKeyDown={e => e.key === 'Enter' && create()}
          />
          <button onClick={create} className="bg-green-600 hover:bg-green-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors">
            Create
          </button>
        </div>
        <button
          onClick={() => setShowSettings(!showSettings)}
          className="text-zinc-400 hover:text-white text-xs transition-colors"
        >
          {showSettings ? 'Hide settings ▲' : 'Settings ▼'}
        </button>
        <AnimatePresence>
          {showSettings && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div className="grid grid-cols-2 gap-2 mt-3">
                <div>
                  <label className="text-zinc-500 text-[10px] block mb-1">Small blind</label>
                  <input
                    type="number"
                    value={sb}
                    onChange={e => { const v = Math.max(1, Number(e.target.value)); setSb(v); if (bb < v * 2) setBb(v * 2) }}
                    className="w-full bg-zinc-800 rounded-lg px-2 py-1.5 text-sm text-white outline-none focus:ring-1 focus:ring-green-500"
                    min={1}
                  />
                </div>
                <div>
                  <label className="text-zinc-500 text-[10px] block mb-1">Big blind</label>
                  <input
                    type="number"
                    value={bb}
                    onChange={e => setBb(Math.max(sb * 2, Number(e.target.value)))}
                    className="w-full bg-zinc-800 rounded-lg px-2 py-1.5 text-sm text-white outline-none focus:ring-1 focus:ring-green-500"
                    min={sb * 2}
                  />
                </div>
                <div>
                  <label className="text-zinc-500 text-[10px] block mb-1">Start chips</label>
                  <input
                    type="number"
                    value={sc}
                    onChange={e => setSc(Math.max(bb * 10, Number(e.target.value)))}
                    className="w-full bg-zinc-800 rounded-lg px-2 py-1.5 text-sm text-white outline-none focus:ring-1 focus:ring-green-500"
                    min={bb * 10}
                    step={100}
                  />
                </div>
                <div>
                  <label className="text-zinc-500 text-[10px] block mb-1">Bots</label>
                  <input
                    type="number"
                    value={bc}
                    onChange={e => setBc(e.target.value === '' ? '' : Math.min(7, Number(e.target.value)))}
                    onBlur={() => setBc(prev => Math.max(0, Math.min(7, Number(prev) || 0)))}
                    className="w-full bg-zinc-800 rounded-lg px-2 py-1.5 text-sm text-white outline-none focus:ring-1 focus:ring-green-500"
                    min={0}
                    max={7}
                  />
                </div>
                {Number(bc) > 0 && (
                  <div className="col-span-2">
                    <label className="text-zinc-500 text-[10px] block mb-1">Bot difficulty</label>
                    <div className="flex gap-1.5">
                      {DIFFICULTY_OPTIONS.map(opt => (
                        <button
                          key={opt.value}
                          onClick={() => setBd(opt.value)}
                          className={`flex-1 py-1.5 rounded-lg text-xs font-semibold transition-colors ${bd === opt.value ? 'bg-zinc-600 ' + opt.color : 'bg-zinc-800 text-zinc-500 hover:bg-zinc-700'}`}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="bg-zinc-900 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-white font-semibold text-sm">Rooms</h2>
          <button onClick={refresh} className="text-zinc-400 hover:text-white text-xs transition-colors">
            Refresh
          </button>
        </div>

        {rooms.length === 0 && (
          <p className="text-zinc-500 text-sm text-center py-4">No rooms available</p>
        )}

        <div className="flex flex-col gap-2">
          {rooms.map(room => (
            <div key={room.id} className="bg-zinc-800 rounded-lg p-3 flex items-center justify-between">
              <div>
                <span className="text-white text-sm font-medium">{room.name}</span>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-zinc-400 text-xs">{room.playerCount}/{room.maxPlayers} players</span>
                  {room.botCount > 0 && <span className="text-blue-400 text-xs">🤖{room.botCount}</span>}
                  {room.started && <span className="text-yellow-400 text-xs">In game</span>}
                  <span className="text-zinc-500 text-[10px]">{room.smallBlind}/{room.bigBlind}</span>
                </div>
              </div>
              <button
                onClick={() => send({ type: 'join_room', roomId: room.id })}
                disabled={room.playerCount >= room.maxPlayers}
                className="bg-green-600 hover:bg-green-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
              >
                {room.started ? 'Spectate' : 'Join'}
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
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    fetch(`/api/user/${userId}/chats`)
      .then(r => r.ok ? r.json() : { chats: [] })
      .then(d => setChats(d.chats || []))
      .catch(() => {})
  }, [userId])

  useEffect(() => {
    if (sent && room) {
      fetch('/api/poker/invite/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          roomId: room.id,
          roomName: room.name,
          playerCount: room.playerCount,
          maxPlayers: room.maxPlayers,
        })
      }).catch(() => {})
    }
  }, [room?.playerCount, sent])

  const sendInvites = async () => {
    if (selected.size === 0) return
    setSending(true)
    try {
      await fetch('/api/poker/invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chatIds: [...selected],
          roomName: room.name,
          roomId: room.id,
          playerCount: room.playerCount,
          maxPlayers: room.maxPlayers,
          creatorName: room.players?.[0]?.name || 'Someone',
        })
      })
      setSent(true)
    } catch {}
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
    <div className="bg-zinc-900 rounded-xl p-4 mb-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between w-full text-left"
      >
        <span className="text-white font-semibold text-sm">
          {sent ? '✓ Invitations sent' : 'Invite to chats'}
        </span>
        <span className="text-zinc-400 text-xs">{expanded ? '▲' : '▼'}</span>
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="flex flex-col gap-1.5 mt-3">
              {chats.map(c => (
                <label key={c.id} className="flex items-center gap-2 bg-zinc-800 rounded-lg px-3 py-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selected.has(c.id)}
                    onChange={() => toggle(c.id)}
                    className="accent-green-500 w-4 h-4"
                    disabled={sent}
                  />
                  <span className="text-white text-sm truncate">{c.name}</span>
                </label>
              ))}
            </div>
            {!sent && (
              <button
                onClick={sendInvites}
                disabled={selected.size === 0 || sending}
                className="w-full mt-3 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-semibold py-2 rounded-lg transition-colors"
              >
                {sending ? 'Sending...' : `Send to ${selected.size} chat${selected.size !== 1 ? 's' : ''}`}
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function WaitingRoom({ room, send, userId }) {
  if (!room) return null
  const isCreator = room.creator_id === userId
  const [editBlinds, setEditBlinds] = useState(false)
  const [sb, setSb] = useState(room.smallBlind || 10)
  const [bb, setBb] = useState(room.bigBlind || 20)
  const [sc, setSc] = useState(room.startChips || 1000)
  const [bc, setBc] = useState(room.botCount || 0)
  const [bd, setBd] = useState(room.botDifficulty || 'medium')
  const [showLeave, setShowLeave] = useState(false)

  useEffect(() => {
    setSb(room.smallBlind || 10)
    setBb(room.bigBlind || 20)
    setSc(room.startChips || 1000)
    setBc(room.botCount || 0)
    setBd(room.botDifficulty || 'medium')
  }, [room.smallBlind, room.bigBlind, room.startChips, room.botCount, room.botDifficulty])

  const saveSettings = () => {
    send({ type: 'update_settings', smallBlind: sb, bigBlind: bb, startChips: sc, botCount: Number(bc) || 0, botDifficulty: bd })
    setEditBlinds(false)
  }

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

      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold text-white">{room.name}</h1>
        <button onClick={() => setShowLeave(true)} className="text-red-400 hover:text-red-300 text-sm transition-colors">
          Leave
        </button>
      </div>

      <div className="bg-zinc-900 rounded-xl p-4 mb-4">
        <h2 className="text-white font-semibold text-sm mb-3">Players ({room.playerCount}/8)</h2>
        <div className="flex flex-col gap-2">
          {(room.players || []).map((p) => (
            <div key={p.id} className="flex items-center gap-2 bg-zinc-800 rounded-lg px-3 py-2">
              <div className={`w-8 h-8 rounded-full ${p.isBot ? 'bg-blue-600' : 'bg-green-600'} flex items-center justify-center text-white text-sm font-bold`}>
                {p.isBot ? '🤖' : p.name[0]?.toUpperCase()}
              </div>
              <span className={`text-sm ${p.id === userId ? 'text-green-400 font-semibold' : p.isBot ? 'text-blue-300' : 'text-white'}`}>
                {p.name}
              </span>
              {p.id === room.creator_id && <span className="text-xs text-yellow-400 ml-auto">Owner</span>}
            </div>
          ))}
        </div>
      </div>

      <InviteBlock room={room} userId={userId} />

      <div className="bg-zinc-900 rounded-xl p-4 mb-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-zinc-400 text-xs font-medium">Settings</span>
          {isCreator && !editBlinds && (
            <button onClick={() => setEditBlinds(true)} className="text-green-400 text-xs hover:text-green-300 transition-colors">
              Edit
            </button>
          )}
        </div>

        {editBlinds && isCreator ? (
          <div className="flex flex-col gap-2">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-zinc-500 text-[10px] block mb-1">Small blind</label>
                <input type="number" value={sb}
                  onChange={e => { const v = Math.max(1, Number(e.target.value)); setSb(v); if (bb < v * 2) setBb(v * 2) }}
                  className="w-full bg-zinc-800 rounded-lg px-2 py-1.5 text-sm text-white outline-none focus:ring-1 focus:ring-green-500" min={1} />
              </div>
              <div>
                <label className="text-zinc-500 text-[10px] block mb-1">Big blind</label>
                <input type="number" value={bb}
                  onChange={e => setBb(Math.max(sb * 2, Number(e.target.value)))}
                  className="w-full bg-zinc-800 rounded-lg px-2 py-1.5 text-sm text-white outline-none focus:ring-1 focus:ring-green-500" min={sb * 2} />
              </div>
              <div>
                <label className="text-zinc-500 text-[10px] block mb-1">Start chips</label>
                <input type="number" value={sc}
                  onChange={e => setSc(Math.max(bb * 10, Number(e.target.value)))}
                  className="w-full bg-zinc-800 rounded-lg px-2 py-1.5 text-sm text-white outline-none focus:ring-1 focus:ring-green-500" min={bb * 10} step={100} />
              </div>
              <div>
                <label className="text-zinc-500 text-[10px] block mb-1">Bots</label>
                <input type="number" value={bc}
                  onChange={e => setBc(e.target.value === '' ? '' : Math.min(7, Number(e.target.value)))}
                  onBlur={() => setBc(prev => Math.max(0, Math.min(7, Number(prev) || 0)))}
                  className="w-full bg-zinc-800 rounded-lg px-2 py-1.5 text-sm text-white outline-none focus:ring-1 focus:ring-green-500" min={0} max={7} />
              </div>
              {Number(bc) > 0 && (
                <div className="col-span-2">
                  <label className="text-zinc-500 text-[10px] block mb-1">Bot difficulty</label>
                  <div className="flex gap-1.5">
                    {DIFFICULTY_OPTIONS.map(opt => (
                      <button
                        key={opt.value}
                        onClick={() => setBd(opt.value)}
                        className={`flex-1 py-1.5 rounded-lg text-xs font-semibold transition-colors ${bd === opt.value ? 'bg-zinc-600 ' + opt.color : 'bg-zinc-800 text-zinc-500 hover:bg-zinc-700'}`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="flex gap-2">
              <button onClick={() => setEditBlinds(false)} className="flex-1 bg-zinc-700 text-white text-xs py-1.5 rounded-lg">Cancel</button>
              <button onClick={saveSettings} className="flex-1 bg-green-600 text-white text-xs py-1.5 rounded-lg">Save</button>
            </div>
          </div>
        ) : (
          <>
            <p className="text-zinc-400 text-xs mb-1">Blinds: {room.smallBlind || 10} / {room.bigBlind || 20}</p>
            <p className="text-zinc-400 text-xs mb-1">Starting chips: {room.startChips || 1000}</p>
            <p className="text-zinc-400 text-xs mb-1">Bots: {room.botCount || 0}{room.botCount > 0 ? ` (${DIFFICULTY_OPTIONS.find(o => o.value === (room.botDifficulty || 'medium'))?.label || 'Medium'})` : ''}</p>
            <p className="text-zinc-400 text-xs">Min players: 2 (including bots)</p>
          </>
        )}
      </div>

      {isCreator ? (
        <button
          onClick={() => send({ type: 'start_game' })}
          disabled={(room.playerCount || 0) < 2}
          className="w-full bg-green-600 hover:bg-green-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white font-bold py-3 rounded-xl transition-colors text-sm"
        >
          {(room.playerCount || 0) < 2 ? 'Need at least 2 players (add bots or invite)...' : 'Start Game'}
        </button>
      ) : (
        <div className="text-center text-zinc-400 text-sm py-3">Waiting for owner to start...</div>
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

  const { phase, community, pot, currentBet, dealerIndex, currentIndex, myIndex,
    myCards, players, actions, results, lastAction, handNum, callAmount, minRaiseTo,
    readyPlayers, smallBlind, bigBlind } = state

  const isShowdown = phase === 'showdown'
  const isMyTurn = actions && actions.length > 0
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
        <h2 className="text-white font-bold text-lg">Hand #{handNum}</h2>
        <div className="flex items-center gap-3">
          <span className="text-zinc-400 text-xs uppercase">{phaseLabel(phase)}</span>
          <button onClick={() => setShowLeave(true)} className="text-red-400 hover:text-red-300 text-xs transition-colors">
            Leave
          </button>
        </div>
      </div>

      {smallBlind && (
        <div className="text-zinc-500 text-[10px] text-center -mt-2">
          Blinds {smallBlind}/{bigBlind}
        </div>
      )}

      <div className="flex flex-wrap gap-2 justify-center">
        {opponents.map((p) => (
          <PlayerSeat
            key={p.id}
            player={p}
            isDealer={p.idx === dealerIndex}
            isCurrent={p.idx === currentIndex}
            isMe={false}
            showdown={isShowdown}
            index={p.idx}
            actionBadge={visibleAction && visibleAction.player === p.idx ? visibleAction : null}
          />
        ))}
      </div>

      <div className="bg-zinc-900/80 rounded-xl p-4 flex flex-col items-center gap-3">
        <AnimatePresence mode="popLayout">
          <div className="flex gap-1.5 justify-center min-h-[68px] items-center">
            {community.length === 0 && <span className="text-zinc-600 text-sm">Waiting for cards...</span>}
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
                <div key={`empty-${i}`} className="w-12 h-17 rounded-lg border-2 border-dashed border-zinc-700" />
              ))
            )}
          </div>
        </AnimatePresence>
        <div className="flex items-center gap-3">
          <span className="text-yellow-400 font-bold text-lg">Pot: {pot}</span>
          {currentBet > 0 && <span className="text-zinc-400 text-xs">Current bet: {currentBet}</span>}
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
          className="bg-zinc-900/80 rounded-xl p-3 transition-shadow duration-400"
        >
          <div className="flex items-center justify-between mb-2">
            <PlayerSeat
              player={players[myIndex]}
              isDealer={myIndex === dealerIndex}
              isCurrent={myIndex === currentIndex}
              isMe={true}
              showdown={isShowdown}
              index={myIndex}
              actionBadge={visibleAction && visibleAction.player === myIndex ? visibleAction : null}
            />
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
                  <button onClick={() => doAction('fold')} className="flex-1 bg-red-600/80 hover:bg-red-500 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors">
                    Fold
                  </button>
                )}
                {actions.includes('check') && (
                  <button onClick={() => doAction('check')} className="flex-1 bg-zinc-700 hover:bg-zinc-600 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors">
                    Check
                  </button>
                )}
                {actions.includes('call') && !callIsAllIn && (
                  <button onClick={() => doAction('call')} className="flex-1 bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors">
                    Call {callAmount}
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
                      Raise
                    </button>
                  </div>
                  <div className="flex gap-1.5 justify-center">
                    {[minRaiseTo, Math.floor(pot / 2 + (me?.bet || 0)), pot + (me?.bet || 0)].filter((v, i, a) => v <= maxRaise && a.indexOf(v) === i && v >= minRaiseTo).map(v => (
                      <button key={v} onClick={() => handleRaiseSlider(v)}
                        className="bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-[10px] px-2 py-1 rounded transition-colors">
                        {v === minRaiseTo ? 'Min' : v >= maxRaise ? 'Max' : v}
                      </button>
                    ))}
                    <button onClick={() => handleRaiseSlider(maxRaise)}
                      className="bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-[10px] px-2 py-1 rounded transition-colors">
                      Max
                    </button>
                  </div>
                </div>
              )}
              {actions.includes('all_in') && (
                <button onClick={() => doAction('all_in')} className="bg-red-700 hover:bg-red-600 text-white text-sm font-bold py-2.5 rounded-lg transition-colors">
                  All-in ({myChips}{callIsAllIn ? ' — call' : ''})
                </button>
              )}
              </div>
            </motion.div>
          )}
          </AnimatePresence>

          {!isMyTurn && phase !== 'showdown' && phase !== 'waiting' && !players[myIndex].folded && !players[myIndex].sittingOut && (
            <p className="text-zinc-500 text-xs text-center mt-2">Waiting for opponent...</p>
          )}
          {players[myIndex].folded && phase !== 'showdown' && (
            <p className="text-zinc-500 text-xs text-center mt-2">You folded</p>
          )}
          {players[myIndex].sittingOut && (
            <p className="text-zinc-500 text-xs text-center mt-2">Sitting out — you'll join next hand</p>
          )}
        </div>
      )}

    </div>
  )
}

function ShowdownResults({ results, players, myIndex, userId, readyPlayers, imReady, onReady }) {
  if (!results) return null

  const totalEligible = players.filter(p => !p.sittingOut && p.chips > 0 && !p.isBot).length

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-zinc-900 border border-yellow-500/30 rounded-xl p-4"
    >
      <h3 className="text-yellow-400 font-bold text-sm mb-2 text-center">
        Results
      </h3>
      <div className="flex flex-col gap-1.5">
        {Object.entries(results.hands || {}).map(([idx, hand]) => {
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
        {results.winners?.length > 0 && !Object.keys(results.hands || {}).length && (
          <div className="text-center text-yellow-400 text-sm">
            🏆 {players[results.winners[0]]?.name} wins
          </div>
        )}
      </div>

      <div className="mt-3 flex flex-col items-center gap-2">
        {!imReady ? (
          <button
            onClick={onReady}
            className="w-full bg-green-600 hover:bg-green-500 text-white text-sm font-bold py-2.5 rounded-lg transition-colors"
          >
            Continue
          </button>
        ) : (
          <span className="text-green-400 text-xs font-semibold">✓ Ready</span>
        )}
        <span className="text-zinc-600 text-[11px]">
          {readyPlayers.length}/{Math.max(totalEligible, 1)} players ready
        </span>
      </div>
    </motion.div>
  )
}

function phaseLabel(phase) {
  const map = {
    waiting: 'Waiting',
    preflop: 'Pre-flop',
    flop: 'Flop',
    turn: 'Turn',
    river: 'River',
    showdown: 'Showdown',
  }
  return map[phase] || phase
}

function actionLabel(la) {
  if (!la) return ''
  const map = { fold: 'Fold', check: 'Check', call: 'Call', raise: 'Raise', all_in: 'All-in' }
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
  const { userId, firstName, username } = useTelegram()
  const [view, setView] = useState('lobby')
  const [rooms, setRooms] = useState([])
  const [room, setRoom] = useState(null)
  const [gameState, setGameState] = useState(null)
  const [error, setError] = useState(null)
  const [connected, setConnected] = useState(false)
  const [pokerStats, setPokerStats] = useState(null)
  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)

  const effectiveId = userId || Math.floor(Math.random() * 900000) + 100000
  const effectiveName = firstName || username || 'Guest'

  const send = useCallback((msg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  useEffect(() => {
    if (effectiveId && view === 'lobby') {
      fetch(`/api/poker/stats/${effectiveId}`)
        .then(r => r.ok ? r.json() : null)
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
      ws.send(JSON.stringify({ type: 'auth', userId: effectiveId, name: effectiveName }))
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
        case 'reconnected':
          setRoom(data.room)
          if (data.room.started) setView('game')
          else setView('waiting')
          break
        case 'left_room':
          setRoom(null)
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
  }, [effectiveId, effectiveName])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const handleLeave = () => {
    if (room?.id) {
      fetch('/api/poker/invite/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ roomId: room.id })
      }).catch(() => {})
    }
    send({ type: 'leave_room' })
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6 pb-20"
    >
      {!connected && (
        <div className="text-center text-zinc-500 text-sm py-8">Connecting...</div>
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

      {connected && view === 'lobby' && <Lobby rooms={rooms} send={send} userId={effectiveId} pokerStats={pokerStats} />}
      {connected && view === 'waiting' && <WaitingRoom room={room} send={send} userId={effectiveId} />}
      {connected && view === 'game' && <GameTable state={gameState} send={send} userId={effectiveId} onLeave={handleLeave} />}
    </motion.div>
  )
}
