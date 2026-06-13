import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import WebApp from '@twa-dev/sdk'

export function useTelegramBackButton() {
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    const btn = WebApp?.BackButton
    if (!btn) return

    const handleBack = () => navigate(-1)

    if (location.pathname !== '/') {
      btn.show()
      btn.onClick(handleBack)
    } else {
      btn.hide()
    }

    return () => btn.offClick(handleBack)
  }, [location.pathname, navigate])
}
