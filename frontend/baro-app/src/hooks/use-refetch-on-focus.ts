import { useFocusEffect, useIsFocused } from '@react-navigation/native';
import { useCallback, useEffect, useRef } from 'react';
import { AppState } from 'react-native';

/**
 * 화면 재진입 시, 그리고 이 화면이 실제로 보이는 상태에서 앱이 다시 활성화됐을 때
 * 캐시가 stale이면 재요청한다. 최초 마운트 포커스는 useQuery의 초기 fetch와 중복되므로 건너뛴다.
 *
 * isStale은 React Query가 staleTime 경과 시점에 내부 타이머로 자동 갱신하는 값이라, 화면에 머무는 동안에도
 * 렌더마다 값이 바뀐다. useFocusEffect는 전달받은 콜백의 참조가 바뀌면 화면이 이미 포커스된 상태에서도
 * 즉시 재실행하므로, 콜백 deps에 isStale을 직접 넣으면 staleTime마다 자동으로 refetch가 발생해
 * 없애려던 고정 폴링이 그대로 재현된다. 그래서 isStale은 ref로만 읽고, 콜백 자체는 실제 포커스 전환
 * (마운트/재진입)에만 반응하도록 refetch에만 의존시킨다.
 *
 * 앱 활성화(AppState) 재요청은 QueryClient의 기본 refetchOnWindowFocus를 쓰지 않고 여기서 직접
 * 처리한다 — Expo Router 스택에는 이전 화면들도 계속 마운트돼 있어서, 전역 refetchOnWindowFocus를
 * 쓰면 지금 안 보이는 뒤쪽 화면들의 쿼리까지 앱 활성화 때마다 한꺼번에 재요청되기 때문이다.
 * useIsFocused로 "지금 실제로 보이는 화면"일 때만 재요청하도록 좁힌다.
 */
export function useRefetchOnFocus(refetch: () => void, isStale: boolean): void {
  const hasFocusedBeforeRef = useRef(false);
  const isStaleRef = useRef(isStale);
  isStaleRef.current = isStale;
  const isFocused = useIsFocused();
  const isFocusedRef = useRef(isFocused);
  isFocusedRef.current = isFocused;

  useFocusEffect(
    useCallback(() => {
      if (!hasFocusedBeforeRef.current) {
        hasFocusedBeforeRef.current = true;
        return;
      }
      if (isStaleRef.current) refetch();
    }, [refetch]),
  );

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active' && isFocusedRef.current && isStaleRef.current) refetch();
    });
    return () => subscription.remove();
  }, [refetch]);
}
