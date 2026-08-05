import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

import {
  getNotificationSettings,
  updateNotificationSettings,
} from '@/features/profile/api/notification-settings-api';
import type { NotificationSettings, UpdateNotificationSettingsRequest } from '@/features/profile/api/types';
import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';
import { refreshAuthenticatedQueries } from '@/services/authenticated-query-refresh';

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
  const loadingRef = useRef(false);
  const hasLoadedRef = useRef(false);
  const dirtyRef = useRef(false);
  const focusedRef = useRef(false);
  const appStateRef = useRef(AppState.currentState);
  dirtyRef.current = hasUnsavedChanges(draftSettings, savedSettings);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const loadSettings = useCallback(async (background = false) => {
    if (status !== 'authenticated' || !accessToken) {
      setIsLoading(false);
      return;
    }
    if (loadingRef.current || savingRef.current || dirtyRef.current) return;

    loadingRef.current = true;
    if (!background) setIsLoading(true);
    if (!background) setLoadErrorMessage(undefined);

    try {
      const result = await getNotificationSettings(accessToken);
      if (mountedRef.current) {
        setSavedSettings(result);
        setDraftSettings(result);
        hasLoadedRef.current = true;
        setLoadErrorMessage(undefined);
        refreshAuthenticatedQueries();
      }
    } catch (error) {
      if (!mountedRef.current) return;
      if (!background) {
        setLoadErrorMessage(
          error instanceof ApiError ? error.message : '알림 설정을 불러오지 못했습니다.',
        );
      }
    } finally {
      loadingRef.current = false;
      if (mountedRef.current && !background) setIsLoading(false);
    }
  }, [accessToken, status]);

  useEffect(() => {
    void loadSettings(false);
  }, [loadSettings]);

  useFocusEffect(
    useCallback(() => {
      focusedRef.current = true;
      if (hasLoadedRef.current && !dirtyRef.current) void loadSettings(true);
      return () => {
        focusedRef.current = false;
      };
    }, [loadSettings]),
  );

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      const becameActive = appStateRef.current !== 'active' && nextState === 'active';
      appStateRef.current = nextState;
      if (becameActive && focusedRef.current && !dirtyRef.current) void loadSettings(true);
    });
    return () => subscription.remove();
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
    reload: () => loadSettings(false),
    save,
    setResponseReminder,
    setEvOverstay,
    setQuietHoursStart,
    setQuietHoursEnd,
  };
}
