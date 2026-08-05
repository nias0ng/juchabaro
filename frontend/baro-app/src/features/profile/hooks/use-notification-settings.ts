import { useCallback, useEffect, useRef, useState } from 'react';

import {
  getNotificationSettings,
  updateNotificationSettings,
} from '@/features/profile/api/notification-settings-api';
import type { NotificationSettings, UpdateNotificationSettingsRequest } from '@/features/profile/api/types';
import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';

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
  // savedSettings는 서버에 실제로 저장된 값, draftSettings는 화면에서 편집 중인(아직 저장 전) 값이다.
  const [savedSettings, setSavedSettings] = useState<NotificationSettings>(DEFAULT_SETTINGS);
  const [draftSettings, setDraftSettings] = useState<NotificationSettings>(DEFAULT_SETTINGS);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [loadErrorMessage, setLoadErrorMessage] = useState<string>();
  const [saveErrorMessage, setSaveErrorMessage] = useState<string>();
  const mountedRef = useRef(true);
  const savingRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const loadSettings = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setLoadErrorMessage(undefined);

    try {
      const result = await getNotificationSettings(accessToken);
      if (mountedRef.current) {
        setSavedSettings(result);
        setDraftSettings(result);
      }
    } catch (error) {
      if (!mountedRef.current) return;
      setLoadErrorMessage(
        error instanceof ApiError ? error.message : '알림 설정을 불러오지 못했습니다.',
      );
    } finally {
      if (mountedRef.current) setIsLoading(false);
    }
  }, [accessToken, status]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const save = useCallback(async () => {
    if (!accessToken || savingRef.current || !hasUnsavedChanges(draftSettings, savedSettings)) return;

    const request: UpdateNotificationSettingsRequest = {
      responseReminder: draftSettings.responseReminder,
      evOverstay: draftSettings.evOverstay,
      quietHoursStart: draftSettings.quietHoursStart,
      quietHoursEnd: draftSettings.quietHoursEnd,
    };

    savingRef.current = true;
    setIsSaving(true);
    setSaveErrorMessage(undefined);

    try {
      const result = await updateNotificationSettings(request, accessToken);
      if (mountedRef.current) {
        setSavedSettings(result);
        setDraftSettings(result);
      }
    } catch (error) {
      if (!mountedRef.current) return;
      setSaveErrorMessage(
        error instanceof ApiError ? error.message : '알림 설정을 저장하지 못했습니다.',
      );
    } finally {
      savingRef.current = false;
      if (mountedRef.current) setIsSaving(false);
    }
  }, [accessToken, draftSettings, savedSettings]);

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
    hasChanges: hasUnsavedChanges(draftSettings, savedSettings),
    isLoading,
    isSaving,
    loadErrorMessage,
    saveErrorMessage,
    reload: loadSettings,
    save,
    setResponseReminder,
    setEvOverstay,
    setQuietHoursStart,
    setQuietHoursEnd,
  };
}
