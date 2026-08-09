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

/**
 * 알림 수신 설정을 조회하고, 저장 전 편집 값(draft)과 서버 저장 값(saved)을 분리 관리해 저장하기 전까지 화면이 서버 재조회로 덮이지 않게 한다.
 * API: GET /api/users/me/notification-settings, PATCH /api/users/me/notification-settings
 */
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
    // 앱 활성화/화면 재진입 재요청은 useRefetchOnFocus가 isStale && !dirty로 이미 처리한다.
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
    // 백그라운드 갱신 실패는 이미 화면에 표시된 설정을 지우지 않는다 — 캐시가 없을 때만 오류로 노출한다.
    loadErrorMessage:
      query.data === undefined && query.error
        ? query.error instanceof ApiError
          ? query.error.message
          : '알림 설정을 불러오지 못했습니다.'
        : undefined,
    saveErrorMessage,
    reload: () => query.refetch(),
    save,
    setResponseReminder,
    setEvOverstay,
    setQuietHoursStart,
    setQuietHoursEnd,
  };
}
