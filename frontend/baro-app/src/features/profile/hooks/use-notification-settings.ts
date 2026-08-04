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

export function useNotificationSettings() {
  const { accessToken, status } = useAuth();
  const [settings, setSettings] = useState<NotificationSettings>(DEFAULT_SETTINGS);
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
      if (mountedRef.current) setSettings(result);
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

  const saveSettings = useCallback(
    async (request: UpdateNotificationSettingsRequest) => {
      if (!accessToken || savingRef.current) return;

      const previousSettings = settings;
      savingRef.current = true;
      setIsSaving(true);
      setSaveErrorMessage(undefined);
      setSettings((current) => ({ ...current, ...request }));

      try {
        const result = await updateNotificationSettings(request, accessToken);
        if (mountedRef.current) setSettings(result);
      } catch (error) {
        if (!mountedRef.current) return;
        setSettings(previousSettings);
        setSaveErrorMessage(
          error instanceof ApiError ? error.message : '알림 설정을 저장하지 못했습니다.',
        );
      } finally {
        savingRef.current = false;
        if (mountedRef.current) setIsSaving(false);
      }
    },
    [accessToken, settings],
  );

  const setResponseReminder = (value: boolean) => void saveSettings({ responseReminder: value });
  const setEvOverstay = (value: boolean) => void saveSettings({ evOverstay: value });
  const setQuietHoursStart = (value: string) => void saveSettings({ quietHoursStart: value });
  const setQuietHoursEnd = (value: string) => void saveSettings({ quietHoursEnd: value });

  return {
    settings,
    isLoading,
    isSaving,
    loadErrorMessage,
    saveErrorMessage,
    reload: loadSettings,
    setResponseReminder,
    setEvOverstay,
    setQuietHoursStart,
    setQuietHoursEnd,
  };
}
