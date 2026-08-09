import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';
import { isPlateNumberValid, toApiPlateNumber } from '@/features/vehicle/validation/register-car';
import { queryKeys } from '@/services/query-keys';

import { postMoveRequest } from '../api/move-request-api';
import type { MoveRequestCreateResult } from '../api/types';
import {
  SITUATION_EVENT_TYPE,
  type RequestSituation,
} from '../components/request-compose/request-compose-situation-selector';
import { useRequestPhotos } from './use-request-photos';

// 홈 화면 주차 현황 카드와 동일하게, 지금은 지하 1층 하나만 지원한다(구역 API에 층 정보가 없음).
const ZONE_FLOOR_LABEL = '지하 1층';

function toZoneLabel(spotCode: string): string {
  return `${ZONE_FLOOR_LABEL} · ${spotCode} 구역`;
}

/**
 * 이동 요청 작성 폼의 입력 상태와 제출을 관리한다.
 * API: POST /api/move-requests
 */
export function useRequestComposeForm() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const { photos, maxPhotos, addPhoto, removePhoto } = useRequestPhotos();

  const [plateNumber, setPlateNumber] = useState('');
  const [zoneLabel, setZoneLabel] = useState<string | null>(null);
  // 구역 지도에는 zoneId가 없어 zoneName으로 보낸다. 고른 자리 코드(spotCode)가 곧 zoneName이 된다.
  const [zoneName, setZoneName] = useState<string | null>(null);
  const [isZonePickerOpen, setIsZonePickerOpen] = useState(false);
  const [situation, setSituation] = useState<RequestSituation>('이중 주차');
  const [reason, setReason] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string>();

  const openZonePicker = () => setIsZonePickerOpen(true);
  const closeZonePicker = () => setIsZonePickerOpen(false);

  const selectZoneSpot = (spotCode: string) => {
    setZoneLabel(toZoneLabel(spotCode));
    setZoneName(spotCode);
    setIsZonePickerOpen(false);
  };

  const canSubmit =
    isPlateNumberValid(plateNumber) &&
    zoneName !== null &&
    photos.length > 0 &&
    reason.trim().length > 0;

  const submit = async (): Promise<MoveRequestCreateResult | null> => {
    if (!canSubmit || !accessToken || isSubmitting) return null;

    setIsSubmitting(true);
    setSubmitError(undefined);

    try {
      const result = await postMoveRequest(
        {
          targetPlateNumber: toApiPlateNumber(plateNumber),
          eventType: SITUATION_EVENT_TYPE[situation],
          reason: reason.trim(),
          zoneName: zoneName ?? undefined,
          images: photos,
        },
        accessToken,
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.moveRequests.lists() });
      return result;
    } catch (error) {
      setSubmitError(error instanceof ApiError ? error.message : '이동 요청을 보내지 못했습니다.');
      return null;
    } finally {
      setIsSubmitting(false);
    }
  };

  return {
    plateNumber,
    setPlateNumber,
    zoneLabel,
    isZonePickerOpen,
    openZonePicker,
    closeZonePicker,
    selectZoneSpot,
    situation,
    setSituation,
    reason,
    setReason,
    photos,
    maxPhotos,
    addPhoto,
    removePhoto,
    canSubmit,
    isSubmitting,
    submitError,
    submit,
  };
}
