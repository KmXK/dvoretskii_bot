import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'sidebar.collapsed'

function readCollapsed() {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(STORAGE_KEY) === '1'
}

export function useSidebar() {
  const [open, setOpen] = useState(() => !readCollapsed())
  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, open ? '0' : '1')
    }
  }, [open])
  const toggle = useCallback(() => setOpen((v) => !v), [])
  return [open, toggle, setOpen]
}
