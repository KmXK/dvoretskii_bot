import { motion } from 'framer-motion'
import mascot from '../assets/mascot_idle.png'

export default function MascotLoader({ scale = 1, label, className = '' }) {
  const size = 112 * scale
  return (
    <div className={`flex flex-col items-center justify-center gap-3 ${className}`}>
      <div
        className="relative grid place-items-center"
        style={{ width: size * 1.5, height: size * 1.3 }}
      >
        <div
          className="absolute rounded-full"
          style={{
            width: size,
            height: size,
            background: 'radial-gradient(circle, var(--color-gold-soft), transparent 70%)',
          }}
        />
        <motion.div
          className="absolute rounded-[50%] bg-black/40 blur-[3px]"
          style={{ width: size * 0.46, height: size * 0.07, bottom: size * 0.05 }}
          animate={{ scaleX: [1, 0.82, 1], opacity: [0.45, 0.3, 0.45] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
        />
        <motion.img
          src={mascot}
          alt=""
          draggable="false"
          style={{ height: size }}
          className="relative drop-shadow-[0_6px_10px_rgba(0,0,0,0.5)] select-none"
          animate={{ y: [0, -size * 0.07, 0] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
        />
      </div>
      {label && <p className="text-spotify-text text-sm">{label}</p>}
    </div>
  )
}
