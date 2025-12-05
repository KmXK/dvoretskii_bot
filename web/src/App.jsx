import { useState, useRef, useEffect } from 'react'
import confetti from 'canvas-confetti'
import './App.css'

function App() {
  const [rotation, setRotation] = useState({ x: -20, y: 30 })
  const [isDragging, setIsDragging] = useState(false)
  const lastPos = useRef({ x: 0, y: 0 })

  useEffect(() => {
    if (!isDragging) return

    const handleMouseMove = (e) => {
      const deltaX = e.clientX - lastPos.current.x
      const deltaY = e.clientY - lastPos.current.y
      setRotation(prev => ({
        x: prev.x - deltaY * 0.5,
        y: prev.y + deltaX * 0.5
      }))
      lastPos.current = { x: e.clientX, y: e.clientY }
    }

    const handleTouchMove = (e) => {
      const touch = e.touches[0]
      const deltaX = touch.clientX - lastPos.current.x
      const deltaY = touch.clientY - lastPos.current.y
      setRotation(prev => ({
        x: prev.x - deltaY * 0.5,
        y: prev.y + deltaX * 0.5
      }))
      lastPos.current = { x: touch.clientX, y: touch.clientY }
    }

    const handleEnd = () => setIsDragging(false)

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleEnd)
    window.addEventListener('touchmove', handleTouchMove)
    window.addEventListener('touchend', handleEnd)

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleEnd)
      window.removeEventListener('touchmove', handleTouchMove)
      window.removeEventListener('touchend', handleEnd)
    }
  }, [isDragging])

  const handleMouseDown = (e) => {
    setIsDragging(true)
    lastPos.current = { x: e.clientX, y: e.clientY }
  }

  const handleTouchStart = (e) => {
    const touch = e.touches[0]
    setIsDragging(true)
    lastPos.current = { x: touch.clientX, y: touch.clientY }
  }

  const handleClick = () => {
    confetti({ particleCount: 150, spread: 70, origin: { y: 0.6 } })
  }

  return (
    <div className="scene">
      <div
        className="cube"
        onMouseDown={handleMouseDown}
        onTouchStart={handleTouchStart}
        style={{ transform: `rotateX(${rotation.x}deg) rotateY(${rotation.y}deg)` }}
      >
        <div className="face front">Front</div>
        <div className="face back">Back</div>
        <div className="face right">Right</div>
        <div className="face left">Left</div>
        <div className="face top">Top</div>
        <div className="face bottom">Bottom</div>
      </div>
      <button className="confetti-btn" onClick={handleClick}>🎉 Confetti</button>
    </div>
  )
}

export default App
