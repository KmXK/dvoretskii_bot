import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import WebApp from '@twa-dev/sdk'

// Мини-апп всегда стартует на `/` (HomePage), а диплинка от бота приходит как
// `startapp=bill_<id>`. Без этого гейта start_param остаётся неконсьюмнутым —
// пользователь видит хоум, а не счёт. Гейт срабатывает один раз и уводит на
// `/bills`; сама BillsPage уже читает start_param и открывает нужный счёт (в
// нужном виде — распределение или детали).
export default function BillsDeepLinkGate() {
  const navigate = useNavigate()
  const location = useLocation()
  const consumed = useRef(false)

  useEffect(() => {
    if (consumed.current) return
    const raw = WebApp?.initDataUnsafe?.start_param || ''
    if (!/^bill_\d+$/.test(raw)) return
    consumed.current = true
    if (location.pathname !== '/bills') {
      navigate('/bills', { replace: true })
    }
  }, [navigate, location.pathname])

  return null
}
