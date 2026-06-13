import mascotStrip from '../assets/mascot_idle_strip.png'

const FRAMES = 6
const FRAME_W = 128
const FRAME_H = 124

export default function MascotLoader({ scale = 1, label, className = '' }) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 ${className}`}>
      <div
        className="relative grid place-items-center"
        style={{ width: FRAME_W * scale, height: FRAME_H * scale }}
      >
        <div
          className="absolute rounded-full"
          style={{
            width: 90 * scale,
            height: 90 * scale,
            background: 'radial-gradient(circle, var(--color-gold-soft), transparent 70%)',
          }}
        />
        <div
          style={{
            width: FRAME_W,
            height: FRAME_H,
            transform: `scale(${scale})`,
            backgroundImage: `url(${mascotStrip})`,
            backgroundRepeat: 'no-repeat',
            imageRendering: 'auto',
            '--mascot-end': `-${FRAME_W * FRAMES}px`,
            animation: 'mascot-idle 0.9s steps(6) infinite',
          }}
        />
      </div>
      {label && <p className="text-spotify-text text-sm">{label}</p>}
    </div>
  )
}
