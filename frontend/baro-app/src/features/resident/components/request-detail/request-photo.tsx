import { Image } from 'expo-image';
import { useRef, useState } from 'react';
import {
  Modal,
  Pressable,
  ScrollView,
  Text,
  View,
  useWindowDimensions,
  type LayoutChangeEvent,
  type NativeSyntheticEvent,
  type NativeScrollEvent,
} from 'react-native';

import { styles } from './request-photo.styles';

type RequestPhotoProps = {
  photos: { imageId: number; imageUrl: string }[];
};

export function RequestPhoto({ photos }: RequestPhotoProps) {
  const scrollRef = useRef<ScrollView>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [index, setIndex] = useState(0);
  const [isViewerOpen, setIsViewerOpen] = useState(false);

  const handleLayout = (event: LayoutChangeEvent) => {
    setContainerWidth(event.nativeEvent.layout.width);
  };

  // pagingEnabled가 스크롤뷰 자체 너비 기준으로 스냅하므로, 각 사진도 같은 픽셀 너비로 맞춰야 페이지가 어긋나지 않는다.
  const handleScrollEnd = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    if (containerWidth === 0) return;
    setIndex(Math.round(event.nativeEvent.contentOffset.x / containerWidth));
  };

  // 웹은 마우스 드래그로 가로 스크롤이 안 넘어가서, 좌우 탭 영역으로도 넘길 수 있게 한다.
  const goToIndex = (nextIndex: number) => {
    const clamped = Math.max(0, Math.min(photos.length - 1, nextIndex));
    setIndex(clamped);
    scrollRef.current?.scrollTo({ x: clamped * containerWidth, animated: true });
  };

  return (
    <View style={styles.container} onLayout={handleLayout}>
      {photos.length > 0 && containerWidth > 0 ? (
        <>
          <ScrollView
            ref={scrollRef}
            style={styles.carousel}
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

          {/* 가운데는 눌러서 크게 보기, 양 끝 얇은 영역만 이전/다음 넘기기 */}
          <View style={styles.tapZones} pointerEvents="box-none">
            {photos.length > 1 ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="이전 사진"
                style={styles.edgeTapZone}
                onPress={() => goToIndex(index - 1)}
              />
            ) : (
              <View style={styles.edgeTapZone} pointerEvents="none" />
            )}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="사진 크게 보기"
              style={styles.centerTapZone}
              onPress={() => setIsViewerOpen(true)}
            />
            {photos.length > 1 ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="다음 사진"
                style={styles.edgeTapZone}
                onPress={() => goToIndex(index + 1)}
              />
            ) : (
              <View style={styles.edgeTapZone} pointerEvents="none" />
            )}
          </View>
        </>
      ) : null}

      {photos.length > 0 ? (
        <View style={styles.indicator} pointerEvents="none">
          <Text style={styles.indicatorText}>
            신고 사진 {index + 1}/{photos.length}
          </Text>
        </View>
      ) : null}

      <RequestPhotoViewer
        visible={isViewerOpen}
        photos={photos}
        index={index}
        onChangeIndex={setIndex}
        onClose={() => setIsViewerOpen(false)}
      />
    </View>
  );
}

type RequestPhotoViewerProps = {
  visible: boolean;
  photos: { imageId: number; imageUrl: string }[];
  index: number;
  onChangeIndex: (index: number) => void;
  onClose: () => void;
};

// 크게 보기 모드에서는 잘리지 않게 비율 그대로 다 보여준다(contain).
function RequestPhotoViewer({ visible, photos, index, onChangeIndex, onClose }: RequestPhotoViewerProps) {
  const { width, height } = useWindowDimensions();

  const handleScrollEnd = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    onChangeIndex(Math.round(event.nativeEvent.contentOffset.x / width));
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.viewerBackdrop}>
        <ScrollView
          horizontal
          pagingEnabled
          showsHorizontalScrollIndicator={false}
          contentOffset={{ x: index * width, y: 0 }}
          onMomentumScrollEnd={handleScrollEnd}
        >
          {photos.map((photo) => (
            <Image
              key={photo.imageId}
              source={{ uri: photo.imageUrl }}
              style={{ width, height }}
              contentFit="contain"
            />
          ))}
        </ScrollView>

        <Pressable accessibilityRole="button" accessibilityLabel="닫기" style={styles.viewerCloseButton} onPress={onClose}>
          <Text style={styles.viewerCloseText}>✕</Text>
        </Pressable>

        {photos.length > 0 ? (
          <View style={styles.viewerIndicator} pointerEvents="none">
            <Text style={styles.indicatorText}>
              신고 사진 {index + 1}/{photos.length}
            </Text>
          </View>
        ) : null}
      </View>
    </Modal>
  );
}
