import * as ImagePicker from 'expo-image-picker';
import { useState } from 'react';
import { Alert } from 'react-native';

import type { RequestSituation } from '../components/request-compose/request-compose-situation-selector';

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

/**
 * E-02(이동 요청 작성) 폼의 로컬 입력 상태를 관리한다. POST /move-requests 연동 전이라
 * 제출 핸들러는 없고, 화면(request-compose-screen)이 값만 읽어서 그려주는 데 쓴다.
 */
export function useRequestComposeForm() {
  const [plateNumber, setPlateNumber] = useState('12가 3456');
  const [zoneLabel, setZoneLabel] = useState<string | null>('지하 1층 · B-14 구역');
  const [isZonePickerOpen, setIsZonePickerOpen] = useState(false);
  const [situation, setSituation] = useState<RequestSituation>('이중 주차');
  const [reason, setReason] = useState('출차 통로를 막고 있어 차량 이동을 요청합니다.');
  const [photos, setPhotos] = useState<string[]>([]);

  const openZonePicker = () => setIsZonePickerOpen(true);
  const closeZonePicker = () => setIsZonePickerOpen(false);

  const selectZoneSpot = (spotCode: string) => {
    setZoneLabel(toZoneLabel(spotCode));
    setIsZonePickerOpen(false);
  };

  const addPhoto = () => {
    if (photos.length >= MAX_PHOTOS) return;

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
  };
}
