import * as ImagePicker from 'expo-image-picker';
import { useState } from 'react';
import { Alert, Platform } from 'react-native';

const MAX_PHOTOS = 3;

async function pickImages(source: 'camera' | 'library', selectionLimit: number): Promise<string[]> {
  const permissionResult =
    source === 'camera'
      ? await ImagePicker.requestCameraPermissionsAsync()
      : await ImagePicker.requestMediaLibraryPermissionsAsync();

  if (!permissionResult.granted) {
    Alert.alert('권한이 필요합니다', source === 'camera' ? '카메라 접근 권한을 허용해 주세요.' : '앨범 접근 권한을 허용해 주세요.');
    return [];
  }

  const result =
    source === 'camera'
      ? await ImagePicker.launchCameraAsync({ mediaTypes: ['images'], quality: 0.7 })
      : await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ['images'],
          quality: 0.7,
          allowsMultipleSelection: true,
          orderedSelection: true,
          selectionLimit,
        });

  if (result.canceled || result.assets.length === 0) return [];
  return result.assets.slice(0, selectionLimit).map((asset) => asset.uri);
}

/** E-02(이동 요청 작성)의 현장 사진 촬영/앨범 선택/삭제와 최대 개수를 관리한다. */
export function useRequestPhotos(maxPhotos: number = MAX_PHOTOS) {
  const [photos, setPhotos] = useState<string[]>([]);

  const appendPhotos = (selectedPhotos: string[]) => {
    setPhotos((prev) => {
      const uniquePhotos = selectedPhotos.filter((uri) => !prev.includes(uri));
      return [...prev, ...uniquePhotos].slice(0, maxPhotos);
    });
  };

  const addPhoto = () => {
    if (photos.length >= maxPhotos) return;
    const remainingCount = maxPhotos - photos.length;

    // 웹은 Alert.alert가 동작하지 않으므로(react-native-web no-op) 선택창 없이 바로 파일 선택창을 띄운다.
    if (Platform.OS === 'web') {
      pickImages('library', remainingCount).then(appendPhotos);
      return;
    }

    // 카메라로 바로 찍을지, 앨범에서 고를지 물어본다.
    Alert.alert('현장 사진 추가', '사진을 어떻게 추가할까요?', [
      {
        text: '사진 촬영',
        onPress: async () => {
          appendPhotos(await pickImages('camera', 1));
        },
      },
      {
        text: '앨범에서 선택',
        onPress: async () => {
          appendPhotos(await pickImages('library', remainingCount));
        },
      },
      { text: '취소', style: 'cancel' },
    ]);
  };

  const removePhoto = (index: number) => {
    setPhotos((prev) => prev.filter((_, photoIndex) => photoIndex !== index));
  };

  return { photos, maxPhotos, addPhoto, removePhoto };
}
