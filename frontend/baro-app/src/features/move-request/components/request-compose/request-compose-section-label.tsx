import { Text } from 'react-native';

import { styles } from './request-compose-section-label.styles';

type RequestComposeSectionLabelProps = {
  label: string;
  suffix?: string;
};

/** 폼 섹션 제목("차량 번호", "현장 사진 2/3" 등)에 공통으로 쓰는 라벨. */
export function RequestComposeSectionLabel({ label, suffix }: RequestComposeSectionLabelProps) {
  return (
    <Text style={styles.label}>
      {label}
      {suffix ? <Text style={styles.suffix}>{` ${suffix}`}</Text> : null}
    </Text>
  );
}
