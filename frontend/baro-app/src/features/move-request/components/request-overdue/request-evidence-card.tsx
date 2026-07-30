import { Text, View } from 'react-native';

import { styles } from './request-evidence-card.styles';

type RequestEvidenceCardProps = {
  plateNumber: string;
  location: string;
};

export function RequestEvidenceCard({ plateNumber, location }: RequestEvidenceCardProps) {
  return (
    <View style={styles.card}>
      <View style={styles.photoSlot}>
        <Text style={styles.photoSlotText}>{'현장\n사진'}</Text>
      </View>
      <Text style={styles.info}>{`${plateNumber} · ${location}`}</Text>
    </View>
  );
}
