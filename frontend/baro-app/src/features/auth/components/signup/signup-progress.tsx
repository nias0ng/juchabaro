import { Text, View } from 'react-native';

import { SIGNUP_INPUT_STEP_COUNT, type SignupStep } from '../../types/signup';

import { styles } from './signup-progress.styles';

type SignupProgressProps = {
  step: SignupStep;
};

export function SignupProgress({ step }: SignupProgressProps) {
  return (
    <View style={styles.row}>
      {Array.from({ length: SIGNUP_INPUT_STEP_COUNT }, (_, index) => (
        <View key={index} style={[styles.track, index < step && styles.trackActive]} />
      ))}
      <Text style={styles.label}>
        {step} / {SIGNUP_INPUT_STEP_COUNT}
      </Text>
    </View>
  );
}
