import { Text } from 'react-native';

import { styles } from './register-car-section-label.styles';

type RegisterCarSectionLabelProps = {
  children: string;
};

/** "차량 성격", "이용 가능 구역"처럼 입력 영역 위에 붙는 작은 섹션 제목. */
export function RegisterCarSectionLabel({ children }: RegisterCarSectionLabelProps) {
  return <Text style={styles.label}>{children}</Text>;
}
