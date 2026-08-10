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

    // dueAt이 새로 생기는(또는 바뀌는) 순간 now를 다시 찍는다. 그냥 두면 컴포넌트가
    // 처음 마운트됐을 때(dueAt이 아직 null이던 시점)의 오래된 now가 그대로 남아있게 된다.
    setNow(Date.now());
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [dueAt]);

  if (!dueAt) {
    return { label: '00:00', progress: 0, isOverdue: false, elapsedLabel: '00:00', remainingMs: 0 };
  }

  const dueMs = new Date(dueAt).getTime();
  const remainingMs = dueMs - now;
  const totalMs = startAt ? dueMs - new Date(startAt).getTime() : null;
  const progress = totalMs && totalMs > 0 ? Math.min(1, Math.max(0, remainingMs / totalMs)) : 0;

  return {
    label: formatRemaining(remainingMs),
    progress,
    isOverdue: remainingMs <= 0,
    // dueAt이 지난 뒤로 얼마나 지났는지 mm:ss로. 아직 안 지났으면 00:00.
    elapsedLabel: remainingMs < 0 ? formatRemaining(-remainingMs) : '00:00',
    // 호출하는 화면에서 시간·분 등 목적에 맞는 형식으로 표시할 때 사용한다.
    remainingMs,
  };
}
