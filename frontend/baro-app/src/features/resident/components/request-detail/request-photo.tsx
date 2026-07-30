import { Image } from 'expo-image';
import { useState } from 'react';
import { ScrollView, Text, View, type LayoutChangeEvent, type NativeSyntheticEvent, type NativeScrollEvent } from 'react-native';

import { styles } from './request-photo.styles';

type RequestPhotoProps = {
  photos: { imageId: number; imageUrl: string }[];
};

export function RequestPhoto({ photos }: RequestPhotoProps) {
  const [containerWidth, setContainerWidth] = useState(0);
  const [index, setIndex] = useState(0);

  const handleLayout = (event: LayoutChangeEvent) => {
    setContainerWidth(event.nativeEvent.layout.width);
  };

  // pagingEnabled가 스크롤뷰 자체 너비 기준으로 스냅하므로, 각 사진도 같은 픽셀 너비로 맞춰야 페이지가 어긋나지 않는다.
  const handleScrollEnd = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    if (containerWidth === 0) return;
    setIndex(Math.round(event.nativeEvent.contentOffset.x / containerWidth));
  };

  return (
    <View style={styles.container} onLayout={handleLayout}>
      {photos.length > 0 && containerWidth > 0 ? (
        <ScrollView
          horizontal
          pagingEnabled
          showsHorizontalScrollIndicator={false}
          onMomentumScrollEnd={handleScrollEnd}
        >
          {photos.map((photo) => (
            <Image
              key={photo.imageId}
              source={{ uri: photo.imageUrl }}
              style={[styles.photo, { width: containerWidth }]}
              contentFit="cover"
            />
          ))}
        </ScrollView>
      ) : null}

      {photos.length > 0 ? (
        <View style={styles.indicator}>
          <Text style={styles.indicatorText}>
            신고 사진 {index + 1}/{photos.length}
          </Text>
        </View>
      ) : null}
    </View>
  );
}
