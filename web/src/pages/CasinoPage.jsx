import { useState, useRef, useEffect, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import confetti from 'canvas-confetti'
import * as Dialog from '@radix-ui/react-dialog'

const SYMBOLS = ['🍒', '🍋', '💎', '7️⃣', '🔔', '⭐']
const CELL_SIZE = 80
const VISIBLE_CELLS = 1
const EXTRA_SPINS = 4

function getRandomSymbol() {
  return SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)]
}

function buildStrip(finalSymbol) {
  const cells = []
  for (let round = 0; round < EXTRA_SPINS; round++) {
    for (const s of SYMBOLS) cells.push(s)
  }
  cells.push(finalSymbol)
  return cells
}

function SlotReel({ symbol, spinning, reelIndex }) {
  const strip = useMemo(() => buildStrip(symbol), [symbol, spinning])
  const totalHeight = strip.length * CELL_SIZE
  const finalOffset = -(totalHeight - CELL_SIZE)
  const duration = 1.6 + reelIndex * 0.4

  return (
    <div
      className="w-20 h-20 bg-spotify-black rounded-xl overflow-hidden border border-white/10 relative"
      style={{ height: CELL_SIZE }}
    >
      <motion.div
        className="flex flex-col"
        initial={{ y: 0 }}
        animate={spinning ? { y: finalOffset } : { y: 0 }}
        transition={spinning
          ? { duration, ease: [0.2, 0.8, 0.3, 1] }
          : { duration: 0 }
        }
      >
        {(spinning ? strip : [symbol]).map((s, i) => (
          <div
            key={i}
            className="flex items-center justify-center shrink-0 text-4xl"
            style={{ width: CELL_SIZE, height: CELL_SIZE }}
          >
            {s}
          </div>
        ))}
      </motion.div>
    </div>
  )
}

export default function CasinoPage() {
  const [reels, setReels] = useState(['🍒', '💎', '🍒'])
  const [spinning, setSpinning] = useState(false)
  const [balance, setBalance] = useState(1000)
  const [lastWin, setLastWin] = useState(null)
  const [showDialog, setShowDialog] = useState(false)

  const spin = () => {
    if (spinning || balance < 10) return
    setBalance(b => b - 10)
    setLastWin(null)

    const results = [getRandomSymbol(), getRandomSymbol(), getRandomSymbol()]
    setReels(results)
    setSpinning(true)

    const lastReelDuration = 1.6 + 2 * 0.4
    setTimeout(() => {
      setSpinning(false)

      if (results[0] === results[1] && results[1] === results[2]) {
        const win = results[0] === '7️⃣' ? 500 : results[0] === '💎' ? 200 : 100
        setBalance(b => b + win)
        setLastWin(win)
        confetti({ particleCount: 150, spread: 70, origin: { y: 0.6 } })
      }
    }, lastReelDuration * 1000 + 100)
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6 flex flex-col items-center"
    >
      <h1 className="text-2xl font-bold text-white mb-2">Casino</h1>
      <p className="text-spotify-text text-sm mb-8">Try your luck</p>

      <div className="bg-spotify-dark rounded-2xl p-6 w-full max-w-sm">
        <div className="flex items-center justify-between mb-6">
          <div>
            <span className="text-spotify-text text-xs uppercase tracking-wider">Balance</span>
            <motion.p
              key={balance}
              initial={{ scale: 1.2 }}
              animate={{ scale: 1 }}
              className="text-white text-2xl font-bold"
            >
              {balance} 🪙
            </motion.p>
          </div>
          <Dialog.Root open={showDialog} onOpenChange={setShowDialog}>
            <Dialog.Trigger className="text-spotify-text text-xs underline hover:text-white transition-colors">
              Rules
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Overlay className="fixed inset-0 bg-black/70 z-50" />
              <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
                bg-spotify-gray rounded-2xl p-6 w-[90vw] max-w-sm z-50">
                <Dialog.Title className="text-white text-lg font-bold mb-3">Slot Rules</Dialog.Title>
                <div className="space-y-2 text-spotify-text text-sm">
                  <p>Spin costs: <span className="text-white font-semibold">10 🪙</span></p>
                  <p>3x match: <span className="text-white font-semibold">100 🪙</span></p>
                  <p>3x 💎: <span className="text-white font-semibold">200 🪙</span></p>
                  <p>3x 7️⃣: <span className="text-white font-semibold">500 🪙</span></p>
                </div>
                <Dialog.Close className="mt-4 w-full bg-spotify-green hover:bg-spotify-green-hover
                  text-black font-semibold py-2.5 rounded-full transition-colors text-sm">
                  Got it
                </Dialog.Close>
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
        </div>

        <div className="flex justify-center gap-3 mb-6">
          {reels.map((symbol, i) => (
            <SlotReel
              key={i}
              symbol={symbol}
              spinning={spinning}
              reelIndex={i}
            />
          ))}
        </div>

        <AnimatePresence>
          {lastWin && (
            <motion.p
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="text-center text-spotify-green font-bold text-lg mb-4"
            >
              +{lastWin} 🪙
            </motion.p>
          )}
        </AnimatePresence>

        <motion.button
          whileTap={{ scale: 0.95 }}
          onClick={spin}
          disabled={spinning || balance < 10}
          className="w-full py-3 rounded-full font-bold text-sm transition-colors
            bg-spotify-green hover:bg-spotify-green-hover text-black
            disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {spinning ? 'Spinning...' : balance < 10 ? 'Not enough coins' : 'SPIN — 10 🪙'}
        </motion.button>
      </div>

      <div className="mt-6 bg-spotify-dark rounded-xl p-4 w-full max-w-sm">
        <h2 className="text-white font-semibold text-sm mb-3">Payouts</h2>
        <div className="grid grid-cols-3 gap-2 text-center">
          {SYMBOLS.map(s => (
            <div key={s} className="bg-spotify-gray rounded-lg py-2">
              <span className="text-2xl">{s}</span>
              <p className="text-spotify-text text-xs mt-1">
                {s === '7️⃣' ? '500' : s === '💎' ? '200' : '100'}
              </p>
            </div>
          ))}
        </div>
      </div>
    </motion.div>
  )
}
