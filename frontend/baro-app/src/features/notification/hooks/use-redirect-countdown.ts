import { useEffect, useState } from 'react';

const DEFAULT_START_SECONDS = 10;

// startSeconds에서 1초 간격으로 0까지 감소시키고, 0에 도달하면 더 이상 타이머를 걸지 않는다.
export function useRedirectCountdown(startSeconds: number = DEFAULT_START_SECONDS): number {
  const [secondsLeft, setSecondsLeft] = useState(startSeconds);

  useEffect(() => {
    if (secondsLeft <= 0) return;

    const timer = setTimeout(() => setSecondsLeft((seconds) => seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [secondsLeft]);

  return secondsLeft;
}
