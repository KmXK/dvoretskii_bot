import { useNavigate } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
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
      <ChevronLeft size={20} />
      Назад
    </button>
  )
}
