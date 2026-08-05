import NetInfo from '@react-native-community/netinfo';
import { focusManager, onlineManager, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, type ReactNode } from 'react';
import { AppState, Platform } from 'react-native';

import { queryClient } from '@/services/query-client';

/** RN의 AppState/NetInfo를 React Query의 focus/online 개념에 연결한다. Fast Refresh 시 리스너가 중복되지 않도록 effect cleanup으로 관리한다. */
export function QueryProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      if (Platform.OS !== 'web') focusManager.setFocused(state === 'active');
    });
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    onlineManager.setEventListener((setOnline) =>
      NetInfo.addEventListener((state) => setOnline(!!state.isConnected)),
    );
  }, []);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
