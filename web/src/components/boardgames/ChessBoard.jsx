import { motion } from 'framer-motion'
import { useEffect, useMemo, useRef, useState } from 'react'

const FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
const RANKS = ['8', '7', '6', '5', '4', '3', '2', '1']
const PIECES = {
  P: '♙', N: '♘', B: '♗', R: '♖', Q: '♕', K: '♔',
  p: '♟', n: '♞', b: '♝', r: '♜', q: '♛', k: '♚',
}

function fenToGrid(fen) {
  const rows = (fen || '').split(' ')[0].split('/')
  const out = []
  for (const row of rows) {
    const cells = []
    for (const ch of row) {
      if (/\d/.test(ch)) for (let i = 0; i < Number(ch); i++) cells.push('.')
      else cells.push(ch)
    }
    out.push(cells)
  }
  return out.length === 8 ? out : Array.from({ length: 8 }, () => Array(8).fill('.'))
}

function posToCoord(r, c) {
  return `${FILES[c]}${8 - r}`
}

function coordToPos(coord) {
  if (!coord || coord.length < 2) return null
  const c = FILES.indexOf(coord[0])
  const r = 8 - Number(coord[1])
  if (r < 0 || r > 7 || c < 0 || c > 7) return null
  return [r, c]
}

function extractEndpoints(lastMove) {
  const mv = String(lastMove?.move || '')
  if (mv.length < 4) return null
  const from = coordToPos(mv.slice(0, 2))
  const to = coordToPos(mv.slice(2, 4))
  if (!from || !to) return null
  return { from, to }
}

function toBoardPos(viewR, viewC, flipped) {
  return flipped ? [7 - viewR, 7 - viewC] : [viewR, viewC]
}

function toViewPos(boardR, boardC, flipped) {
  return flipped ? [7 - boardR, 7 - boardC] : [boardR, boardC]
}

export default function ChessBoard({ state, onMove }) {
  const [selected, setSelected] = useState(null)
  const [promotionDialog, setPromotionDialog] = useState(null)
  const [animMove, setAnimMove] = useState(null)
  const prevGridRef = useRef(null)
  const lastAnimKeyRef = useRef('')
  const animTimerRef = useRef(null)

  const grid = useMemo(() => fenToGrid(state.board?.fen), [state.board?.fen])
  const legalMoves = state.legalMoves || []
  const isFlipped = state.role === 'black'
  const fileLabels = isFlipped ? [...FILES].reverse() : FILES
  const rankLabels = isFlipped ? [...RANKS].reverse() : RANKS

  const targets = useMemo(() => {
    if (!selected) return new Set()
    const from = posToCoord(selected[0], selected[1])
    return new Set(legalMoves.filter(m => m.startsWith(from)).map(m => m.slice(2, 4)))
  }, [selected, legalMoves])

  useEffect(() => {
    const ends = extractEndpoints(state.lastMove)
    if (!ends) {
      prevGridRef.current = grid
      return
    }
    const key = `${ends.from[0]},${ends.from[1]}-${ends.to[0]},${ends.to[1]}-${state.lastMove.move}`
    if (key === lastAnimKeyRef.current) {
      prevGridRef.current = grid
      return
    }
    const prev = prevGridRef.current || grid
    const movingPiece = prev?.[ends.from[0]]?.[ends.from[1]]
    if (!movingPiece || movingPiece === '.') {
      prevGridRef.current = grid
      return
    }
    setAnimMove({ from: ends.from, to: ends.to, piece: movingPiece, key })
    lastAnimKeyRef.current = key
    clearTimeout(animTimerRef.current)
    animTimerRef.current = setTimeout(() => setAnimMove(null), 360)
    prevGridRef.current = grid
  }, [grid, state.lastMove])

  useEffect(() => () => clearTimeout(animTimerRef.current), [])

  const clickCell = (viewR, viewC) => {
    const [r, c] = toBoardPos(viewR, viewC, isFlipped)
    const piece = grid[r][c]
    const mySide = state.role
    if (mySide !== 'white' && mySide !== 'black') return
    if (state.turn !== mySide || state.finished) return

    if (!selected) {
      if (piece !== '.' && (piece === piece.toUpperCase()) === (mySide === 'white')) setSelected([r, c])
      return
    }
    if (selected[0] === r && selected[1] === c) {
      setSelected(null)
      return
    }
    const to = posToCoord(r, c)
    if (!targets.has(to)) {
      if (piece !== '.' && (piece === piece.toUpperCase()) === (mySide === 'white')) setSelected([r, c])
      return
    }
    const from = posToCoord(selected[0], selected[1])
    const prefix = `${from}${to}`
    const promotionMoves = legalMoves.filter(m => m.startsWith(prefix) && m.length === 5)
    if (promotionMoves.length > 0) {
      setPromotionDialog({ from, to, legal: new Set(promotionMoves.map(m => m[4])) })
      return
    }
    onMove({ type: 'move', move: prefix })
    setSelected(null)
  }

  const choosePromotion = (pieceCode) => {
    if (!promotionDialog) return
    const code = String(pieceCode || 'q').toLowerCase()
    if (!promotionDialog.legal.has(code)) return
    onMove({ type: 'move', move: `${promotionDialog.from}${promotionDialog.to}${code}` })
    setPromotionDialog(null)
    setSelected(null)
  }

  const last = extractEndpoints(state.lastMove)
  const lastFrom = last ? `${last.from[0]},${last.from[1]}` : null
  const lastTo = last ? `${last.to[0]},${last.to[1]}` : null

  return (
    <div className="relative bg-zinc-900 rounded-xl overflow-hidden p-2">
      <div className="grid grid-cols-[18px_1fr] grid-rows-[1fr_18px] gap-1">
        <div className="grid grid-rows-8">
          {rankLabels.map(rank => (
            <div key={rank} className="h-full flex items-center justify-center text-[10px] text-zinc-500 select-none">
              {rank}
            </div>
          ))}
        </div>
        <div className="relative">
          <div className="grid grid-cols-8">
            {Array.from({ length: 64 }, (_, i) => {
              const viewR = Math.floor(i / 8)
              const viewC = i % 8
              const [r, c] = toBoardPos(viewR, viewC, isFlipped)
              const key = `${r},${c}`
              const piece = grid[r][c]
              const dark = (r + c) % 2 === 1
              const isSel = selected && selected[0] === r && selected[1] === c
              const isTarget = targets.has(posToCoord(r, c))
              const hideAtTo = animMove && animMove.to[0] === r && animMove.to[1] === c
              const cellShadow = [
                isSel ? 'inset 0 0 0 2px rgba(250,204,21,0.95)' : '',
                isTarget ? 'inset 0 0 0 2px rgba(74,222,128,0.95)' : '',
                key === lastFrom ? 'inset 0 0 0 2px rgba(251,146,60,0.95)' : '',
                key === lastTo ? 'inset 0 0 0 2px rgba(34,211,238,0.95)' : '',
              ].filter(Boolean).join(', ')
              return (
                <button
                  key={key}
                  onClick={() => clickCell(viewR, viewC)}
                  className={`aspect-square rounded text-2xl flex items-center justify-center transition-colors ${
                    dark ? 'bg-zinc-700' : 'bg-zinc-200'
                  }`}
                  style={cellShadow ? { boxShadow: cellShadow } : undefined}
                >
                  {!hideAtTo && (
                    <motion.span
                      key={`${piece}-${key}-${key === lastTo ? 'last' : 'normal'}`}
                      initial={key === lastTo ? { scale: 0.7, y: -12, opacity: 0.15, rotate: -8 } : { scale: 1, opacity: 1 }}
                      animate={key === lastTo ? { scale: [0.92, 1.2, 1], y: [0, -4, 0], opacity: 1, rotate: [0, 6, 0] } : { scale: 1, opacity: 1, rotate: 0 }}
                      transition={{ duration: 0.36 }}
                      style={{
                        color: piece !== '.' && piece === piece.toUpperCase() ? '#f8fafc' : '#111827',
                        textShadow: piece !== '.' && piece === piece.toUpperCase()
                          ? '0 1px 2px rgba(0,0,0,0.7), 0 0 2px rgba(0,0,0,0.9)'
                          : '0 1px 2px rgba(255,255,255,0.25)',
                        WebkitTextStroke: piece !== '.' && piece === piece.toUpperCase() ? '0.6px rgba(17,24,39,0.9)' : '0',
                        filter: key === lastTo ? 'drop-shadow(0 0 6px rgba(34,211,238,0.55))' : 'none',
                      }}
                    >
                      {PIECES[piece] || ''}
                    </motion.span>
                  )}
                </button>
              )
            })}
          </div>
          {animMove && (
            (() => {
              const [fromViewR, fromViewC] = toViewPos(animMove.from[0], animMove.from[1], isFlipped)
              const [toViewR, toViewC] = toViewPos(animMove.to[0], animMove.to[1], isFlipped)
              return (
                <motion.div
                  key={animMove.key}
                  className="absolute pointer-events-none flex items-center justify-center text-2xl"
                  style={{
                    left: `${fromViewC * 12.5}%`,
                    top: `${fromViewR * 12.5}%`,
                    width: '12.5%',
                    height: '12.5%',
                    color: animMove.piece === animMove.piece.toUpperCase() ? '#f8fafc' : '#111827',
                    textShadow: animMove.piece === animMove.piece.toUpperCase()
                      ? '0 2px 4px rgba(0,0,0,0.75), 0 0 2px rgba(0,0,0,0.95)'
                      : '0 2px 4px rgba(255,255,255,0.25)',
                    WebkitTextStroke: animMove.piece === animMove.piece.toUpperCase() ? '0.6px rgba(17,24,39,0.9)' : '0',
                    zIndex: 30,
                  }}
                  initial={{ left: `${fromViewC * 12.5}%`, top: `${fromViewR * 12.5}%`, scale: 1 }}
                  animate={{ left: `${toViewC * 12.5}%`, top: `${toViewR * 12.5}%`, scale: [1, 1.08, 1] }}
                  transition={{ duration: 0.32, ease: 'easeInOut' }}
                >
                  {PIECES[animMove.piece] || ''}
                </motion.div>
              )
            })()
          )}
          {promotionDialog && (
            <div className="absolute inset-0 bg-black/55 flex items-center justify-center z-40">
              <div className="bg-zinc-900 rounded-xl p-3 w-56">
                <p className="text-zinc-200 text-xs mb-2 text-center">Выберите фигуру превращения</p>
                <div className="grid grid-cols-4 gap-2">
                  {['q', 'r', 'b', 'n'].map(code => {
                    const enabled = promotionDialog.legal.has(code)
                    return (
                      <button
                        key={code}
                        onClick={() => choosePromotion(code)}
                        disabled={!enabled}
                        className={`rounded py-2 text-xl ${enabled ? 'bg-zinc-800 hover:bg-zinc-700 text-white' : 'bg-zinc-800/40 text-zinc-500'}`}
                      >
                        {PIECES[state.role === 'white' ? code.toUpperCase() : code] || code.toUpperCase()}
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
        <div />
        <div className="grid grid-cols-8">
          {fileLabels.map(file => (
            <div key={file} className="h-full flex items-center justify-center text-[10px] text-zinc-500 select-none">
              {file}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
