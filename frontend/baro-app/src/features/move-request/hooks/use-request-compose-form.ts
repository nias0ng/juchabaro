import * as ImagePicker from 'expo-image-picker';
import { useState } from 'react';
import { Alert, Platform } from 'react-native';

import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';
import { isPlateNumberValid, toApiPlateNumber } from '@/features/vehicle/validation/register-car';

import { postMoveRequest } from '../api/move-request-api';
import type { MoveRequestCreateResult } from '../api/types';
import {
  SITUATION_EVENT_TYPE,
  type RequestSituation,
} from '../components/request-compose/request-compose-situation-selector';

const MAX_PHOTOS = 3;
// 홈 화면 주차 현황 카드와 동일하게, 지금은 지하 1층 하나만 지원한다(구역 API에 층 정보가 없음).
const ZONE_FLOOR_LABEL = '지하 1층';

function toZoneLabel(spotCode: string): string {
  return `${ZONE_FLOOR_LABEL} · ${spotCode} 구역`;
}

async function pickImage(source: 'camera' | 'library'): Promise<string | null> {
  const permissionResult =
    source === 'camera'
      ? await ImagePicker.requestCameraPermissionsAsync()
      : await ImagePicker.requestMediaLibraryPermissionsAsync();

  if (!permissionResult.granted) {
    Alert.alert('권한이 필요합니다', source === 'camera' ? '카메라 접근 권한을 허용해 주세요.' : '앨범 접근 권한을 허용해 주세요.');
    return null;
  }

  const result =
    source === 'camera'
      ? await ImagePicker.launchCameraAsync({ quality: 0.7 })
      : await ImagePicker.launchImageLibraryAsync({ quality: 0.7 });

  if (result.canceled || result.assets.length === 0) return null;
  return result.assets[0].uri;
}

/** E-02(이동 요청 작성) 폼의 입력 상태와 POST /move-requests 제출을 관리한다. */
export function useRequestComposeForm() {
  const { accessToken } = useAuth();

  const [plateNumber, setPlateNumber] = useState('');
  const [zoneLabel, setZoneLabel] = useState<string | null>(null);
  // 구역 지도에는 zoneId가 없어 zoneName으로 보낸다. 고른 자리 코드(spotCode)가 곧 zoneName이 된다.
  const [zoneName, setZoneName] = useState<string | null>(null);
  const [isZonePickerOpen, setIsZonePickerOpen] = useState(false);
  const [situation, setSituation] = useState<RequestSituation>('이중 주차');
  const [reason, setReason] = useState('');
  const [photos, setPhotos] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string>();

  const openZonePicker = () => setIsZonePickerOpen(true);
  const closeZonePicker = () => setIsZonePickerOpen(false);

  const selectZoneSpot = (spotCode: string) => {
    setZoneLabel(toZoneLabel(spotCode));
    setZoneName(spotCode);
    setIsZonePickerOpen(false);
  };

  const addPhoto = () => {
    if (photos.length >= MAX_PHOTOS) return;

    // 웹은 Alert.alert가 동작하지 않으므로(react-native-web no-op) 선택창 없이 바로 파일 선택창을 띄운다.
    if (Platform.OS === 'web') {
      pickImage('library').then((uri) => {
        if (uri) setPhotos((prev) => [...prev, uri]);
      });
      return;
    }

    // 카메라로 바로 찍을지, 앨범에서 고를지 물어본다.
    Alert.alert('현장 사진 추가', '사진을 어떻게 추가할까요?', [
      {
        text: '사진 촬영',
        onPress: async () => {
          const uri = await pickImage('camera');
          if (uri) setPhotos((prev) => [...prev, uri]);
        },
      },
      {
        text: '앨범에서 선택',
        onPress: async () => {
          const uri = await pickImage('library');
          if (uri) setPhotos((prev) => [...prev, uri]);
        },
      },
      { text: '취소', style: 'cancel' },
    ]);
  };

  const removePhoto = (index: number) => {
    setPhotos((prev) => prev.filter((_, photoIndex) => photoIndex !== index));
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
      return await postMoveRequest(
        {
          targetPlateNumber: toApiPlateNumber(plateNumber),
          eventType: SITUATION_EVENT_TYPE[situation],
          reason: reason.trim(),
          zoneName: zoneName ?? undefined,
          images: photos,
        },
        accessToken,
      );
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
    maxPhotos: MAX_PHOTOS,
    addPhoto,
    removePhoto,
    canSubmit,
    isSubmitting,
    submitError,
    submit,
  };
}
