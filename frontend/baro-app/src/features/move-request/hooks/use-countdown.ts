import { useEffect, useState } from 'react';

function formatRemaining(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

// dueAt까지 남은 시간을 mm:ss로 매초 갱신한다. dueAt이 없으면(아직 응답 전) 카운트다운하지 않는다.
export function useCountdown(dueAt: string | null) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!dueAt) return;

    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [dueAt]);

  if (!dueAt) {
    return { label: '00:00', isOverdue: false };
  }

  const remainingMs = new Date(dueAt).getTime() - now;
  return {
    label: formatRemaining(remainingMs),
    isOverdue: remainingMs <= 0,
  };
}
