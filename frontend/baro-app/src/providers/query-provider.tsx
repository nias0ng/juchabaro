import NetInfo from '@react-native-community/netinfo';
import { focusManager, onlineManager, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, type ReactNode } from 'react';
import { AppState, Platform } from 'react-native';

import { queryClient } from '@/services/query-client';

/** RN의 AppState/NetInfo를 React Query의 focus/online 개념에 연결한다. Fast Refresh 시 리스너가 중복되지 않도록 effect cleanup으로 관리한다. */
export function QueryProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    if (Platform.OS !== 'web') {
      // 마운트 시점의 현재 AppState를 바로 반영한다 — 다음 변경 이벤트만 기다리면 Fast Refresh 직후
      // 등 focusManager가 false로 남아있던 상태에서 앱이 실제로는 활성 상태인데도 unfocused로 취급될 수 있다.
      focusManager.setFocused(AppState.currentState === 'active');
    }

    const subscription = AppState.addEventListener('change', (state) => {
      if (Platform.OS !== 'web') focusManager.setFocused(state === 'active');
    });
    return () => {
      subscription.remove();
      // 리스너가 사라진 뒤에도 이전 값이 남지 않도록 React Query의 기본 판단(플랫폼 기본 focus 이벤트)으로 되돌린다.
      if (Platform.OS !== 'web') focusManager.setFocused(undefined);
    };
  }, []);

  useEffect(() => {
    onlineManager.setEventListener((setOnline) =>
      NetInfo.addEventListener((state) => setOnline(!!state.isConnected)),
    );
  }, []);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
