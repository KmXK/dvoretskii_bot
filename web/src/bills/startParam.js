import WebApp from '@twa-dev/sdk'


export function getBillsStartParam() {
  return WebApp?.initDataUnsafe?.start_param
    || new URLSearchParams(window.location.search).get('startapp')
    || ''
}
