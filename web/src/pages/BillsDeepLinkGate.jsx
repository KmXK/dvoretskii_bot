import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { getBillsStartParam } from '../bills/startParam'

// Мини-апп всегда стартует на `/` (HomePage), а диплинка от бота приходит через
// `startapp`. Без этого гейта start_param остаётся неконсьюмнутым —
// пользователь видит хоум, а не счёт. Гейт срабатывает один раз и уводит на
// `/bills`; сама BillsPage уже читает start_param и открывает нужный экран.
const BILLS_START_PARAM = /^(?:bill_\d+|bills_(?:pay|details))$/


export default function BillsDeepLinkGate() {
  const navigate = useNavigate()
  const location = useLocation()
  const consumed = useRef(false)

  useEffect(() => {
    if (consumed.current) return
    const raw = getBillsStartParam()
    if (!BILLS_START_PARAM.test(raw)) return
    consumed.current = true
    if (location.pathname !== '/bills') {
      navigate('/bills', { replace: true })
    }
  }, [navigate, location.pathname])

  return null
}
