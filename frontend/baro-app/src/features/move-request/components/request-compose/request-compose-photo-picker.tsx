import { Image } from 'expo-image';
import { Pressable, Text, View } from 'react-native';

import { styles } from './request-compose-photo-picker.styles';

type RequestComposePhotoPickerProps = {
  photos: string[];
  maxPhotos: number;
  onPressAdd: () => void;
  onRemove: (index: number) => void;
};

export function RequestComposePhotoPicker({ photos, maxPhotos, onPressAdd, onRemove }: RequestComposePhotoPickerProps) {
  const canAddMore = photos.length < maxPhotos;

  return (
    <View style={styles.row}>
      {photos.map((uri, index) => (
        <View key={uri} style={styles.slot}>
          <Image source={{ uri }} style={styles.slotImage} contentFit="cover" />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="사진 삭제"
            hitSlop={8}
            style={styles.removeButton}
            onPress={() => onRemove(index)}
          >
            <Text style={styles.removeIcon}>✕</Text>
          </Pressable>
        </View>
      ))}

      {canAddMore ? (
        <Pressable accessibilityRole="button" style={styles.addSlot} onPress={onPressAdd}>
          <Text style={styles.addIcon}>+</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
