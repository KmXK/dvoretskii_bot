import { motion } from 'framer-motion'
import { useEffect, useMemo, useRef, useState } from 'react'

const PIECES = { w: '⛀', W: '⛁', b: '⛂', B: '⛃' }
const FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
const RANKS = ['8', '7', '6', '5', '4', '3', '2', '1']

function pieceSide(piece) {
  if (piece === 'w' || piece === 'W') return 'white'
  if (piece === 'b' || piece === 'B') return 'black'
  return null
}

function toBoardPos(viewR, viewC, flipped) {
  return flipped ? [7 - viewR, 7 - viewC] : [viewR, viewC]
}

function toViewPos(boardR, boardC, flipped) {
  return flipped ? [7 - boardR, 7 - boardC] : [boardR, boardC]
}

export default function CheckersBoard({ state, onMove }) {
  const [selected, setSelected] = useState(null)
  const [animMove, setAnimMove] = useState(null)
  const prevGridRef = useRef(null)
  const lastAnimKeyRef = useRef('')
  const animTimerRef = useRef(null)

  const grid = state.board?.grid || Array.from({ length: 8 }, () => Array(8).fill('.'))
  const legalMoves = state.legalMoves || []
  const forcedFrom = state.board?.forcedFrom || null
  const isFlipped = state.role === 'black'
  const fileLabels = isFlipped ? [...FILES].reverse() : FILES
  const rankLabels = isFlipped ? [...RANKS].reverse() : RANKS

  const targets = useMemo(() => {
    if (!selected) return new Set()
    return new Set(legalMoves.filter(m => m.from[0] === selected[0] && m.from[1] === selected[1]).map(m => `${m.to[0]},${m.to[1]}`))
  }, [selected, legalMoves])
  const movableFrom = useMemo(
    () => new Set(legalMoves.map(m => `${m.from[0]},${m.from[1]}`)),
    [legalMoves],
  )

  useEffect(() => {
    if (forcedFrom && Array.isArray(forcedFrom) && forcedFrom.length === 2) {
      setSelected([forcedFrom[0], forcedFrom[1]])
    }
  }, [forcedFrom, state.lastMove?.to?.[0], state.lastMove?.to?.[1]])

  useEffect(() => {
    const from = state.lastMove?.from
    const to = state.lastMove?.to
    if (!Array.isArray(from) || !Array.isArray(to)) {
      prevGridRef.current = grid
      return
    }
    const key = `${from[0]},${from[1]}-${to[0]},${to[1]}-${JSON.stringify(state.lastMove)}`
    if (key === lastAnimKeyRef.current) {
      prevGridRef.current = grid
      return
    }
    const prev = prevGridRef.current || grid
    const movingPiece = prev?.[from[0]]?.[from[1]]
    if (!movingPiece || movingPiece === '.') {
      prevGridRef.current = grid
      return
    }
    setAnimMove({ from, to, piece: movingPiece, key })
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
      if (pieceSide(piece) === mySide) {
        if (forcedFrom && (forcedFrom[0] !== r || forcedFrom[1] !== c)) return
        if (!movableFrom.has(`${r},${c}`)) return
        setSelected([r, c])
      }
      return
    }
    if (selected[0] === r && selected[1] === c) {
      if (forcedFrom) return
      setSelected(null)
      return
    }
    const move = legalMoves.find(m => m.from[0] === selected[0] && m.from[1] === selected[1] && m.to[0] === r && m.to[1] === c)
    if (!move) {
      if (pieceSide(piece) === mySide && (!forcedFrom || (forcedFrom[0] === r && forcedFrom[1] === c))) {
        if (!movableFrom.has(`${r},${c}`)) return
        setSelected([r, c])
      }
      return
    }
    onMove({ type: 'move', from: [selected[0], selected[1]], to: [r, c] })
    setSelected(null)
  }

  const lastFrom = state.lastMove?.from ? `${state.lastMove.from[0]},${state.lastMove.from[1]}` : null
  const lastTo = state.lastMove?.to ? `${state.lastMove.to[0]},${state.lastMove.to[1]}` : null

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
              const isTarget = targets.has(key)
              const isMovable = movableFrom.has(key)
              const hideAtTo = animMove && animMove.to[0] === r && animMove.to[1] === c
              const cellShadow = [
                isSel ? 'inset 0 0 0 2px rgba(250,204,21,0.95)' : '',
                isTarget ? 'inset 0 0 0 2px rgba(74,222,128,0.95)' : '',
                isMovable && !isSel && !isTarget ? 'inset 0 0 0 1px rgba(250,204,21,0.45)' : '',
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
                        color: pieceSide(piece) === 'white' ? '#f8fafc' : pieceSide(piece) === 'black' ? '#111827' : '#e5e7eb',
                        textShadow: '0 1px 2px rgba(0,0,0,0.45)',
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
                    color: pieceSide(animMove.piece) === 'white' ? '#f8fafc' : '#111827',
                    textShadow: '0 2px 4px rgba(0,0,0,0.55)',
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
