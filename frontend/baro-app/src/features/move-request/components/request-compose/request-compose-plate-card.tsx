import { Text, TextInput, View } from 'react-native';

// 차량 등록(G-01/G-02)에서 쓰던 것과 같은 포맷/검증 로직을 그대로 재사용한다.
import { formatPlateNumberInput, isPlateNumberValid } from '@/features/vehicle/validation/register-car';

import { styles } from './request-compose-plate-card.styles';

const PLATE_NUMBER_PLACEHOLDER = 'ex. 12가 3456';

type RequestComposePlateCardProps = {
  plateNumber: string;
  onChangeText: (value: string) => void;
};

export function RequestComposePlateCard({ plateNumber, onChangeText }: RequestComposePlateCardProps) {
  const showError = plateNumber.length > 0 && !isPlateNumberValid(plateNumber);

  return (
    <View>
      <View style={[styles.card, showError && styles.cardError]}>
        <TextInput
          value={plateNumber}
          onChangeText={(text) => onChangeText(formatPlateNumberInput(text))}
          placeholder={PLATE_NUMBER_PLACEHOLDER}
          placeholderTextColor="#b6bac7"
          style={styles.plateText}
        />
      </View>
      {showError ? <Text style={styles.errorText}>차량 번호 형식을 확인해 주세요</Text> : null}
    </View>
  );
}
