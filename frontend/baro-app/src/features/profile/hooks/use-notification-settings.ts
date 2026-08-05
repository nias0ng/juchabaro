import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import {
  getNotificationSettings,
  updateNotificationSettings,
} from '@/features/profile/api/notification-settings-api';
import type { NotificationSettings, UpdateNotificationSettingsRequest } from '@/features/profile/api/types';
import { useRefetchOnFocus } from '@/hooks/use-refetch-on-focus';
import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';
import { queryKeys } from '@/services/query-keys';

const DEFAULT_SETTINGS: NotificationSettings = {
  moveRequestReceive: true,
  responseReminder: true,
  evOverstay: true,
  quietHoursStart: '23:00',
  quietHoursEnd: '07:00',
};

function hasUnsavedChanges(draft: NotificationSettings, saved: NotificationSettings): boolean {
  return (
    draft.responseReminder !== saved.responseReminder ||
    draft.evOverstay !== saved.evOverstay ||
    draft.quietHoursStart !== saved.quietHoursStart ||
    draft.quietHoursEnd !== saved.quietHoursEnd
  );
}

export function useNotificationSettings() {
  const { accessToken, status } = useAuth();
  const queryClient = useQueryClient();

  // savedSettings는 서버에 실제로 저장된 값, draftSettings는 화면에서 편집 중인(아직 저장 전) 값이다.
  const [savedSettings, setSavedSettings] = useState<NotificationSettings>(DEFAULT_SETTINGS);
  const [draftSettings, setDraftSettings] = useState<NotificationSettings>(DEFAULT_SETTINGS);
  const [saveErrorMessage, setSaveErrorMessage] = useState<string>();
  const dirty = hasUnsavedChanges(draftSettings, savedSettings);

  const query = useQuery({
    queryKey: queryKeys.notifications.settings(),
    queryFn: () => getNotificationSettings(accessToken!),
    enabled: status === 'authenticated' && !!accessToken,
    refetchOnWindowFocus: !dirty,
    refetchOnReconnect: !dirty,
  });
  useRefetchOnFocus(query.refetch, query.isStale && !dirty);

  useEffect(() => {
    // dirty 중엔 서버 데이터가 갱신돼도 saved/draft 둘 다 덮어쓰지 않는다.
    if (!dirty && query.data) {
      setSavedSettings(query.data);
      setDraftSettings(query.data);
    }
  }, [query.data, dirty]);

  const saveMutation = useMutation({
    mutationFn: (payload: UpdateNotificationSettingsRequest) => updateNotificationSettings(payload, accessToken!),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.notifications.settings(), result);
      setSavedSettings(result);
      setDraftSettings(result);
      // 별도 dirty 초기화 불필요 — draft === saved가 되어 dirty가 자동으로 false가 된다.
    },
    onError: (error) => {
      setSaveErrorMessage(error instanceof ApiError ? error.message : '알림 설정을 저장하지 못했습니다.');
    },
  });

  const save = () => {
    if (!accessToken || saveMutation.isPending || !dirty) return;

    setSaveErrorMessage(undefined);
    saveMutation.mutate({
      responseReminder: draftSettings.responseReminder,
      evOverstay: draftSettings.evOverstay,
      quietHoursStart: draftSettings.quietHoursStart,
      quietHoursEnd: draftSettings.quietHoursEnd,
    });
  };

  const setResponseReminder = (value: boolean) =>
    setDraftSettings((current) => ({ ...current, responseReminder: value }));
  const setEvOverstay = (value: boolean) =>
    setDraftSettings((current) => ({ ...current, evOverstay: value }));
  const setQuietHoursStart = (value: string) =>
    setDraftSettings((current) => ({ ...current, quietHoursStart: value }));
  const setQuietHoursEnd = (value: string) =>
    setDraftSettings((current) => ({ ...current, quietHoursEnd: value }));

  return {
    settings: draftSettings,
    hasChanges: dirty,
    isLoading: query.isLoading,
    isSaving: saveMutation.isPending,
    loadErrorMessage: query.error instanceof ApiError ? query.error.message : query.error ? '알림 설정을 불러오지 못했습니다.' : undefined,
    saveErrorMessage,
    reload: () => query.refetch(),
    save,
    setResponseReminder,
    setEvOverstay,
    setQuietHoursStart,
    setQuietHoursEnd,
  };
}
