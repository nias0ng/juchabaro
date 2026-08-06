import { onMounted, onUnmounted } from 'vue'

/** 보이는 브라우저 탭에서만 주기적으로 갱신하고, 탭/창으로 돌아오면 즉시 한 번 갱신한다. */
export function useAutoRefresh(refresh: () => void | Promise<void>, intervalMs: number) {
  let intervalId: number | null = null
  let running = false

  const run = async () => {
    if (running || document.visibilityState !== 'visible') return
    running = true
    try {
      await refresh()
    } finally {
      running = false
    }
  }

  const handleVisibilityChange = () => {
    if (document.visibilityState === 'visible') void run()
  }

  onMounted(() => {
    window.addEventListener('focus', run)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    intervalId = window.setInterval(() => void run(), intervalMs)
  })

  onUnmounted(() => {
    window.removeEventListener('focus', run)
    document.removeEventListener('visibilitychange', handleVisibilityChange)
    if (intervalId !== null) window.clearInterval(intervalId)
  })

  return { refreshNow: run }
}
