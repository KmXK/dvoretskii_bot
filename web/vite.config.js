import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // HTTPS отключен, так как nginx обеспечивает HTTPS
    // Включайте только если запускаете Vite напрямую без nginx
    https: process.env.VITE_HTTPS === 'true' && fs.existsSync(path.resolve(__dirname, 'key.pem')) && fs.existsSync(path.resolve(__dirname, 'cert.pem')) ? {
      // Используйте самоподписанный сертификат для разработки
      // Создайте его командой: openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365
      key: fs.readFileSync(path.resolve(__dirname, 'key.pem')),
      cert: fs.readFileSync(path.resolve(__dirname, 'cert.pem')),
    } : false,
    host: '0.0.0.0',
    port: 5173,
    'allowedHosts': [
        process.env.DOMAIN
    ]
  },
})
