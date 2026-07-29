import { LinearGradient } from 'expo-linear-gradient';
import { Pressable, Text, TextInput, View } from 'react-native';

import { Stack } from '@/components/ui';
import { Gradients, Palette, Spacing } from '@/styles';

import type { SignupHouseholdFormValues } from '../../types/signup';

import { SignupStepHeading } from './signup-step-heading';
import { styles } from './signup-household-form.styles';

const UNIT_NUMBER_MAX_LENGTH = 4;

type SignupHouseholdFormProps = {
  complexName: string;
  values: SignupHouseholdFormValues;
  onChange: <K extends keyof SignupHouseholdFormValues>(
    key: K,
    value: SignupHouseholdFormValues[K],
  ) => void;
};

export function SignupHouseholdForm({ complexName, values, onChange }: SignupHouseholdFormProps) {
  return (
    <Stack gap={Spacing.xl}>
      <SignupStepHeading
        title={'거주하시는 세대를\n알려 주세요'}
        description="정확한 주차 관리를 위해 실제 거주 중인 세대 정보를 입력해 주세요"
      />

      <LinearGradient
        colors={Gradients.signupHouseholdCard}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.complexCard}
      >
        <View style={styles.complexHeaderRow}>
          <View style={styles.complexIconBadge}>
            <Text style={styles.complexIconText}>🏠</Text>
          </View>
          <Text style={styles.complexName}>{complexName}</Text>
        </View>

        <View style={styles.unitRow}>
          <View style={styles.unitField}>
            <TextInput
              accessibilityLabel="동"
              value={values.buildingNumber}
              onChangeText={(text) => onChange('buildingNumber', text)}
              placeholder="101"
              placeholderTextColor={Palette.gray400}
              keyboardType="number-pad"
              maxLength={UNIT_NUMBER_MAX_LENGTH}
              style={styles.unitInput}
            />
            <Text style={styles.unitSuffix}>동</Text>
          </View>
          <View style={styles.unitField}>
            <TextInput
              accessibilityLabel="호"
              value={values.unitNumber}
              onChangeText={(text) => onChange('unitNumber', text)}
              placeholder="1203"
              placeholderTextColor={Palette.gray400}
              keyboardType="number-pad"
              maxLength={UNIT_NUMBER_MAX_LENGTH}
              style={styles.unitInput}
            />
            <Text style={styles.unitSuffix}>호</Text>
          </View>
        </View>
      </LinearGradient>

      <Stack gap={Spacing.sm}>
        <Text style={styles.verificationLabel}>세대 확인 방법</Text>
        <Pressable
          accessibilityRole="radio"
          accessibilityState={{ checked: values.verificationConfirmed }}
          onPress={() => onChange('verificationConfirmed', !values.verificationConfirmed)}
          style={[
            styles.verificationOption,
            values.verificationConfirmed && styles.verificationOptionSelected,
          ]}
        >
          <Text style={styles.verificationOptionLabel}>관리사무소 명부 대조</Text>
          <View style={[styles.radio, values.verificationConfirmed && styles.radioSelected]} />
        </Pressable>
        <Text style={styles.verificationHelper}>세대 등록은 관리사무소 확인 후 완료됩니다</Text>
      </Stack>
    </Stack>
  );
}
