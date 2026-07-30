import { useEffect, useState } from 'react';

function formatRemaining(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

/**
 * dueAt까지 남은 시간을 mm:ss로 매초 갱신한다.
 * startAt(약속이 시작된 시각, 보통 응답 시각)을 같이 주면 전체 구간 대비 남은 비율(progress, 1→0)도 계산해서
 * 링 형태 타이머가 시간이 줄어들수록 점점 짧아지도록 그릴 수 있게 해준다.
 */
export function useCountdown(dueAt: string | null, startAt: string | null = null) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!dueAt) return;

    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [dueAt]);

  if (!dueAt) {
    return { label: '00:00', progress: 0, isOverdue: false };
  }

  const dueMs = new Date(dueAt).getTime();
  const remainingMs = dueMs - now;
  const totalMs = startAt ? dueMs - new Date(startAt).getTime() : null;
  const progress = totalMs && totalMs > 0 ? Math.min(1, Math.max(0, remainingMs / totalMs)) : 0;

  return {
    label: formatRemaining(remainingMs),
    progress,
    isOverdue: remainingMs <= 0,
  };
}
