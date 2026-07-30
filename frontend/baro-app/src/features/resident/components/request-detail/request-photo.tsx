import { Text, View } from 'react-native';

import { styles } from './request-photo.styles';

type RequestPhotoProps = {
  photoIndex: number;
  photoTotal: number;
};

// TODO(request-detail): 백엔드 사건 이미지 API가 연동되면 실제 사진으로 교체한다. 지금은 자리표시용 배경이다.
export function RequestPhoto({ photoIndex, photoTotal }: RequestPhotoProps) {
  return (
    <View style={styles.container}>
      <View style={styles.indicator}>
        <Text style={styles.indicatorText}>
          신고 사진 {photoIndex}/{photoTotal}
        </Text>
      </View>
    </View>
  );
}
