import confetti from 'canvas-confetti'
import { AnimatePresence, motion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTelegram } from '../context/TelegramContext'
import useCasinoSounds from '../hooks/useCasinoSounds'

const DAILY_BONUS = 50
const INITIAL_BALANCE = 100

const GAME_IDS = ['slots', 'coinflip', 'roulette', 'slots5x5', 'rocket', 'race']
const GAME_LABELS = { slots: '🎰 Бандит', coinflip: '🪙 Монетка', roulette: '🎡 Рулетка', slots5x5: '🎲 Слоты 5×5', rocket: '🚀 Ракетка', race: '🏁 Скачки' }

function secureRandom() {
  const buf = new Uint32Array(1)
  crypto.getRandomValues(buf)
  return buf[0] / 0x100000000
}

function weighted(symbols, weights) {
  const total = weights.reduce((a, b) => a + b, 0)
  let r = secureRandom() * total
  for (let i = 0; i < symbols.length; i++) { r -= weights[i]; if (r <= 0) return symbols[i] }
  return symbols[symbols.length - 1]
}

// ===== rocket crash helpers =====
const ROCKET_BET_MS = 3000
const ROCKET_FLY_MS = 9000
const ROCKET_POST_MS = 3000
const ROCKET_RATE = 0.0005
const ROCKET_MAX = 100
const ROCKET_SEED_TTL_MS = 14400000

function cyrb53(str, seed = 0) {
  let h1 = 0xdeadbeef ^ seed, h2 = 0x41c6ce57 ^ seed
  for (let i = 0; i < str.length; i++) {
    const ch = str.charCodeAt(i)
    h1 = Math.imul(h1 ^ ch, 2654435761)
    h2 = Math.imul(h2 ^ ch, 1597334677)
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507)
  h1 ^= Math.imul(h2 ^ (h2 >>> 16), 3266489909)
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507)
  h2 ^= Math.imul(h1 ^ (h1 >>> 16), 3266489909)
  return 4294967296 * (2097151 & h2) + (h1 >>> 0)
}

function rocketCrashPoint(seed, round) {
  const check = cyrb53(`${seed}:${round}:c`)
  if (check % 25 === 0) return 1.00
  const h = cyrb53(`${seed}:${round}`)
  const u = h / (2 ** 53)
  const cp = 1 / (1 - u)
  return Math.min(ROCKET_MAX, Math.max(1.01, Math.floor(cp * 100) / 100))
}

function rocketCrashMs(cp) {
  return cp <= 1.00 ? 0 : Math.min(Math.log(cp) / ROCKET_RATE, ROCKET_FLY_MS)
}

function rocketRoundDur(seed, n) {
  return ROCKET_BET_MS + rocketCrashMs(rocketCrashPoint(seed, n)) + ROCKET_POST_MS
}

function rocketFindRound(seed, periodStart, now) {
  let t = periodStart, n = 0
  while (true) {
    const dur = rocketRoundDur(seed, n)
    if (t + dur > now) return { round: n, start: t, dur }
    t += dur
    n++
  }
}

// ===== monkey race helpers =====
const RACE_MONKEYS = [
  { name: 'Бананчик', emoji: '🍌', mult: 2.8, color: '#eab308' },
  { name: 'Кокос', emoji: '🥥', mult: 3.4, color: '#f59e0b' },
  { name: 'Шимпа', emoji: '🐒', mult: 4.2, color: '#f97316' },
  { name: 'Горилла', emoji: '🦍', mult: 6.5, color: '#ef4444' },
  { name: 'Мандарин', emoji: '🍊', mult: 10, color: '#ec4899' },
  { name: 'Кинг-Конг', emoji: '👑', mult: 20, color: '#a855f7' },
]
const RACE_WEIGHTS = [30, 25, 20, 13, 8, 4]
const RACE_CYCLE_MS = 15000
const RACE_BET_MS = 7000
const RACE_RUN_MS = 5000
const RACE_SEED_TTL_MS = 14400000

function raceWinner(seed, round) {
  const h = cyrb53(`${seed}:${round}:race`)
  let r = h % 100
  for (let i = 0; i < RACE_WEIGHTS.length; i++) {
    r -= RACE_WEIGHTS[i]
    if (r < 0) return i
  }
  return 0
}

function raceFinals(seed, round, winner) {
  return RACE_MONKEYS.map((_, i) => {
    if (i === winner) return 100
    const h = cyrb53(`${seed}:${round}:pos:${i}`)
    return 65 + (h % 30)
  })
}

function GameBack({ onClick }) {
  return (
    <button onClick={onClick}
      className="text-spotify-text hover:text-white text-sm mb-4 flex items-center gap-1 transition-colors">
      ← Назад
    </button>
  )
}

function BetSelector({ bet, setBet, balance }) {
  const opts = [5, 10, 25, 50].filter(b => b <= balance)
  return (
    <div className="flex gap-2 justify-center mb-4">
      {opts.map(b => (
        <button key={b} onClick={() => setBet(b)}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors
            ${bet === b ? 'bg-yellow-500 text-black' : 'bg-white/10 text-white/70 hover:bg-white/20'}`}>
          {b} 🐵
        </button>
      ))}
    </div>
  )
}

// ===== 3-reel slot =====
const SYMBOLS = ['🍒', '🍋', '🔔', '⭐', '💎', '7️⃣']
const SYMBOL_WEIGHTS = [30, 25, 20, 13, 8, 4]
const PAYOUTS = { '🍒': 80, '🍋': 120, '🔔': 200, '⭐': 350, '💎': 700, '7️⃣': 1500 }
const SPIN_COST = 10
const PAIR_PAYOUT = 5
const CELL_SIZE = 80
const EXTRA_SPINS = 4

function buildStrip(final, symbols) {
  const cells = []
  for (let round = 0; round < EXTRA_SPINS; round++)
    for (const s of symbols) cells.push(s)
  cells.push(final)
  return cells
}

function SlotReel({ symbol, spinning, reelIndex }) {
  const strip = useMemo(() => buildStrip(symbol, SYMBOLS), [symbol, spinning])
  const finalOffset = -(strip.length * CELL_SIZE - CELL_SIZE)
  const duration = 1.6 + reelIndex * 0.4

  return (
    <div className="w-20 h-20 rounded-xl overflow-hidden border-2 border-yellow-500/30"
      style={{ height: CELL_SIZE, background: 'linear-gradient(135deg, #1a1a2e, #16213e)' }}>
      <motion.div className="flex flex-col"
        initial={{ y: 0 }}
        animate={spinning ? { y: finalOffset } : { y: 0 }}
        transition={spinning ? { duration, ease: [0.2, 0.8, 0.3, 1] } : { duration: 0 }}>
        {(spinning ? strip : [symbol]).map((s, i) => (
          <div key={i} className="flex items-center justify-center shrink-0 text-4xl"
            style={{ width: CELL_SIZE, height: CELL_SIZE }}>{s}</div>
        ))}
      </motion.div>
    </div>
  )
}

function SlotMachine({ balance, onBalanceChange, onBack, onGameResult, sound }) {
  const [reels, setReels] = useState(['🍒', '💎', '🍒'])
  const [spinning, setSpinning] = useState(false)
  const [lastWin, setLastWin] = useState(null)

  const spin = () => {
    if (spinning || balance < SPIN_COST) return
    onBalanceChange(-SPIN_COST)
    setLastWin(null)
    sound('spin')
    const results = [weighted(SYMBOLS, SYMBOL_WEIGHTS), weighted(SYMBOLS, SYMBOL_WEIGHTS), weighted(SYMBOLS, SYMBOL_WEIGHTS)]
    setReels(results)
    setSpinning(true)
    for (let i = 0; i < 3; i++) setTimeout(() => sound('reelStop'), (1.6 + i * 0.4) * 1000)
    setTimeout(() => {
      setSpinning(false)
      let win = 0
      if (results[0] === results[1] && results[1] === results[2]) win = PAYOUTS[results[0]]
      else if (results[0] === results[1] || results[1] === results[2] || results[0] === results[2]) win = PAIR_PAYOUT
      if (win > 0) {
        onBalanceChange(win)
        setLastWin(win)
        if (win >= 100) { confetti({ particleCount: 150, spread: 70, origin: { y: 0.6 } }); sound('bigWin') }
        else sound('win')
      } else {
        sound('lose')
      }
      onGameResult('slots', SPIN_COST, win)
    }, (1.6 + 2 * 0.4) * 1000 + 100)
  }

  return (
    <motion.div initial={{ opacity: 0, x: 50 }} animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }} className="w-full max-w-sm mx-auto">
      <GameBack onClick={onBack} />
      <div className="rounded-2xl p-6 w-full border border-white/5"
        style={{ background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)' }}>
        <h2 className="text-center text-white font-bold text-xl mb-1">🎰 Однорукий бандит</h2>
        <p className="text-center text-white/40 text-xs mb-6">Ставка: {SPIN_COST} 🐵</p>
        <div className="flex justify-center gap-3 mb-6">
          {reels.map((s, i) => <SlotReel key={i} symbol={s} spinning={spinning} reelIndex={i} />)}
        </div>
        <motion.button whileTap={{ scale: 0.95 }} onClick={spin}
          disabled={spinning || balance < SPIN_COST}
          className="w-full py-3 rounded-full font-bold text-sm transition-colors mb-3
            bg-gradient-to-r from-yellow-500 to-orange-500 hover:from-yellow-400 hover:to-orange-400 text-black
            disabled:opacity-40 disabled:cursor-not-allowed">
          {spinning ? 'Кручу...' : balance < SPIN_COST ? 'Мало обезьянок' : `КРУТИТЬ — ${SPIN_COST} 🐵`}
        </motion.button>
        <AnimatePresence>
          {lastWin !== null && (
            <motion.p initial={{ opacity: 0, y: 10, scale: 0.8 }} animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0 }}
              className={`text-center font-bold text-lg ${lastWin >= 100 ? 'text-yellow-400' : 'text-spotify-green'}`}>
              +{lastWin} 🐵
            </motion.p>
          )}
        </AnimatePresence>
      </div>
      <div className="mt-4 rounded-xl p-4 border border-white/5" style={{ background: 'rgba(26,26,46,0.8)' }}>
        <h3 className="text-white font-semibold text-sm mb-3">Выплаты</h3>
        <div className="grid grid-cols-3 gap-2 text-center">
          {SYMBOLS.map(s => (
            <div key={s} className="bg-white/5 rounded-lg py-2 border border-white/5">
              <span className="text-xl">{s}{s}{s}</span>
              <p className="text-yellow-400 text-xs mt-1 font-bold">{PAYOUTS[s]} 🐵</p>
            </div>
          ))}
        </div>
        <div className="mt-2 bg-white/5 rounded-lg py-2 text-center border border-white/5">
          <span className="text-sm text-white/70">Любая пара</span>
          <p className="text-spotify-text text-xs mt-0.5">{PAIR_PAYOUT} 🐵</p>
        </div>
      </div>
    </motion.div>
  )
}

// ===== coin flip =====
function CoinFlip({ balance, onBalanceChange, onBack, onGameResult, sound }) {
  const [bet, setBet] = useState(10)
  const [flipping, setFlipping] = useState(false)
  const [result, setResult] = useState(null)
  const [won, setWon] = useState(null)

  const flip = (choice) => {
    const b = Math.min(bet, balance)
    if (flipping || b < 1) return
    onBalanceChange(-b)
    setWon(null)
    setResult(null)
    setFlipping(true)
    sound('coinFlip')

    const isHeads = secureRandom() < 0.5
    const playerWon = (choice === 'heads') === isHeads

    setTimeout(() => {
      sound('coinLand')
      setResult(isHeads ? 'heads' : 'tails')
      setFlipping(false)
      if (playerWon) {
        const winAmount = Math.floor(b * 1.9)
        onBalanceChange(winAmount)
        setWon(winAmount)
        if (winAmount >= 40) { confetti({ particleCount: 80, spread: 50, origin: { y: 0.5 } }); sound('bigWin') }
        else sound('win')
        onGameResult('coinflip', b, winAmount)
      } else {
        setWon(0)
        sound('lose')
        onGameResult('coinflip', b, 0)
      }
    }, 1400)
  }

  useEffect(() => { if (bet > balance && balance > 0) setBet(Math.min(balance, 10)) }, [balance])

  return (
    <motion.div initial={{ opacity: 0, x: 50 }} animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }} className="w-full max-w-sm mx-auto">
      <GameBack onClick={onBack} />
      <div className="rounded-2xl p-6 border border-white/5"
        style={{ background: 'linear-gradient(135deg, #3d2b1f 0%, #78621a 50%, #3d2b1f 100%)' }}>
        <h2 className="text-center text-white font-bold text-xl mb-1">🪙 Монетка</h2>
        <p className="text-center text-white/40 text-xs mb-4">Угадай сторону — x1.9</p>

        <BetSelector bet={bet} setBet={setBet} balance={balance} />

        <div className="flex justify-center mb-6">
          <motion.div
            className="w-28 h-28 rounded-full flex items-center justify-center text-5xl shadow-lg"
            style={{
              background: result === 'tails'
                ? 'linear-gradient(135deg, #a0a0a0, #606060)'
                : 'linear-gradient(135deg, #ffd700, #b8860b)',
              boxShadow: '0 0 25px rgba(255,215,0,0.25)'
            }}
            animate={flipping ? { rotateX: [0, 360, 720, 1080, 1440] } : { rotateX: 0 }}
            transition={flipping ? { duration: 1.3, ease: [0.2, 0.8, 0.3, 1] } : { duration: 0 }}>
            {flipping ? '✨' : result === 'heads' ? '🦅' : result === 'tails' ? '🌙' : '🪙'}
          </motion.div>
        </div>

        <div className="grid grid-cols-2 gap-3 mb-3">
          <motion.button whileTap={{ scale: 0.95 }} onClick={() => flip('heads')}
            disabled={flipping || balance < 1}
            className="py-3 rounded-xl font-bold text-sm transition-colors
              bg-gradient-to-r from-amber-600 to-yellow-500 text-black
              disabled:opacity-40 disabled:cursor-not-allowed">
            🦅 Орёл
          </motion.button>
          <motion.button whileTap={{ scale: 0.95 }} onClick={() => flip('tails')}
            disabled={flipping || balance < 1}
            className="py-3 rounded-xl font-bold text-sm transition-colors
              bg-gradient-to-r from-gray-500 to-gray-400 text-black
              disabled:opacity-40 disabled:cursor-not-allowed">
            🌙 Решка
          </motion.button>
        </div>
        <AnimatePresence>
          {won !== null && !flipping && (
            <motion.p initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className={`text-center font-bold text-lg ${won > 0 ? 'text-yellow-400' : 'text-red-400'}`}>
              {won > 0 ? `+${won} 🐵` : `Не повезло!`}
            </motion.p>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}

// ===== roulette =====
const RED_NUMS = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36])
const WHEEL_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
const SECTOR_DEG = 360 / 37

function numColor(n) { return n === 0 ? 'green' : RED_NUMS.has(n) ? 'red' : 'black' }
function sectorFill(n) {
  const c = numColor(n)
  return c === 'red' ? '#c0392b' : c === 'green' ? '#27ae60' : '#2c3e50'
}

function RouletteWheel({ rotation, spinning }) {
  const R = 125
  const inner = R * 0.55
  const textR = R * 0.8
  const DEG2RAD = Math.PI / 180

  const sectors = useMemo(() => WHEEL_ORDER.map((num, i) => {
    const startDeg = i * SECTOR_DEG
    const endDeg = (i + 1) * SECTOR_DEG
    const midDeg = (startDeg + endDeg) / 2
    const sRad = (startDeg - 90) * DEG2RAD
    const eRad = (endDeg - 90) * DEG2RAD
    const mRad = (midDeg - 90) * DEG2RAD

    const x1 = R * Math.cos(sRad), y1 = R * Math.sin(sRad)
    const x2 = R * Math.cos(eRad), y2 = R * Math.sin(eRad)
    const ix1 = inner * Math.cos(sRad), iy1 = inner * Math.sin(sRad)
    const ix2 = inner * Math.cos(eRad), iy2 = inner * Math.sin(eRad)
    const tx = textR * Math.cos(mRad), ty = textR * Math.sin(mRad)

    return {
      num,
      path: `M ${ix1} ${iy1} L ${x1} ${y1} A ${R} ${R} 0 0 1 ${x2} ${y2} L ${ix2} ${iy2} A ${inner} ${inner} 0 0 0 ${ix1} ${iy1} Z`,
      fill: sectorFill(num), tx, ty, textRot: midDeg,
    }
  }), [])

  return (
    <div className="relative mx-auto mb-4" style={{ width: 270, height: 270 }}>
      <div className="absolute left-1/2 -translate-x-1/2 z-20" style={{ top: -2 }}>
        <div className="w-0 h-0 border-l-[10px] border-r-[10px] border-t-[18px]
          border-l-transparent border-r-transparent border-t-yellow-400
          drop-shadow-[0_0_6px_rgba(250,204,21,0.7)]" />
      </div>

      <motion.div
        className="w-full h-full"
        animate={{ rotate: rotation }}
        transition={spinning ? { duration: 4.5, ease: [0.15, 0.7, 0.1, 1] } : { duration: 0 }}>
        <svg viewBox={`${-R - 8} ${-R - 8} ${(R + 8) * 2} ${(R + 8) * 2}`} className="w-full h-full">
          <circle cx="0" cy="0" r={R + 3} fill="none" stroke="#c9a84c" strokeWidth="4" />
          <circle cx="0" cy="0" r={R} fill="none" stroke="#8b7a3a" strokeWidth="1" />
          {sectors.map(s => (
            <g key={s.num}>
              <path d={s.path} fill={s.fill} stroke="#1a1a2e" strokeWidth="0.6" />
              <text x={s.tx} y={s.ty} fill="white" fontSize="8" fontWeight="bold"
                textAnchor="middle" dominantBaseline="middle"
                transform={`rotate(${s.textRot}, ${s.tx}, ${s.ty})`}>
                {s.num}
              </text>
            </g>
          ))}
          <circle cx="0" cy="0" r={inner - 2} fill="#1a1a2e" stroke="#c9a84c" strokeWidth="1.5" />
          <text x="0" y="0" fill="#c9a84c" fontSize="28" textAnchor="middle" dominantBaseline="middle">🎰</text>
        </svg>
      </motion.div>

      <motion.div className="absolute inset-0 pointer-events-none z-10"
        animate={spinning ? { rotate: [0, -2160] } : { rotate: 0 }}
        transition={spinning ? { duration: 4.5, ease: [0.25, 0.85, 0.1, 1] } : { duration: 0 }}>
        <div className="absolute left-1/2 -ml-2" style={{ top: 6 }}>
          <div className="w-4 h-4 rounded-full bg-white shadow-[0_0_8px_rgba(255,255,255,0.8)]" />
        </div>
      </motion.div>
    </div>
  )
}

function calcRouletteWin(num, betChoice, bet) {
  if (!betChoice) return 0
  const { type, value } = betChoice
  if (type === 'number') return value === num ? bet * 36 : 0
  if (num === 0) return 0
  if (type === 'color') return (value === 'red' && RED_NUMS.has(num)) || (value === 'black' && !RED_NUMS.has(num)) ? bet * 2 : 0
  if (type === 'even') return num % 2 === 0 ? bet * 2 : 0
  if (type === 'odd') return num % 2 === 1 ? bet * 2 : 0
  if (type === 'half') return value === 1 ? (num <= 18 ? bet * 2 : 0) : (num >= 19 ? bet * 2 : 0)
  if (type === 'dozen') {
    if (value === 1 && num >= 1 && num <= 12) return bet * 3
    if (value === 2 && num >= 13 && num <= 24) return bet * 3
    if (value === 3 && num >= 25 && num <= 36) return bet * 3
  }
  return 0
}

function Roulette({ balance, onBalanceChange, onBack, onGameResult, sound }) {
  const [bet, setBet] = useState(10)
  const [spinning, setSpinning] = useState(false)
  const [betChoice, setBetChoice] = useState(null)
  const [result, setResult] = useState(null)
  const [lastWin, setLastWin] = useState(null)
  const [showNums, setShowNums] = useState(false)
  const [wheelRot, setWheelRot] = useState(0)
  const timerRef = useRef(null)

  useEffect(() => { if (bet > balance && balance > 0) setBet(Math.min(balance, 10)) }, [balance])
  useEffect(() => () => clearTimeout(timerRef.current), [])

  const chooseBet = (type, value) => {
    sound('tick')
    setBetChoice(prev => prev?.type === type && prev?.value === value ? null : { type, value })
  }
  const isSelected = (type, value) => betChoice?.type === type && betChoice?.value === value

  const spin = () => {
    if (spinning || balance < bet || !betChoice) return
    onBalanceChange(-bet)
    setLastWin(null)
    setResult(null)
    setSpinning(true)
    sound('rouletteSpin')

    const winNum = Math.floor(secureRandom() * 37)
    const targetIdx = WHEEL_ORDER.indexOf(winNum)
    const targetAngle = 360 - (targetIdx * SECTOR_DEG + SECTOR_DEG / 2)
    const spins = (5 + Math.floor(secureRandom() * 3)) * 360
    const currentMod = ((wheelRot % 360) + 360) % 360
    const delta = ((targetAngle - currentMod) + 360) % 360
    const newRot = wheelRot + spins + delta

    setWheelRot(newRot)

    timerRef.current = setTimeout(() => {
      sound('rouletteBall')
      setResult(winNum)
      setSpinning(false)
      const win = calcRouletteWin(winNum, betChoice, bet)
      if (win > 0) {
        onBalanceChange(win)
        setLastWin(win)
        if (win >= 50) { confetti({ particleCount: 100, spread: 60, origin: { y: 0.5 } }); sound('bigWin') }
        else sound('win')
      } else {
        setLastWin(0)
        sound('lose')
      }
      onGameResult('roulette', bet, win)
    }, 4700)
  }

  const selCls = (active) => `px-2.5 py-2 rounded-lg text-xs font-semibold transition-colors
    ${active ? 'bg-yellow-500 text-black' : 'bg-white/10 text-white/70 hover:bg-white/20'}`

  const resultColor = result != null ? numColor(result) : null

  return (
    <motion.div initial={{ opacity: 0, x: 50 }} animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }} className="w-full max-w-sm mx-auto">
      <GameBack onClick={onBack} />
      <div className="rounded-2xl p-5 border border-white/5"
        style={{ background: 'linear-gradient(135deg, #1a0a0a 0%, #4a0e0e 50%, #1a0a0a 100%)' }}>
        <h2 className="text-center text-white font-bold text-xl mb-1">🎡 Рулетка</h2>
        <p className="text-center text-white/40 text-xs mb-3">Европейская — 0-36</p>

        <RouletteWheel rotation={wheelRot} spinning={spinning} />

        <motion.button whileTap={{ scale: 0.95 }} onClick={spin}
          disabled={spinning || balance < bet || !betChoice}
          className="w-full py-3 rounded-full font-bold text-sm transition-colors mb-3
            bg-gradient-to-r from-red-600 to-rose-500 hover:from-red-500 hover:to-rose-400 text-white
            disabled:opacity-40 disabled:cursor-not-allowed">
          {spinning ? 'Крутится...' : !betChoice ? 'Выбери ставку' : `КРУТИТЬ — ${bet} 🐵`}
        </motion.button>

        <AnimatePresence>
          {result !== null && !spinning && (
            <motion.div initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}
              className="flex flex-col items-center mb-3">
              <div className={`w-12 h-12 rounded-full flex items-center justify-center text-lg font-bold text-white mb-1
                ${resultColor === 'red' ? 'bg-red-700' : resultColor === 'green' ? 'bg-green-700' : 'bg-zinc-700'}`}>
                {result}
              </div>
              <p className={`font-bold text-lg ${lastWin > 0 ? 'text-yellow-400' : 'text-red-400'}`}>
                {lastWin > 0 ? `+${lastWin} 🐵` : 'Не повезло!'}
              </p>
            </motion.div>
          )}
        </AnimatePresence>

        <BetSelector bet={bet} setBet={setBet} balance={balance} />

        <div className="flex flex-wrap gap-1.5 justify-center mb-2">
          <button onClick={() => chooseBet('color', 'red')} className={selCls(isSelected('color', 'red'))}>🔴 Красное ×2</button>
          <button onClick={() => chooseBet('color', 'black')} className={selCls(isSelected('color', 'black'))}>⚫ Чёрное ×2</button>
          <button onClick={() => chooseBet('even', true)} className={selCls(isSelected('even', true))}>Чёт ×2</button>
          <button onClick={() => chooseBet('odd', true)} className={selCls(isSelected('odd', true))}>Нечёт ×2</button>
        </div>
        <div className="flex flex-wrap gap-1.5 justify-center mb-2">
          <button onClick={() => chooseBet('half', 1)} className={selCls(isSelected('half', 1))}>1-18 ×2</button>
          <button onClick={() => chooseBet('half', 2)} className={selCls(isSelected('half', 2))}>19-36 ×2</button>
          <button onClick={() => chooseBet('dozen', 1)} className={selCls(isSelected('dozen', 1))}>1-12 ×3</button>
          <button onClick={() => chooseBet('dozen', 2)} className={selCls(isSelected('dozen', 2))}>13-24 ×3</button>
          <button onClick={() => chooseBet('dozen', 3)} className={selCls(isSelected('dozen', 3))}>25-36 ×3</button>
        </div>

        <button onClick={() => setShowNums(!showNums)}
          className="w-full text-center text-xs text-white/50 hover:text-white/80 transition-colors mb-2">
          {showNums ? 'Скрыть числа ▲' : 'Число ×36 ▼'}
        </button>
        <AnimatePresence>
          {showNums && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
              <div className="grid grid-cols-7 gap-1 mb-3">
                <button onClick={() => chooseBet('number', 0)}
                  className={`col-span-7 py-1.5 rounded text-xs font-bold transition-colors
                    ${isSelected('number', 0) ? 'ring-2 ring-yellow-400 bg-green-700' : 'bg-green-700/80 hover:bg-green-600'} text-white`}>
                  0
                </button>
                {Array.from({ length: 36 }, (_, i) => i + 1).map(n => (
                  <button key={n} onClick={() => chooseBet('number', n)}
                    className={`py-1.5 rounded text-[11px] font-bold transition-colors
                      ${isSelected('number', n) ? 'ring-2 ring-yellow-400' : ''}
                      ${RED_NUMS.has(n) ? 'bg-red-700/80 hover:bg-red-600' : 'bg-zinc-700/80 hover:bg-zinc-600'} text-white`}>
                    {n}
                  </button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}

// ===== slots 5x5 =====
const S5 = ['🍇', '🍊', '🍉', '🔔', '⭐', '💎', '🐵']
const W5 = [32, 26, 20, 11, 6, 3, 2]
const PAY5 = {
  '🍇': [2, 6, 20],
  '🍊': [3, 10, 35],
  '🍉': [5, 15, 50],
  '🔔': [8, 25, 80],
  '⭐': [12, 40, 130],
  '💎': [20, 65, 220],
  '🐵': [10, 30, 100],
}
const SPIN5_COST = 10

function genGrid() {
  return Array.from({ length: 5 }, () =>
    Array.from({ length: 5 }, () => weighted(S5, W5)))
}

function checkLineRuns(coords, cellFn) {
  const symbols = coords.map(([r, c]) => cellFn(r, c))
  const results = []
  let i = 0
  while (i < symbols.length) {
    let base = symbols[i] === '🐵' ? null : symbols[i]
    let len = 1
    for (let j = i + 1; j < symbols.length; j++) {
      const s = symbols[j]
      if (s === '🐵') { len++; continue }
      if (base === null) { base = s; len++; continue }
      if (s === base) { len++; continue }
      break
    }
    if (len >= 3 && base) {
      results.push({ symbol: base, length: len, cells: coords.slice(i, i + len) })
      i += len
    } else {
      i++
    }
  }
  return results
}

function findClusters(cols) {
  const visited = Array.from({ length: 5 }, () => Array(5).fill(false))
  const clusters = []
  for (let r = 0; r < 5; r++) {
    for (let c = 0; c < 5; c++) {
      if (visited[r][c]) continue
      const sym = cols[c][r]
      if (sym === '🐵') { visited[r][c] = true; continue }
      const queue = [[r, c]]
      const cells = []
      visited[r][c] = true
      while (queue.length > 0) {
        const [cr, cc] = queue.shift()
        cells.push([cr, cc])
        for (const [dr, dc] of [[0, 1], [0, -1], [1, 0], [-1, 0]]) {
          const nr = cr + dr, nc = cc + dc
          if (nr < 0 || nr >= 5 || nc < 0 || nc >= 5 || visited[nr][nc]) continue
          if (cols[nc][nr] === sym) { visited[nr][nc] = true; queue.push([nr, nc]) }
        }
      }
      if (cells.length >= 6) clusters.push({ symbol: sym, size: cells.length, cells })
    }
  }
  return clusters
}

function clusterPayout(sym, size) {
  const base = PAY5[sym]
  if (size >= 9) return base[2]
  if (size >= 7) return base[1]
  return base[0]
}

function check5x5AllWins(cols) {
  const cell = (r, c) => cols[c]?.[r]
  const lineWins = []
  const winCells = new Set()

  const addWins = (label, runs) => {
    runs.forEach(result => {
      lineWins.push({ ...result, label })
      result.cells.forEach(([r, c]) => winCells.add(`${r},${c}`))
    })
  }

  for (let r = 0; r < 5; r++)
    addWins(`Ряд ${r + 1}`, checkLineRuns([0, 1, 2, 3, 4].map(c => [r, c]), cell))

  for (let c = 0; c < 5; c++)
    addWins(`Кол ${c + 1}`, checkLineRuns([0, 1, 2, 3, 4].map(r => [r, c]), cell))

  addWins('Диаг ↘', checkLineRuns([0, 1, 2, 3, 4].map(i => [i, i]), cell))
  addWins('Диаг ↙', checkLineRuns([0, 1, 2, 3, 4].map(i => [i, 4 - i]), cell))

  const clusters = findClusters(cols)
  clusters.forEach(cl => cl.cells.forEach(([r, c]) => winCells.add(`${r},${c}`)))

  let totalPay = lineWins.reduce((s, w) => s + PAY5[w.symbol][w.length - 3], 0)
  totalPay += clusters.reduce((s, cl) => s + clusterPayout(cl.symbol, cl.size), 0)

  return { lineWins, clusters, winCells, totalPay }
}

function Slots5x5({ balance, onBalanceChange, onBack, onGameResult, sound }) {
  const [grid, setGrid] = useState(() => genGrid())
  const [spinning, setSpinning] = useState(false)
  const [winData, setWinData] = useState({ lineWins: [], clusters: [], winCells: new Set(), totalPay: 0 })
  const [lastWin, setLastWin] = useState(null)
  const intervalRef = useRef(null)

  const spin = () => {
    if (spinning || balance < SPIN5_COST) return
    onBalanceChange(-SPIN5_COST)
    setLastWin(null)
    setWinData({ lineWins: [], clusters: [], winCells: new Set(), totalPay: 0 })
    setSpinning(true)
    sound('spin')

    const finalGrid = genGrid()
    const locked = new Set()

    intervalRef.current = setInterval(() => {
      setGrid(Array.from({ length: 5 }, (_, i) =>
        locked.has(i) ? finalGrid[i] : Array.from({ length: 5 }, () => weighted(S5, W5))))
    }, 80)

    for (let c = 0; c < 5; c++) {
      setTimeout(() => {
        locked.add(c)
        sound('reelStop')
        setGrid(prev => { const cp = [...prev]; cp[c] = finalGrid[c]; return cp })
      }, 500 + c * 300)
    }

    setTimeout(() => {
      clearInterval(intervalRef.current)
      setGrid(finalGrid)
      setSpinning(false)
      const wd = check5x5AllWins(finalGrid)
      setWinData(wd)
      if (wd.totalPay > 0) {
        onBalanceChange(wd.totalPay)
        setLastWin(wd.totalPay)
        if (wd.totalPay >= 50) { confetti({ particleCount: 120, spread: 70, origin: { y: 0.6 } }); sound('bigWin') }
        else sound('win')
      } else {
        sound('lose')
      }
      onGameResult('slots5x5', SPIN5_COST, wd.totalPay)
    }, 500 + 5 * 300 + 200)
  }

  useEffect(() => () => clearInterval(intervalRef.current), [])

  return (
    <motion.div initial={{ opacity: 0, x: 50 }} animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }} className="w-full max-w-sm mx-auto">
      <GameBack onClick={onBack} />
      <div className="rounded-2xl p-4 border border-white/5"
        style={{ background: 'linear-gradient(135deg, #0a1628 0%, #162040 50%, #0a1628 100%)' }}>
        <h2 className="text-center text-white font-bold text-xl mb-1">🎲 Слоты 5×5</h2>
        <p className="text-center text-white/40 text-xs mb-1">↔ ↕ ↗ ↘ кластеры · 🐵 = джокер</p>
        <p className="text-center text-white/40 text-xs mb-4">Ставка: {SPIN5_COST} 🐵</p>

        <div className="rounded-xl p-2 mb-4" style={{ background: 'rgba(0,0,0,0.3)' }}>
          <div className="grid grid-cols-5 gap-1">
            {Array.from({ length: 25 }, (_, i) => {
              const row = Math.floor(i / 5)
              const col = i % 5
              const s = grid[col]?.[row] || '🍇'
              const highlight = winData.winCells.has(`${row},${col}`)
              return (
                <motion.div key={i}
                  animate={highlight ? { scale: [1, 1.1, 1] } : { scale: 1 }}
                  transition={highlight ? { duration: 0.6, repeat: Infinity } : { duration: 0.15 }}
                  className={`flex items-center justify-center text-2xl rounded-lg
                    ${highlight ? 'bg-yellow-500/20 ring-1 ring-yellow-400/60' : 'bg-white/5'}
                    ${spinning && !highlight ? 'opacity-80' : ''}`}
                  style={{ aspectRatio: '1', minHeight: 48 }}>
                  {s}
                </motion.div>
              )
            })}
          </div>
        </div>

        <motion.button whileTap={{ scale: 0.95 }} onClick={spin}
          disabled={spinning || balance < SPIN5_COST}
          className="w-full py-3 rounded-full font-bold text-sm transition-colors mb-3
            bg-gradient-to-r from-blue-600 to-indigo-500 hover:from-blue-500 hover:to-indigo-400 text-white
            disabled:opacity-40 disabled:cursor-not-allowed">
          {spinning ? 'Кручу...' : balance < SPIN5_COST ? 'Мало обезьянок' : `КРУТИТЬ — ${SPIN5_COST} 🐵`}
        </motion.button>
        <AnimatePresence>
          {lastWin !== null && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
              <p className="text-center font-bold text-lg text-yellow-400">+{lastWin} 🐵</p>
              {(winData.lineWins.length > 0 || winData.clusters.length > 0) && (
                <div className="flex flex-wrap gap-1 justify-center mt-1">
                  {winData.lineWins.map((w, i) => (
                    <span key={`l${i}`} className="text-[10px] bg-yellow-500/20 text-yellow-300 px-1.5 py-0.5 rounded">
                      {w.label}: {w.symbol}×{w.length} = {PAY5[w.symbol][w.length - 3]}
                    </span>
                  ))}
                  {winData.clusters.map((cl, i) => (
                    <span key={`c${i}`} className="text-[10px] bg-purple-500/20 text-purple-300 px-1.5 py-0.5 rounded">
                      Кластер: {cl.symbol}×{cl.size} = {clusterPayout(cl.symbol, cl.size)}
                    </span>
                  ))}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="mt-4 rounded-xl p-4 border border-white/5" style={{ background: 'rgba(10,22,40,0.8)' }}>
        <h3 className="text-white font-semibold text-sm mb-2">Выплаты (3 / 4 / 5 совпадений)</h3>
        <div className="flex flex-col gap-1">
          {S5.map(s => (
            <div key={s} className="flex items-center justify-between bg-white/5 rounded-lg px-3 py-1.5">
              <span className="text-lg">{s} {s === '🐵' && <span className="text-[10px] text-yellow-400">джокер</span>}</span>
              <span className="text-xs text-white/70">{PAY5[s].join(' / ')}</span>
            </div>
          ))}
        </div>
        <p className="text-[10px] text-white/40 mt-2">
          Линии: ↔ горизонтали · ↕ вертикали · ↘↙ диагонали · Кластер 5+ касающихся
        </p>
      </div>
    </motion.div>
  )
}

// ===== rocket crash =====
function RocketStars() {
  const stars = useMemo(() =>
    Array.from({ length: 40 }, (_, i) => ({
      x: Math.random() * 100,
      size: 1 + Math.random() * 1.5,
      opacity: 0.15 + Math.random() * 0.45,
      dur: 3 + Math.random() * 4,
      delay: -Math.random() * 7,
    })), [])

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden">
      {stars.map((s, i) => (
        <div key={i} className="absolute rounded-full bg-white"
          style={{
            left: `${s.x}%`, width: s.size, height: s.size,
            animation: `rocketStar ${s.dur}s linear infinite`,
            animationDelay: `${s.delay}s`,
          }} />
      ))}
      <style>{`@keyframes rocketStar { from { top: -2%; opacity: 0.5; } to { top: 102%; opacity: 0; } }`}</style>
    </div>
  )
}

function RocketGame({ balance, onBalanceChange, onBack, onGameResult, sound }) {
  const [phase, setPhase] = useState('loading')
  const [seed, setSeed] = useState(null)
  const [serverOff, setServerOff] = useState(0)
  const [bet, setBet] = useState(10)
  const [mult, setMult] = useState(1.0)
  const [cp, setCp] = useState(0)
  const [history, setHistory] = useState([])
  const [cashedOut, setCashedOut] = useState(false)
  const [cashMult, setCashMult] = useState(0)
  const [currentBet, setCurrentBet] = useState(0)
  const [timeLeft, setTimeLeft] = useState(0)
  const [flyMs, setFlyMs] = useState(0)

  const betRef = useRef(0)
  const cashedRef = useRef(false)
  const pendingRef = useRef(null)
  const sentRef = useRef(false)
  const lastRoundRef = useRef(-1)
  const crashSndRef = useRef(false)
  const launchSndRef = useRef(false)
  const animRef = useRef(null)
  const gameResultRef = useRef(onGameResult)
  gameResultRef.current = onGameResult
  const roundInfoRef = useRef(null)
  const periodStartRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    const delay = new Promise(r => setTimeout(r, 1500))
    Promise.all([
      fetch('/api/casino/rocket/init', { credentials: 'include' })
        .then(r => r.ok ? r.json() : null),
      delay,
    ]).then(([data]) => {
      if (cancelled || !data) { if (!cancelled) setPhase('error'); return }
      const off = data.serverTime - Date.now()
      setSeed(data.seed)
      setServerOff(off)
      const ps = Math.floor(data.serverTime / ROCKET_SEED_TTL_MS) * ROCKET_SEED_TTL_MS
      periodStartRef.current = ps
      const info = rocketFindRound(data.seed, ps, data.serverTime)
      roundInfoRef.current = info
      const hist = []
      for (let i = info.round - 1; i >= Math.max(0, info.round - 15); i--)
        hist.push(rocketCrashPoint(data.seed, i))
      setHistory(hist)
    }).catch(() => { if (!cancelled) setPhase('error') })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!seed) return
    const tick = () => {
      const now = Date.now() + serverOff
      let ri = roundInfoRef.current
      if (!ri) {
        ri = rocketFindRound(seed, periodStartRef.current, now)
        roundInfoRef.current = ri
      }
      while (now >= ri.start + ri.dur) {
        const next = ri.round + 1
        const nextStart = ri.start + ri.dur
        const nextDur = rocketRoundDur(seed, next)
        ri = { round: next, start: nextStart, dur: nextDur }
        roundInfoRef.current = ri
      }

      const round = ri.round
      const elapsed = now - ri.start
      const roundCp = rocketCrashPoint(seed, round)
      const crashMs = rocketCrashMs(roundCp)

      if (round !== lastRoundRef.current) {
        if (pendingRef.current && !sentRef.current) {
          sentRef.current = true
          const p = pendingRef.current
          gameResultRef.current(p.game, p.bet, p.win)
          pendingRef.current = null
        }
        if (lastRoundRef.current >= 0) {
          const prev = rocketCrashPoint(seed, lastRoundRef.current)
          setHistory(h => [prev, ...h].slice(0, 15))
        }
        betRef.current = 0
        cashedRef.current = false
        crashSndRef.current = false
        launchSndRef.current = false
        sentRef.current = false
        setCashedOut(false)
        setCashMult(0)
        setCurrentBet(0)
        lastRoundRef.current = round
      }

      setCp(roundCp)

      if (elapsed < ROCKET_BET_MS) {
        setPhase('betting')
        setMult(1.00)
        setTimeLeft(Math.ceil((ROCKET_BET_MS - elapsed) / 1000))
        setFlyMs(0)
      } else {
        const flyElapsed = elapsed - ROCKET_BET_MS
        if (!launchSndRef.current) { launchSndRef.current = true; sound('rocketLaunch') }
        if (flyElapsed >= crashMs) {
          if (!crashSndRef.current) {
            crashSndRef.current = true
            sound('rocketCrash')
            if (betRef.current > 0 && !cashedRef.current) {
              pendingRef.current = { game: 'rocket', bet: betRef.current, win: 0 }
              sound('lose')
            }
          }
          setPhase('crashed')
          setMult(roundCp)
          setFlyMs(crashMs)
          const postEnd = ROCKET_BET_MS + crashMs + ROCKET_POST_MS
          setTimeLeft(Math.max(0, Math.ceil((postEnd - elapsed) / 1000)))
        } else {
          setPhase('flying')
          setMult(Math.floor(Math.exp(ROCKET_RATE * flyElapsed) * 100) / 100)
          setFlyMs(flyElapsed)
        }
      }
      animRef.current = requestAnimationFrame(tick)
    }
    animRef.current = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(animRef.current)
      if (pendingRef.current && !sentRef.current) {
        sentRef.current = true
        const p = pendingRef.current
        gameResultRef.current(p.game, p.bet, p.win)
      }
    }
  }, [seed, serverOff, sound])

  const placeBet = useCallback(() => {
    if (phase !== 'betting' || betRef.current > 0 || balance < bet) return
    onBalanceChange(-bet)
    betRef.current = bet
    setCurrentBet(bet)
    sound('tick')
  }, [phase, balance, bet, onBalanceChange, sound])

  const cashout = useCallback(() => {
    if (phase !== 'flying' || betRef.current <= 0 || cashedRef.current) return
    const m = mult
    const win = Math.floor(betRef.current * m)
    cashedRef.current = true
    setCashedOut(true)
    setCashMult(m)
    onBalanceChange(win)
    pendingRef.current = { game: 'rocket', bet: betRef.current, win }
    if (win >= 100) {
      confetti({ particleCount: 120, spread: 60, origin: { y: 0.5 } })
      sound('bigWin')
    } else {
      sound('win')
    }
  }, [phase, mult, onBalanceChange, sound])

  useEffect(() => {
    if (bet > balance && balance > 0) setBet(Math.min(balance, 10))
  }, [balance])

  if (phase === 'loading') {
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full max-w-sm mx-auto">
        <GameBack onClick={onBack} />
        <div className="rounded-2xl p-6 border border-white/5 flex flex-col items-center py-16 relative overflow-hidden"
          style={{ background: 'linear-gradient(135deg, #0a0a1a 0%, #1a0a2e 50%, #0a0a1a 100%)' }}>
          <RocketStars />
          <motion.div animate={{ y: [0, -15, 0], rotate: [0, 5, -5, 0] }}
            transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
            className="text-6xl mb-6 relative z-10">🚀</motion.div>
          <p className="text-white/60 text-sm mb-4 relative z-10">Подключение к орбите...</p>
          <div className="w-32 h-1 bg-white/10 rounded-full overflow-hidden relative z-10">
            <motion.div className="h-full w-1/3 bg-gradient-to-r from-orange-500 to-red-500 rounded-full"
              animate={{ x: ['-100%', '400%'] }}
              transition={{ duration: 1.2, repeat: Infinity, ease: 'easeInOut' }} />
          </div>
        </div>
      </motion.div>
    )
  }

  if (phase === 'error') {
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full max-w-sm mx-auto">
        <GameBack onClick={onBack} />
        <div className="rounded-2xl p-6 border border-white/5 text-center py-12"
          style={{ background: 'linear-gradient(135deg, #0a0a1a 0%, #1a0a2e 50%, #0a0a1a 100%)' }}>
          <p className="text-4xl mb-4">💥</p>
          <p className="text-white/60 text-sm">Ошибка подключения</p>
          <button onClick={onBack} className="mt-4 text-orange-400 text-sm hover:text-orange-300">← Вернуться</button>
        </div>
      </motion.div>
    )
  }

  const graphW = 280, graphH = 140
  const gPad = { l: 28, r: 8, t: 8, b: 12 }
  const gw = graphW - gPad.l - gPad.r, gh = graphH - gPad.t - gPad.b
  const maxFly = ROCKET_FLY_MS
  const dMs = phase === 'crashed'
    ? Math.min(cp <= 1.0 ? 0 : Math.log(cp) / ROCKET_RATE, maxFly)
    : Math.min(flyMs, maxFly)

  let graphPts = ''
  let lastPt = null
  if (dMs > 10) {
    const steps = Math.max(2, Math.min(150, Math.floor(dMs / 60)))
    const pts = []
    for (let i = 0; i <= steps; i++) {
      const t = (i / steps) * dMs
      const m = Math.exp(ROCKET_RATE * t)
      const x = gPad.l + (t / maxFly) * gw
      const yN = Math.log(m) / Math.log(ROCKET_MAX + 1)
      const y = graphH - gPad.b - yN * gh
      pts.push(`${x.toFixed(1)},${y.toFixed(1)}`)
    }
    graphPts = pts.join(' ')
    const lp = pts[pts.length - 1].split(',')
    lastPt = { x: parseFloat(lp[0]), y: parseFloat(lp[1]) }
  }

  const lineClr = phase === 'crashed' ? '#ef4444' : '#22c55e'
  const gridMs = [2, 5, 10, 25, 50, 100]

  return (
    <motion.div initial={{ opacity: 0, x: 50 }} animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }} className="w-full max-w-sm mx-auto">
      <GameBack onClick={onBack} />

      {history.length > 0 && (
        <div className="flex gap-1.5 mb-3 overflow-x-auto pb-1" style={{ scrollbarWidth: 'none' }}>
          {history.map((h, i) => (
            <span key={i} className={`shrink-0 px-2 py-0.5 rounded text-[11px] font-bold
              ${h <= 1.5 ? 'bg-red-500/20 text-red-400' :
                h <= 3 ? 'bg-orange-500/20 text-orange-400' :
                  h <= 10 ? 'bg-yellow-500/20 text-yellow-300' :
                    'bg-green-500/20 text-green-400'}`}>
              {h.toFixed(2)}×
            </span>
          ))}
        </div>
      )}

      <div className="rounded-2xl p-4 border border-white/5 relative overflow-hidden"
        style={{ background: 'linear-gradient(135deg, #0a0a1a 0%, #1a0a2e 50%, #0a0a1a 100%)' }}>
        <RocketStars />

        <h2 className="text-center text-white font-bold text-xl mb-1 relative z-10">🚀 Ракетка</h2>
        <p className="text-center text-white/30 text-[10px] mb-2 relative z-10">макс ×{ROCKET_MAX}</p>

        <div className="text-center mb-1 relative z-10" style={{ minHeight: 72 }}>
          {phase === 'betting' ? (
            <motion.div key="bet-phase" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <p className="text-white/40 text-xs mb-1">Запуск через</p>
              <p className="text-white text-4xl font-black tabular-nums">{timeLeft}с</p>
            </motion.div>
          ) : (
            <motion.div key={`fly-${Math.floor(mult)}`}>
              <motion.p
                className={`text-5xl font-black tabular-nums leading-none
                  ${phase === 'crashed' ? 'text-red-500' : cashedOut ? 'text-yellow-400' : 'text-green-400'}`}
                animate={phase === 'flying' && !cashedOut ? { scale: [1, 1.03, 1] } : {}}
                transition={{ duration: 0.5, repeat: Infinity }}>
                {mult.toFixed(2)}×
              </motion.p>
              {phase === 'crashed' && (
                <motion.p initial={{ scale: 0, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
                  className="text-red-400 text-sm font-bold mt-1">КРАШ</motion.p>
              )}
            </motion.div>
          )}
        </div>

        <div className="mb-3 relative z-10 rounded-xl overflow-hidden"
          style={{ background: 'rgba(0,0,0,0.3)' }}>
          <svg viewBox={`0 0 ${graphW} ${graphH}`} className="w-full block" style={{ height: 140 }}>
            {gridMs.map(m => {
              const yN = Math.log(m) / Math.log(ROCKET_MAX + 1)
              const y = graphH - gPad.b - yN * gh
              if (y < gPad.t || y > graphH - gPad.b) return null
              return (
                <g key={m}>
                  <line x1={gPad.l} y1={y} x2={graphW - gPad.r} y2={y}
                    stroke="white" opacity="0.06" strokeDasharray="2,4" />
                  <text x={gPad.l - 3} y={y + 3} fill="white" opacity="0.25"
                    fontSize="7" textAnchor="end">{m}×</text>
                </g>
              )
            })}
            <line x1={gPad.l} y1={graphH - gPad.b} x2={graphW - gPad.r} y2={graphH - gPad.b}
              stroke="white" opacity="0.08" />
            {graphPts && (
              <>
                <polyline points={graphPts} fill="none" stroke={lineClr}
                  strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                <polyline points={graphPts} fill="none" stroke={lineClr}
                  strokeWidth="8" strokeLinecap="round" opacity="0.12" />
              </>
            )}
            {phase === 'flying' && lastPt && (
              <text x={lastPt.x} y={lastPt.y - 10} fontSize="14" textAnchor="middle">🚀</text>
            )}
            {phase === 'crashed' && lastPt && (
              <text x={lastPt.x} y={lastPt.y - 10} fontSize="14" textAnchor="middle">💥</text>
            )}
            {phase === 'betting' && (
              <text x={graphW / 2} y={graphH / 2 + 4} fill="white" opacity="0.15"
                fontSize="11" textAnchor="middle" fontWeight="bold">ОЖИДАНИЕ ЗАПУСКА</text>
            )}
          </svg>
        </div>

        <div style={{ minHeight: 36 }} className="relative z-10">
          <AnimatePresence>
            {cashedOut && (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                className="text-center mb-3">
                <p className="text-yellow-400 font-bold text-lg">
                  Забрал на {cashMult.toFixed(2)}× → +{Math.floor(currentBet * cashMult)} 🐵
                </p>
              </motion.div>
            )}
            {phase === 'crashed' && currentBet > 0 && !cashedOut && (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                className="text-center mb-3">
                <p className="text-red-400 font-bold text-sm">Не успел! −{currentBet} 🐵</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <div className="relative z-10">
          {phase === 'betting' && (
            <>
              <BetSelector bet={bet} setBet={setBet} balance={balance} />
              <motion.button whileTap={{ scale: 0.95 }} onClick={placeBet}
                disabled={currentBet > 0 || balance < bet}
                className={`w-full py-3 rounded-full font-bold text-sm transition-colors
                  ${currentBet > 0
                    ? 'bg-green-600/30 text-green-300 cursor-default'
                    : 'bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-400 hover:to-red-400 text-white'}
                  disabled:opacity-40 disabled:cursor-not-allowed`}>
                {currentBet > 0 ? `✅ Ставка ${currentBet} 🐵` :
                  balance < bet ? 'Мало обезьянок' : `ПОСТАВИТЬ ${bet} 🐵`}
              </motion.button>
            </>
          )}

          {phase === 'flying' && (
            <motion.button whileTap={{ scale: 0.95 }} onClick={cashout}
              disabled={currentBet <= 0 || cashedOut}
              className={`w-full py-3.5 rounded-full font-bold text-sm transition-colors
                ${cashedOut
                  ? 'bg-yellow-600/30 text-yellow-300 cursor-default'
                  : currentBet > 0
                    ? 'bg-gradient-to-r from-green-500 to-emerald-400 hover:from-green-400 hover:to-emerald-300 text-black shadow-lg shadow-green-500/30 animate-pulse'
                    : 'bg-white/10 text-white/40 cursor-default'}`}>
              {cashedOut ? `✅ Забрал ${cashMult.toFixed(2)}×` :
                currentBet > 0 ? `ЗАБРАТЬ ${Math.floor(currentBet * mult)} 🐵` :
                  'Ставка не сделана'}
            </motion.button>
          )}

          {phase === 'crashed' && (
            <div className="text-center py-2">
              {currentBet === 0 && <BetSelector bet={bet} setBet={setBet} balance={balance} />}
              <p className="text-white/30 text-xs">Следующий раунд через {timeLeft}с</p>
            </div>
          )}
        </div>
      </div>

    </motion.div>
  )
}

// ===== monkey race =====
function MonkeyRace({ balance, onBalanceChange, onBack, sound }) {
  const { userId } = useTelegram()
  const [phase, setPhase] = useState('loading')
  const [seed, setSeed] = useState(null)
  const [serverOff, setServerOff] = useState(0)
  const [bet, setBet] = useState(10)
  const [selected, setSelected] = useState(-1)
  const [positions, setPositions] = useState(() => Array(6).fill(0))
  const [winner, setWinner] = useState(-1)
  const [timeLeft, setTimeLeft] = useState(0)
  const [bets, setBets] = useState([])
  const [myBet, setMyBet] = useState(null)
  const [lastResult, setLastResult] = useState(null)
  const [history, setHistory] = useState([])

  const animRef = useRef(null)
  const lastRoundRef = useRef(-1)
  const myBetRef = useRef(null)
  const finalsRef = useRef(null)
  const resultDoneRef = useRef(false)
  const phaseRef = useRef('loading')
  const lastPosRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    const delay = new Promise(r => setTimeout(r, 1200))
    Promise.all([
      fetch('/api/casino/race/init', { credentials: 'include' }).then(r => r.ok ? r.json() : null),
      delay,
    ]).then(([data]) => {
      if (cancelled || !data) { if (!cancelled) setPhase('error'); return }
      setSeed(data.seed)
      setServerOff(data.serverTime - Date.now())
    }).catch(() => { if (!cancelled) setPhase('error') })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!seed) return
    const tick = () => {
      const now = Date.now() + serverOff
      const ps = Math.floor(now / RACE_SEED_TTL_MS) * RACE_SEED_TTL_MS
      const elapsed = now - ps
      const rn = Math.floor(elapsed / RACE_CYCLE_MS)
      const off = elapsed - rn * RACE_CYCLE_MS

      if (rn !== lastRoundRef.current) {
        if (lastRoundRef.current >= 0) {
          const pw = raceWinner(seed, lastRoundRef.current)
          setHistory(h => [pw, ...h].slice(0, 10))
        }
        lastRoundRef.current = rn
        myBetRef.current = null
        finalsRef.current = null
        resultDoneRef.current = false
        setMyBet(null)
        setBets([])
        setPositions(Array(6).fill(0))
        setWinner(-1)
        setLastResult(null)
        setSelected(-1)
      }

      if (off < RACE_BET_MS) {
        if (phaseRef.current !== 'betting') { phaseRef.current = 'betting'; setPhase('betting') }
        setTimeLeft(Math.ceil((RACE_BET_MS - off) / 1000))
      } else if (off < RACE_BET_MS + RACE_RUN_MS) {
        if (phaseRef.current !== 'racing') {
          phaseRef.current = 'racing'
          setPhase('racing')
          sound('raceStart')
          const w = raceWinner(seed, rn)
          setWinner(w)
          finalsRef.current = raceFinals(seed, rn, w)
          fetch('/api/casino/race/bets', { credentials: 'include' })
            .then(r => r.ok ? r.json() : null)
            .then(d => { if (d) setBets(d.bets || []) })
            .catch(() => { })
        }
        const raceOff = off - RACE_BET_MS
        const t = raceOff / RACE_RUN_MS
        const nowMs = Date.now()
        if (finalsRef.current && nowMs - lastPosRef.current > 50) {
          lastPosRef.current = nowMs
          const e = 1 - Math.pow(1 - t, 4)
          setPositions(finalsRef.current.map(f => Math.min(f, f * e)))
        }
      } else {
        if (phaseRef.current !== 'result') {
          phaseRef.current = 'result'
          setPhase('result')
          const w = raceWinner(seed, rn)
          setWinner(w)
          if (finalsRef.current) setPositions([...finalsRef.current])
          else {
            const f = raceFinals(seed, rn, w)
            finalsRef.current = f
            setPositions(f)
          }
          if (myBetRef.current && !resultDoneRef.current) {
            resultDoneRef.current = true
            if (myBetRef.current.monkey_idx === w) {
              const winAmt = Math.floor(myBetRef.current.amount * RACE_MONKEYS[w].mult)
              setLastResult({ won: true, amount: winAmt })
              onBalanceChange(winAmt)
              if (winAmt >= 100) { confetti({ particleCount: 80, spread: 60, origin: { y: 0.5 } }); sound('bigWin') }
              else sound('win')
            } else {
              setLastResult({ won: false, amount: myBetRef.current.amount })
              sound('lose')
            }
          }
        }
        setTimeLeft(Math.ceil((RACE_CYCLE_MS - off) / 1000))
      }
      animRef.current = requestAnimationFrame(tick)
    }
    animRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(animRef.current)
  }, [seed, serverOff, sound, onBalanceChange])

  useEffect(() => {
    if (phase !== 'betting') return
    const fetchBets = () => {
      fetch('/api/casino/race/bets', { credentials: 'include' })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) setBets(d.bets || []) })
        .catch(() => { })
    }
    fetchBets()
    const iv = setInterval(fetchBets, 2500)
    return () => clearInterval(iv)
  }, [phase])

  const placeBet = useCallback(() => {
    if (phaseRef.current !== 'betting' || selected < 0 || balance < bet || myBetRef.current) return
    onBalanceChange(-bet)
    sound('tick')
    fetch('/api/casino/race/bet', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify({ monkeyIdx: selected, amount: bet }),
    })
      .then(r => { if (!r.ok) { onBalanceChange(bet); return null } return r.json() })
      .then(d => {
        if (d?.ok) {
          myBetRef.current = { monkey_idx: selected, amount: bet }
          setMyBet({ monkey_idx: selected, amount: bet })
          setBets(d.bets || [])
        }
      })
      .catch(() => onBalanceChange(bet))
  }, [selected, balance, bet, onBalanceChange, sound])

  useEffect(() => { if (bet > balance && balance > 0) setBet(Math.min(balance, 10)) }, [balance])

  if (phase === 'loading') return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full max-w-sm mx-auto">
      <GameBack onClick={onBack} />
      <div className="rounded-2xl p-6 border border-white/5 flex flex-col items-center py-12"
        style={{ background: 'linear-gradient(180deg, #071a0e 0%, #0f2b18 50%, #12200d 100%)' }}>
        <div className="flex gap-2 mb-4">
          {['🌴', '🐒', '🌴'].map((e, i) => (
            <motion.span key={i} className="text-4xl" animate={{ y: [0, -12, 0], rotate: i === 1 ? [0, 10, -10, 0] : [-5, 5, -5] }}
              transition={{ duration: 1.2 + i * 0.2, repeat: Infinity, ease: 'easeInOut', delay: i * 0.15 }}>
              {e}
            </motion.span>
          ))}
        </div>
        <p className="text-white/60 text-sm mb-1">Готовим джунгли...</p>
        <p className="text-white/30 text-[10px] mb-4">🍌 обезьянки разминаются</p>
        <div className="w-36 h-1.5 bg-white/10 rounded-full overflow-hidden">
          <motion.div className="h-full w-1/3 bg-gradient-to-r from-green-500 to-emerald-400 rounded-full"
            animate={{ x: ['-100%', '400%'] }} transition={{ duration: 1, repeat: Infinity, ease: 'easeInOut' }} />
        </div>
      </div>
    </motion.div>
  )

  if (phase === 'error') return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full max-w-sm mx-auto">
      <GameBack onClick={onBack} />
      <div className="rounded-2xl p-6 border border-white/5 text-center py-12"
        style={{ background: 'linear-gradient(135deg, #0a1a0a 0%, #1a2e0a 50%, #0a1a0a 100%)' }}>
        <p className="text-4xl mb-4">💥</p>
        <p className="text-white/60 text-sm">Ошибка подключения</p>
        <button onClick={onBack} className="mt-4 text-green-400 text-sm hover:text-green-300">← Вернуться</button>
      </div>
    </motion.div>
  )

  return (
    <motion.div initial={{ opacity: 0, x: 50 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -50 }}
      className="w-full max-w-sm mx-auto">
      <GameBack onClick={onBack} />

      {history.length > 0 && (
        <div className="flex gap-1.5 mb-3 overflow-x-auto pb-1" style={{ scrollbarWidth: 'none' }}>
          {history.map((w, i) => (
            <span key={i} className="shrink-0 px-2 py-0.5 rounded text-[11px] font-bold bg-white/10 text-white/70">
              {RACE_MONKEYS[w].emoji}
            </span>
          ))}
        </div>
      )}

      <div className="rounded-2xl p-4 border border-white/5"
        style={{ background: 'linear-gradient(135deg, #0a1a0a 0%, #1a2e0a 50%, #0a1a0a 100%)' }}>
        <h2 className="text-center text-white font-bold text-xl mb-1">🏁 Скачки обезьянок</h2>

        <div className="text-center mb-3" style={{ minHeight: 48 }}>
          <AnimatePresence mode="wait">
            {phase === 'betting' && (
              <motion.div key="bet-phase" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
                <p className="text-white/40 text-xs">🌴 Ставки открыты — кто доберётся первым?</p>
                <p className="text-white text-3xl font-black tabular-nums">{timeLeft}с</p>
              </motion.div>
            )}
            {phase === 'racing' && (
              <motion.div key="race-phase" initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}
                className="pt-1">
                <motion.p className="text-green-400 text-xl font-black"
                  animate={{ scale: [1, 1.06, 1], textShadow: ['0 0 8px rgba(74,222,128,0.3)', '0 0 16px rgba(74,222,128,0.6)', '0 0 8px rgba(74,222,128,0.3)'] }}
                  transition={{ duration: 0.5, repeat: Infinity }}>
                  🐒 ПРЫГАЮТ!
                </motion.p>
                <motion.div className="flex justify-center gap-1 mt-0.5"
                  animate={{ opacity: [0.4, 0.8, 0.4] }} transition={{ duration: 0.6, repeat: Infinity }}>
                  {['🌴', '🍌', '🌴', '🥥', '🌴'].map((e, i) => (
                    <motion.span key={i} className="text-xs" animate={{ y: [0, -3, 0] }}
                      transition={{ duration: 0.3, delay: i * 0.06, repeat: Infinity }}>
                      {e}
                    </motion.span>
                  ))}
                </motion.div>
              </motion.div>
            )}
            {phase === 'result' && winner >= 0 && (
              <motion.div key="result-phase" initial={{ opacity: 0, scale: 0.5 }} animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }} transition={{ type: 'spring', damping: 12 }}>
                <motion.p className="text-yellow-400 text-lg font-black"
                  animate={{ textShadow: ['0 0 8px rgba(234,179,8,0.3)', '0 0 20px rgba(234,179,8,0.6)', '0 0 8px rgba(234,179,8,0.3)'] }}
                  transition={{ duration: 1, repeat: Infinity }}>
                  🏆 {RACE_MONKEYS[winner].emoji} {RACE_MONKEYS[winner].name} 🏆
                </motion.p>
                <p className="text-white/30 text-xs mt-0.5">Следующий забег через {timeLeft}с</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {phase === 'betting' && !myBet && (
          <>
            <div className="grid grid-cols-3 gap-2 mb-3">
              {RACE_MONKEYS.map((m, i) => (
                <motion.button key={i} whileTap={{ scale: 0.93 }} onClick={() => setSelected(i)}
                  className={`rounded-xl p-2 text-center transition-all border relative overflow-hidden
                    ${selected === i ? 'border-green-400 shadow-lg shadow-green-500/20'
                      : 'border-white/10 hover:border-white/20'}`}
                  style={{
                    background: selected === i
                      ? `linear-gradient(135deg, ${m.color}15 0%, ${m.color}30 100%)`
                      : 'rgba(255,255,255,0.03)'
                  }}>
                  {selected === i && (
                    <motion.div className="absolute inset-0 pointer-events-none"
                      style={{ background: `radial-gradient(circle at 50% 30%, ${m.color}20, transparent 70%)` }}
                      animate={{ opacity: [0.5, 1, 0.5] }} transition={{ duration: 1.5, repeat: Infinity }} />
                  )}
                  <motion.div className="text-2xl relative"
                    animate={selected === i ? { y: [0, -4, 0], rotate: [0, 5, -5, 0] } : {}}
                    transition={{ duration: 0.8, repeat: selected === i ? Infinity : 0, ease: 'easeInOut' }}>
                    {m.emoji}
                  </motion.div>
                  <div className="text-[10px] text-white/60 mt-0.5 relative">{m.name}</div>
                  <div className="text-xs font-bold relative" style={{ color: m.color }}>×{m.mult}</div>
                </motion.button>
              ))}
            </div>
            <BetSelector bet={bet} setBet={setBet} balance={balance} />
            <motion.button whileTap={{ scale: 0.95 }} onClick={placeBet}
              disabled={selected < 0 || balance < bet}
              className="w-full py-3 rounded-full font-bold text-sm transition-colors mb-3
                bg-gradient-to-r from-green-600 to-emerald-500 hover:from-green-500 hover:to-emerald-400 text-white
                disabled:opacity-40 disabled:cursor-not-allowed">
              {selected < 0 ? 'Выбери обезьянку ↑' :
                balance < bet ? 'Мало обезьянок' :
                  `ПОСТАВИТЬ на ${RACE_MONKEYS[selected].emoji} — ${bet} 🐵`}
            </motion.button>
          </>
        )}

        {myBet && phase === 'betting' && (
          <div className="text-center mb-3 bg-green-500/10 rounded-xl p-2 border border-green-500/20">
            <p className="text-green-400 text-sm font-bold">
              ✅ {RACE_MONKEYS[myBet.monkey_idx].emoji} {RACE_MONKEYS[myBet.monkey_idx].name} — {myBet.amount} 🐵
            </p>
          </div>
        )}

        <div className="rounded-xl mb-3 overflow-hidden relative"
          style={{ background: 'linear-gradient(180deg, #071a0e 0%, #0f2b18 30%, #1a3520 60%, #12200d 100%)' }}>

          <div className="relative h-9 overflow-hidden">
            <div className="flex justify-around px-1 pt-1">
              {[0, 1, 2, 3, 4, 5, 6].map(i => (
                <motion.span key={i} className="text-xl select-none" style={{ opacity: 0.3 + (i % 3) * 0.08 }}
                  animate={phase === 'racing' ? { rotate: [-6, 6, -6], y: [0, -2, 0] } : {}}
                  transition={{ duration: 2 + i * 0.3, repeat: Infinity, ease: 'easeInOut' }}>
                  🌴
                </motion.span>
              ))}
            </div>
            <div className="absolute bottom-0 left-0 right-0 h-3 bg-gradient-to-b from-transparent to-[#0f2b18]" />
          </div>

          {phase === 'racing' && (
            <div className="absolute inset-0 overflow-hidden pointer-events-none" style={{ zIndex: 30 }}>
              {[0, 1, 2, 3, 4, 5, 6, 7].map(i => (
                <motion.div key={i} className="absolute select-none"
                  style={{ left: `${5 + i * 12}%`, top: -10, fontSize: 10 + (i % 3) * 2 }}
                  animate={{ y: [0, 320], x: [0, i % 2 ? 25 : -25, i % 2 ? -8 : 8], rotate: [0, 180, 360], opacity: [0.7, 0.3, 0] }}
                  transition={{ duration: 3 + i * 0.4, repeat: Infinity, delay: i * 0.55, ease: 'linear' }}>
                  {['🍃', '🍂', '🍌', '🥥', '🍃', '🍂', '🍃', '🍂'][i]}
                </motion.div>
              ))}
            </div>
          )}

          <div className="px-2 pb-1 relative" style={{ zIndex: 10 }}>
            {RACE_MONKEYS.map((m, i) => {
              const isMine = myBet?.monkey_idx === i
              const isWin = phase === 'result' && winner === i
              const pos = positions[i]
              const monkeyPct = 6 + (pos / 100) * 80

              return (
                <div key={i} className={`relative ${i < 5 ? 'mb-0.5' : ''}`} style={{ height: 40 }}>
                  <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" style={{ overflow: 'visible' }}>
                    <line x1="7%" y1="65%" x2="93%" y2="65%"
                      stroke="#3d6a30" strokeWidth="2" strokeDasharray="6,3" opacity="0.4" />
                    {[0, 20, 40, 60, 80, 100].map(p => {
                      const cx = 7 + p * 0.86
                      return <g key={p}>
                        <line x1={`${cx}%`} y1="40%" x2={`${cx}%`} y2="75%" stroke="#2a5420" strokeWidth="1.5" opacity="0.35" />
                        <text x={`${cx}%`} y="35%" textAnchor="middle" fontSize="10" opacity="0.3" className="select-none">🌿</text>
                      </g>
                    })}
                    {isWin && (
                      <circle cx={`${monkeyPct + 4}%`} cy="50%" r="18" fill="none" stroke="#eab308" strokeWidth="1.5" opacity="0.5">
                        <animate attributeName="r" values="14;20;14" dur="1s" repeatCount="indefinite" />
                        <animate attributeName="opacity" values="0.6;0.2;0.6" dur="1s" repeatCount="indefinite" />
                      </circle>
                    )}
                  </svg>

                  <div className="absolute left-0 top-1/2 -translate-y-1/2 flex items-center gap-0.5" style={{ zIndex: 5 }}>
                    <span className="text-[9px] text-white/25 font-medium w-[3ch] text-right">{m.name.slice(0, 3)}</span>
                  </div>

                  <motion.div className="absolute" style={{ zIndex: 20 }}
                    animate={phase === 'racing' ? {
                      left: `${monkeyPct}%`,
                      top: '15%',
                      y: [0, -14, 0],
                      rotate: [0, i % 2 ? 12 : -12, 0],
                      scale: [1, 1.15, 1],
                    } : {
                      left: `${monkeyPct}%`,
                      top: '15%',
                      y: phase === 'betting' ? [0, -4, 0] : 0,
                      rotate: 0,
                      scale: isWin ? [1, 1.3, 1] : 1,
                    }}
                    transition={phase === 'racing' ? {
                      left: { duration: 0.15, ease: 'linear' },
                      y: { duration: 0.28 + i * 0.03, repeat: Infinity, ease: 'easeInOut' },
                      rotate: { duration: 0.28 + i * 0.03, repeat: Infinity, ease: 'easeInOut' },
                      scale: { duration: 0.28 + i * 0.03, repeat: Infinity, ease: 'easeInOut' },
                    } : {
                      left: { duration: 0.3 },
                      y: phase === 'betting' ? { duration: 1.5 + i * 0.15, repeat: Infinity, ease: 'easeInOut' } : { duration: 0.3 },
                      scale: isWin ? { duration: 0.5, repeat: Infinity, ease: 'easeInOut' } : { duration: 0.3 },
                    }}>
                    <span className="select-none" style={{
                      fontSize: isMine ? 22 : 18,
                      filter: isMine
                        ? 'drop-shadow(0 0 6px rgba(74,222,128,0.7))'
                        : isWin
                          ? 'drop-shadow(0 0 8px rgba(234,179,8,0.8))'
                          : 'drop-shadow(0 2px 2px rgba(0,0,0,0.5))',
                    }}>{m.emoji}</span>
                  </motion.div>

                  {phase === 'racing' && pos > 5 && (
                    <motion.div className="absolute pointer-events-none" style={{ zIndex: 15, left: `${monkeyPct - 3}%`, top: '40%' }}
                      animate={{ opacity: [0.5, 0], x: [-4, -16], scale: [0.8, 0.3] }}
                      transition={{ duration: 0.4, repeat: Infinity, ease: 'easeOut' }}>
                      <span style={{ fontSize: 8 }}>💨</span>
                    </motion.div>
                  )}

                  <motion.span className="absolute right-0 top-1/2 -translate-y-1/2 select-none" style={{ zIndex: 5 }}
                    animate={isWin ? { scale: [1, 1.2, 1], rotate: [0, 10, -10, 0] } : {}}
                    transition={{ duration: 0.6, repeat: isWin ? Infinity : 0 }}>
                    <span style={{ fontSize: 14, opacity: isWin ? 1 : 0.35 }}>{isWin ? '🏆' : '🌴'}</span>
                  </motion.span>

                  {isMine && (
                    <motion.div className="absolute inset-0 rounded-lg border pointer-events-none" style={{ zIndex: 1 }}
                      animate={{ borderColor: ['rgba(74,222,128,0.15)', 'rgba(74,222,128,0.35)', 'rgba(74,222,128,0.15)'] }}
                      transition={{ duration: 1.5, repeat: Infinity }} />
                  )}
                </div>
              )
            })}
          </div>

          <div className="relative h-6">
            <div className="absolute inset-0 bg-gradient-to-t from-amber-900/20 to-transparent" />
            <div className="flex justify-between px-3 items-end h-full pb-1.5">
              <span className="text-[8px] text-white/20 flex items-center gap-0.5">🌱 СТАРТ</span>
              <span className="text-[8px] text-white/20 flex items-center gap-0.5">ФИНИШ 🏁</span>
            </div>
          </div>
        </div>

        <div style={{ minHeight: 36 }}>
          <AnimatePresence>
            {lastResult && (
              <motion.div initial={{ opacity: 0, scale: 0.5, y: 15 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.8 }}
                transition={{ type: 'spring', damping: 10 }}
                className="text-center mb-2">
                {lastResult.won ? (
                  <motion.div animate={{ scale: [1, 1.05, 1] }} transition={{ duration: 0.8, repeat: 3 }}>
                    <p className="text-yellow-400 font-black text-xl" style={{ textShadow: '0 0 12px rgba(234,179,8,0.4)' }}>
                      🍌 +{lastResult.amount} 🐵 🍌
                    </p>
                  </motion.div>
                ) : (
                  <p className="text-red-400/80 font-bold text-sm">🍂 −{lastResult.amount} 🐵</p>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {bets.length > 0 && (
          <div className="mb-2">
            <p className="text-white/40 text-[10px] mb-1.5">Ставки игроков:</p>
            <div className="flex flex-col gap-1">
              {bets.map((b, i) => {
                const mk = RACE_MONKEYS[b.monkey_idx]
                const won = phase === 'result' && winner === b.monkey_idx
                const isMe = String(b.user_id) === String(userId)
                return (
                  <div key={i} className={`flex items-center justify-between rounded-lg px-2.5 py-1
                    ${won ? 'bg-green-500/10 border border-green-500/20' : 'bg-white/5'}
                    ${isMe ? 'ring-1 ring-green-400/30' : ''}`}>
                    <span className="text-white/70 text-xs truncate max-w-[100px]">
                      {isMe ? '👤 Ты' : `🐵 ${b.user_name}`}
                    </span>
                    <span className="text-xs flex items-center gap-1">
                      <span>{mk?.emoji}</span>
                      <span className="text-yellow-400">{b.amount}🐵</span>
                      {won && <span className="text-green-400 font-bold">+{Math.floor(b.amount * mk.mult)}</span>}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </motion.div>
  )
}

// ===== stats block =====
function CasinoStatCell({ value, label, color = 'text-white' }) {
  return (
    <div className="bg-white/5 rounded-lg p-2 text-center">
      <div className={`text-lg font-bold ${color}`}>{value}</div>
      <div className="text-[10px] text-white/40">{label}</div>
    </div>
  )
}

function CasinoStatsBlock({ stats }) {
  const [expanded, setExpanded] = useState(false)
  if (!stats) return null
  const s = stats
  const net = (s.won || 0) - (s.bet || 0)
  const totalGames = (s.gamesWon || 0) + (s.gamesLost || 0)
  const winRate = totalGames > 0 ? Math.round((s.gamesWon || 0) / totalGames * 100) : 0

  if (totalGames === 0 && !s.bonus) return null

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
      className="rounded-xl p-4 mb-4 border border-white/5" style={{ background: 'rgba(20,10,40,0.7)' }}>
      <button onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between w-full text-left mb-3">
        <h2 className="text-white font-semibold text-sm">📊 Статистика</h2>
        <span className="text-white/40 text-xs">{expanded ? 'Меньше ▲' : 'Подробнее ▼'}</span>
      </button>

      <div className="grid grid-cols-3 gap-2">
        <CasinoStatCell value={totalGames} label="Игр" />
        <CasinoStatCell value={s.won || 0} label="Выиграно 🐵" color="text-green-400" />
        <CasinoStatCell value={net} label="Нетто 🐵" color={net >= 0 ? 'text-green-400' : 'text-red-400'} />
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="grid grid-cols-3 gap-2 mt-2">
              <CasinoStatCell value={s.bet || 0} label="Поставлено 🐵" color="text-red-400" />
              <CasinoStatCell value={s.bonus || 0} label="Из бонуса 🐵" color="text-purple-400" />
              <CasinoStatCell value={`${winRate}%`} label="Винрейт" color="text-yellow-400" />
            </div>

            {totalGames > 0 && (
              <div className="mt-3 bg-white/5 rounded-lg p-2.5">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-white/40 text-[11px]">Винрейт</span>
                  <span className="text-white text-xs font-bold">{winRate}%</span>
                </div>
                <div className="w-full bg-white/10 rounded-full h-1.5">
                  <div className="bg-green-500 h-1.5 rounded-full transition-all" style={{ width: `${winRate}%` }} />
                </div>
              </div>
            )}

            {s.games && s.games.length > 0 && (
              <div className="mt-3">
                <h3 className="text-white/40 text-[11px] mb-2">По играм</h3>
                <div className="flex flex-col gap-1">
                  {s.games.map(g => {
                    const gNet = (g.won || 0) - (g.bet || 0)
                    const gTotal = (g.gamesWon || 0) + (g.gamesLost || 0)
                    return (
                      <div key={g.game} className="flex items-center justify-between bg-white/5 rounded-lg px-2.5 py-1.5">
                        <span className="text-white/80 text-xs">{GAME_LABELS[g.game] || g.game}</span>
                        <div className="flex items-center gap-2">
                          <span className="text-white/40 text-[10px]">{gTotal} игр</span>
                          <span className="text-green-400 text-[10px]">+{g.won || 0}</span>
                          <span className={`text-[10px] font-semibold ${gNet >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {gNet >= 0 ? '+' : ''}{gNet}
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

// ===== game cards =====
const GAMES = [
  {
    id: 'slots', name: 'Однорукий бандит', emoji: '🎰', available: true,
    gradient: 'from-purple-600 via-pink-500 to-red-500', glow: 'shadow-purple-500/40', desc: 'Крути барабаны!'
  },
  {
    id: 'poker', name: 'Покер', emoji: '🃏', available: true,
    gradient: 'from-emerald-600 via-green-500 to-teal-400', glow: 'shadow-green-500/40', desc: "Техасский холдем", route: '/poker'
  },
  {
    id: 'coinflip', name: 'Монетка', emoji: '🪙', available: true,
    gradient: 'from-yellow-600 via-amber-500 to-orange-400', glow: 'shadow-yellow-500/40', desc: 'Орёл или решка?'
  },
  {
    id: 'roulette', name: 'Рулетка', emoji: '🎡', available: true,
    gradient: 'from-red-700 via-red-500 to-rose-400', glow: 'shadow-red-500/40', desc: 'Поставь на число!'
  },
  {
    id: 'slots5x5', name: 'Слоты 5×5', emoji: '🎲', available: true,
    gradient: 'from-blue-700 via-indigo-500 to-violet-400', glow: 'shadow-blue-500/40', desc: '5 линий выплат'
  },
  {
    id: 'rocket', name: 'Ракетка', emoji: '🚀', available: true,
    gradient: 'from-orange-600 via-red-500 to-rose-600', glow: 'shadow-orange-500/40', desc: 'Забери до краша!'
  },
  {
    id: 'race', name: 'Скачки', emoji: '🏁', available: true,
    gradient: 'from-green-600 via-emerald-500 to-lime-400', glow: 'shadow-green-500/40', desc: 'Поставь на обезьянку!'
  },
]

function GameCard({ game, onClick, index }) {
  return (
    <motion.button
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.15 + index * 0.08, duration: 0.4, ease: 'easeOut' }}
      whileHover={game.available ? { scale: 1.04 } : undefined}
      whileTap={game.available ? { scale: 0.96 } : undefined}
      onClick={onClick} disabled={!game.available}
      className={`relative overflow-hidden rounded-2xl p-4 text-left w-full shadow-lg ${game.glow}
        ${!game.available ? 'opacity-40 grayscale cursor-default' : 'cursor-pointer'}`}>
      <div className={`absolute inset-0 bg-gradient-to-br ${game.gradient} opacity-90`} />
      {game.available && (
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute -top-1/2 -left-1/2 w-[200%] h-[200%]"
            style={{
              background: 'conic-gradient(from 0deg, transparent 0%, transparent 40%, rgba(255,255,255,0.12) 50%, transparent 60%, transparent 100%)',
              animation: 'casino-shimmer 5s linear infinite'
            }} />
        </div>
      )}
      <div className="relative z-10">
        <motion.div className="text-4xl mb-2 drop-shadow-lg inline-block"
          animate={game.available ? { y: [0, -6, 0] } : undefined}
          transition={game.available ? { duration: 2.5, repeat: Infinity, ease: 'easeInOut', delay: index * 0.3 } : undefined}>
          {game.emoji}
        </motion.div>
        <h3 className="text-white font-bold text-base drop-shadow">{game.name}</h3>
        <p className="text-white/70 text-xs mt-0.5">{game.desc}</p>
        {!game.available && (
          <span className="inline-block mt-2 bg-black/30 text-white/80 text-[10px] font-semibold px-2 py-0.5 rounded-full">🔒 Скоро</span>
        )}
      </div>
    </motion.button>
  )
}

// ===== main =====
export default function CasinoPage() {
  const { userId, username, firstName, initData } = useTelegram()
  const userName = username || firstName || 'гость'
  const navigate = useNavigate()
  const { sound, muted, toggleMute } = useCasinoSounds()
  const [view, setView] = useState('hub')
  const [balance, setBalance] = useState(INITIAL_BALANCE)
  const [lastBonusClaim, setLastBonusClaim] = useState(0)
  const [loading, setLoading] = useState(true)
  const [timer, setTimer] = useState(null)
  const [bonusFlash, setBonusFlash] = useState(false)
  const [casinoStats, setCasinoStats] = useState(null)
  const sessionTokenRef = useRef(null)

  const claimable = !lastBonusClaim || Date.now() / 1000 - lastBonusClaim >= 86400

  useEffect(() => {
    if (!userId) { setLoading(false); return }
    fetch('/api/casino/session', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ initData }),
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d) {
          setBalance(d.monkeys)
          setLastBonusClaim(d.lastBonusClaim || 0)
          if (d.token) sessionTokenRef.current = d.token
        }
      })
      .catch(() => { })
      .finally(() => setLoading(false))
  }, [userId, userName])

  const fetchStats = useCallback(() => {
    if (!userId) return
    fetch('/api/casino/stats', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setCasinoStats(d) })
      .catch(() => { })
  }, [userId])

  useEffect(() => { if (view === 'hub') fetchStats() }, [view, fetchStats])

  const changeBalance = useCallback((delta) => {
    setBalance(prev => Math.max(0, prev + delta))
  }, [])

  useEffect(() => {
    if (!claimable && lastBonusClaim) {
      const tick = () => {
        const d = 86400 - (Date.now() / 1000 - lastBonusClaim)
        if (d <= 0) { setTimer(null); return }
        setTimer(`${Math.floor(d / 3600)}ч ${Math.floor((d % 3600) / 60)}м`)
      }
      tick()
      const id = setInterval(tick, 30000)
      return () => clearInterval(id)
    }
    setTimer(null)
  }, [claimable, lastBonusClaim])

  const handleGameResult = useCallback((gameId, bet, winAmount) => {
    fetch('/api/casino/event', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ game: gameId, bet, win: winAmount, token: sessionTokenRef.current || '' }),
    })
      .then(r => {
        if (!r.ok) return fetch('/api/casino/balance', { credentials: 'include' }).then(r2 => r2.ok ? r2.json() : null)
        return r.json()
      })
      .then(d => { if (d?.monkeys != null) setBalance(d.monkeys) })
      .catch(() => { })
  }, [])

  const claimBonus = () => {
    if (!claimable) return
    fetch('/api/casino/bonus', {
      method: 'POST', credentials: 'include',
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d) {
          setBalance(d.monkeys)
          setLastBonusClaim(d.lastBonusClaim || Date.now() / 1000)
        }
      })
      .catch(() => { })
    setBonusFlash(true)
    sound('bonus')
    confetti({ particleCount: 80, spread: 60, origin: { y: 0.45 } })
    setTimeout(() => setBonusFlash(false), 2000)
  }

  const handleGame = (game) => {
    if (game.route) navigate(game.route)
    else setView(game.id)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <span className="text-white/50 text-sm">Загрузка...</span>
      </div>
    )
  }

  const gameProps = { balance, onBalanceChange: changeBalance, onBack: () => setView('hub'), onGameResult: handleGameResult, sound }
  const gameViews = {
    slots: <SlotMachine key="slots" {...gameProps} />,
    coinflip: <CoinFlip key="coinflip" {...gameProps} />,
    roulette: <Roulette key="roulette" {...gameProps} />,
    slots5x5: <Slots5x5 key="slots5x5" {...gameProps} />,
    rocket: <RocketGame key="rocket" {...gameProps} />,
    race: <MonkeyRace key="race" {...gameProps} />,
  }

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="px-4 pt-6 pb-20 flex flex-col items-center">
      <motion.div initial={{ y: -20, opacity: 0 }} animate={{ y: 0, opacity: 1 }} className="w-full max-w-sm mb-5">
        <div className="rounded-xl px-4 py-2.5 flex items-center justify-center gap-2 relative"
          style={{ background: 'linear-gradient(135deg, #2d1b69 0%, #11998e 100%)' }}>
          <span className="text-white/60 text-xs">Баланс:</span>
          <motion.span key={balance} initial={{ scale: 1.15 }} animate={{ scale: 1 }}
            className="text-white text-xl font-bold">{balance} 🐵</motion.span>
          <button onClick={toggleMute}
            className="absolute right-3 text-white/50 hover:text-white transition-colors text-lg"
            title={muted ? 'Включить звук' : 'Выключить звук'}>
            {muted ? '🔇' : '🔊'}
          </button>
        </div>
      </motion.div>

      <AnimatePresence mode="wait">
        {view === 'hub' ? (
          <motion.div key="hub" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            exit={{ opacity: 0, x: -50 }} className="w-full max-w-sm">
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.05 }} className="mb-6">
              {claimable ? (
                <motion.button whileTap={{ scale: 0.95 }} onClick={claimBonus}
                  className="w-full py-3.5 rounded-2xl font-bold text-sm relative overflow-hidden border border-white/10"
                  style={{ background: 'linear-gradient(135deg, #f093fb, #f5576c)' }}>
                  <div className="absolute inset-0 overflow-hidden pointer-events-none">
                    <div className="absolute -top-1/2 -left-1/2 w-[200%] h-[200%]"
                      style={{
                        background: 'conic-gradient(from 0deg, transparent 0%, transparent 30%, rgba(255,255,255,0.2) 50%, transparent 70%, transparent 100%)',
                        animation: 'casino-shimmer 3s linear infinite'
                      }} />
                  </div>
                  <span className="relative z-10 text-white drop-shadow">🎁 Забрать бонус — {DAILY_BONUS} 🐵</span>
                </motion.button>
              ) : (
                <div className="w-full py-3 rounded-2xl text-center text-sm bg-spotify-gray border border-white/5">
                  <span className="text-spotify-text">⏰ Бонус через {timer || '...'}</span>
                </div>
              )}
              <AnimatePresence>
                {bonusFlash && (
                  <motion.p initial={{ opacity: 0, y: -5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                    className="text-center text-spotify-green text-sm font-bold mt-2">+{DAILY_BONUS} 🐵 получено!</motion.p>
                )}
              </AnimatePresence>
            </motion.div>

            <CasinoStatsBlock stats={casinoStats} />

            <motion.h2 initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.1 }}
              className="text-white font-bold text-lg mb-3">Игры</motion.h2>
            <div className="grid grid-cols-2 gap-3">
              {GAMES.map((g, i) => <GameCard key={g.id} game={g} index={i} onClick={() => handleGame(g)} />)}
            </div>
          </motion.div>
        ) : gameViews[view]}
      </AnimatePresence>
    </motion.div>
  )
}
