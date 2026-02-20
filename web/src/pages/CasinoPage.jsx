import confetti from 'canvas-confetti'
import { AnimatePresence, motion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTelegram } from '../context/TelegramContext'
import useCasinoSounds from '../hooks/useCasinoSounds'

const DAILY_BONUS = 50
const INITIAL_BALANCE = 100

const GAME_IDS = ['slots', 'coinflip', 'roulette', 'slots5x5']
const GAME_LABELS = { slots: '🎰 Бандит', coinflip: '🪙 Монетка', roulette: '🎡 Рулетка', slots5x5: '🎲 Слоты 5×5' }

function weighted(symbols, weights) {
  const total = weights.reduce((a, b) => a + b, 0)
  let r = Math.random() * total
  for (let i = 0; i < symbols.length; i++) { r -= weights[i]; if (r <= 0) return symbols[i] }
  return symbols[symbols.length - 1]
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
        <AnimatePresence>
          {lastWin !== null && (
            <motion.p initial={{ opacity: 0, y: 10, scale: 0.8 }} animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0 }}
              className={`text-center font-bold text-lg mb-4 ${lastWin >= 100 ? 'text-yellow-400' : 'text-spotify-green'}`}>
              +{lastWin} 🐵
            </motion.p>
          )}
        </AnimatePresence>
        <motion.button whileTap={{ scale: 0.95 }} onClick={spin}
          disabled={spinning || balance < SPIN_COST}
          className="w-full py-3 rounded-full font-bold text-sm transition-colors
            bg-gradient-to-r from-yellow-500 to-orange-500 hover:from-yellow-400 hover:to-orange-400 text-black
            disabled:opacity-40 disabled:cursor-not-allowed">
          {spinning ? 'Кручу...' : balance < SPIN_COST ? 'Мало обезьянок' : `КРУТИТЬ — ${SPIN_COST} 🐵`}
        </motion.button>
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

    const isHeads = Math.random() < 0.5
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

        <AnimatePresence>
          {won !== null && !flipping && (
            <motion.p initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className={`text-center font-bold text-lg mb-4 ${won > 0 ? 'text-yellow-400' : 'text-red-400'}`}>
              {won > 0 ? `+${won} 🐵` : `Не повезло!`}
            </motion.p>
          )}
        </AnimatePresence>

        <div className="grid grid-cols-2 gap-3">
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

    const winNum = Math.floor(Math.random() * 37)
    const targetIdx = WHEEL_ORDER.indexOf(winNum)
    const targetAngle = 360 - (targetIdx * SECTOR_DEG + SECTOR_DEG / 2)
    const spins = (5 + Math.floor(Math.random() * 3)) * 360
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

        <motion.button whileTap={{ scale: 0.95 }} onClick={spin}
          disabled={spinning || balance < bet || !betChoice}
          className="w-full py-3 rounded-full font-bold text-sm transition-colors
            bg-gradient-to-r from-red-600 to-rose-500 hover:from-red-500 hover:to-rose-400 text-white
            disabled:opacity-40 disabled:cursor-not-allowed">
          {spinning ? 'Крутится...' : !betChoice ? 'Выбери ставку' : `КРУТИТЬ — ${bet} 🐵`}
        </motion.button>
      </div>
    </motion.div>
  )
}

// ===== slots 5x5 =====
const S5 = ['🍇', '🍊', '🍉', '🔔', '⭐', '💎', '🐵']
const W5 = [32, 26, 20, 11, 6, 3, 2]
const PAY5 = {
  '🍇': [3, 10, 35],
  '🍊': [5, 18, 55],
  '🍉': [8, 25, 80],
  '🔔': [12, 35, 120],
  '⭐': [20, 55, 200],
  '💎': [35, 100, 350],
  '🐵': [15, 40, 170],
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
        <p className="text-center text-white/40 text-xs mb-1">↔ ↕ ↗ ↘ кластеры · 🐵 = wild</p>
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

        <AnimatePresence>
          {lastWin !== null && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className="mb-3">
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

        <motion.button whileTap={{ scale: 0.95 }} onClick={spin}
          disabled={spinning || balance < SPIN5_COST}
          className="w-full py-3 rounded-full font-bold text-sm transition-colors
            bg-gradient-to-r from-blue-600 to-indigo-500 hover:from-blue-500 hover:to-indigo-400 text-white
            disabled:opacity-40 disabled:cursor-not-allowed">
          {spinning ? 'Кручу...' : balance < SPIN5_COST ? 'Мало обезьянок' : `КРУТИТЬ — ${SPIN5_COST} 🐵`}
        </motion.button>
      </div>

      <div className="mt-4 rounded-xl p-4 border border-white/5" style={{ background: 'rgba(10,22,40,0.8)' }}>
        <h3 className="text-white font-semibold text-sm mb-2">Выплаты (3 / 4 / 5 совпадений)</h3>
        <div className="flex flex-col gap-1">
          {S5.map(s => (
            <div key={s} className="flex items-center justify-between bg-white/5 rounded-lg px-3 py-1.5">
              <span className="text-lg">{s} {s === '🐵' && <span className="text-[10px] text-yellow-400">wild</span>}</span>
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
    gradient: 'from-emerald-600 via-green-500 to-teal-400', glow: 'shadow-green-500/40', desc: "Texas Hold'em", route: '/poker'
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
  const { userId, username, firstName } = useTelegram()
  const userName = username || firstName || 'guest'
  const navigate = useNavigate()
  const { sound, muted, toggleMute } = useCasinoSounds()
  const [view, setView] = useState('hub')
  const [balance, setBalance] = useState(INITIAL_BALANCE)
  const [lastBonusClaim, setLastBonusClaim] = useState(0)
  const [loading, setLoading] = useState(true)
  const [timer, setTimer] = useState(null)
  const [bonusFlash, setBonusFlash] = useState(false)
  const [casinoStats, setCasinoStats] = useState(null)

  const claimable = !lastBonusClaim || Date.now() / 1000 - lastBonusClaim >= 86400

  useEffect(() => {
    if (!userId) { setLoading(false); return }
    fetch(`/api/casino/balance/${userId}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d) {
          setBalance(d.monkeys)
          setLastBonusClaim(d.lastBonusClaim || 0)
        }
      })
      .catch(() => { })
      .finally(() => setLoading(false))
  }, [userId])

  const fetchStats = useCallback(() => {
    if (!userId) return
    fetch(`/api/casino/stats/${userId}`)
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
      body: JSON.stringify({ userId, userName, game: gameId, bet, win: winAmount }),
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.monkeys != null) setBalance(d.monkeys) })
      .catch(() => { })
  }, [userId, userName])

  const claimBonus = () => {
    if (!claimable) return
    fetch('/api/casino/bonus', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userId, userName }),
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
