import { motion } from 'framer-motion'

function Ring({ color, dim, dir, dur, thickness }) {
  return (
    <motion.span
      className="absolute rounded-full"
      style={{
        width: dim,
        height: dim,
        background: `conic-gradient(from 0deg, transparent 0deg, ${color} 300deg, ${color} 360deg)`,
        WebkitMask: `radial-gradient(farthest-side, transparent calc(100% - ${thickness}px), #000 calc(100% - ${thickness}px))`,
        mask: `radial-gradient(farthest-side, transparent calc(100% - ${thickness}px), #000 calc(100% - ${thickness}px))`,
        filter: `drop-shadow(0 0 5px ${color})`,
      }}
      animate={{ rotate: dir * 360 }}
      transition={{ duration: dur, repeat: Infinity, ease: 'linear' }}
    />
  )
}

export default function Loader({ scale = 1, label, className = '' }) {
  const size = 56 * scale
  return (
    <div className={`flex flex-col items-center justify-center gap-3 ${className}`}>
      <div className="relative grid place-items-center" style={{ width: size, height: size }}>
        <div
          className="absolute rounded-full"
          style={{
            width: size * 1.6,
            height: size * 1.6,
            background: 'radial-gradient(circle, var(--color-gold-soft), transparent 70%)',
          }}
        />
        <Ring color="var(--color-gold)" dim={size} dir={1} dur={0.9} thickness={Math.max(3, size * 0.09)} />
        <Ring color="var(--color-indigo)" dim={size * 0.6} dir={-1} dur={0.7} thickness={Math.max(2.5, size * 0.08)} />
        <motion.span
          className="absolute rounded-full bg-gold"
          style={{ width: size * 0.11, height: size * 0.11, filter: 'drop-shadow(0 0 4px var(--color-gold))' }}
          animate={{ scale: [1, 1.7, 1], opacity: [0.6, 1, 0.6] }}
          transition={{ duration: 1.1, repeat: Infinity, ease: 'easeInOut' }}
        />
      </div>
      {label && <p className="text-spotify-text text-sm">{label}</p>}
    </div>
  )
}
