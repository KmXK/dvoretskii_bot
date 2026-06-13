import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import WebApp from '@twa-dev/sdk'
import './index.css'
import App from './App.jsx'

// Telegram Mini App init: open full-height and stop the swipe-to-close
// gesture from dragging the app down while the user scrolls content.
if (WebApp?.platform && WebApp.platform !== 'unknown') {
  try { WebApp.ready() } catch { /* ignore */ }
  try { WebApp.expand() } catch { /* ignore */ }
  try { WebApp.disableVerticalSwipes?.() } catch { /* ignore */ }
  try { WebApp.setBackgroundColor?.('#0C0D11') } catch { /* ignore */ }
  try { WebApp.setHeaderColor?.('#0C0D11') } catch { /* ignore */ }
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
