import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/useAuth'

export default function BackButton({ force = false }) {
  const navigate = useNavigate()
  const { mode } = useAuth()

  if (mode !== 'miniapp' && !force) return null

  return (
    <button
      onClick={() => navigate(-1)}
      className="flex items-center gap-1.5 text-spotify-text text-sm hover:text-white transition-colors mb-4"
    >
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M15 18l-6-6 6-6" />
      </svg>
      Назад
    </button>
  )
}
