import { Pressable, Text, View } from 'react-native';

import { Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import type {
  SignupAccountFormValues,
  SignupConfirmFormValues,
  SignupHouseholdFormValues,
} from '../../types/signup';

import { CheckboxOption } from '../checkbox-option';
import { SignupStepHeading } from './signup-step-heading';
import { styles } from './signup-confirm-form.styles';

/** 확인 화면에서는 비밀번호를 다시 노출하지 않는다. */
const PASSWORD_MASK = '••••••';

type SignupConfirmFormProps = {
  account: SignupAccountFormValues;
  household: SignupHouseholdFormValues;
  complexName: string;
  values: SignupConfirmFormValues;
  onChange: <K extends keyof SignupConfirmFormValues>(
    key: K,
    value: SignupConfirmFormValues[K],
  ) => void;
  onEditAccount: () => void;
  onEditHousehold: () => void;
};

export function SignupConfirmForm({
  account,
  household,
  complexName,
  values,
  onChange,
  onEditAccount,
  onEditHousehold,
}: SignupConfirmFormProps) {
  const agreeAll = values.agreeTerms && values.agreePrivacy;

  const handleToggleAll = (checked: boolean) => {
    onChange('agreeTerms', checked);
    onChange('agreePrivacy', checked);
  };

  return (
    <Stack gap={Spacing.xl}>
      <SignupStepHeading
        title={'가입 정보를\n최종 확인해 주세요'}
        description="입력하신 정보가 맞는지 다시 한번 확인해 주세요"
      />

      <View style={styles.reviewCard}>
        <View style={styles.reviewCardHeaderRow}>
          <Text style={styles.reviewCardTitle}>계정 정보</Text>
          <Pressable accessibilityRole="button" onPress={onEditAccount}>
            <Text style={styles.reviewEditLink}>수정</Text>
          </Pressable>
        </View>
        <ReviewRow label="이름" value={account.name} />
        <ReviewRow label="아이디" value={account.username} />
        <ReviewRow label="비밀번호" value={PASSWORD_MASK} />
      </View>

      <View style={styles.reviewCard}>
        <View style={styles.reviewCardHeaderRow}>
          <Text style={styles.reviewCardTitle}>세대 정보</Text>
          <Pressable accessibilityRole="button" onPress={onEditHousehold}>
            <Text style={styles.reviewEditLink}>수정</Text>
          </Pressable>
        </View>
        <ReviewRow label="아파트" value={complexName} />
        <ReviewRow label="동/호수" value={`${household.buildingNumber}동 ${household.unitNumber}호`} />
      </View>

      <Stack gap={Spacing.sm}>
        <CheckboxOption
          label="모두 동의합니다"
          checked={agreeAll}
          onChange={handleToggleAll}
          labelStyle={styles.agreementAllLabel}
        />
        <CheckboxOption
          label="(필수) 서비스 이용약관"
          checked={values.agreeTerms}
          onChange={(checked) => onChange('agreeTerms', checked)}
          labelStyle={styles.agreementItemLabel}
        />
        <CheckboxOption
          label="(필수) 개인정보 처리방침"
          checked={values.agreePrivacy}
          onChange={(checked) => onChange('agreePrivacy', checked)}
          labelStyle={styles.agreementItemLabel}
        />
      </Stack>
    </Stack>
  );
}

type ReviewRowProps = {
  label: string;
  value: string;
};

function ReviewRow({ label, value }: ReviewRowProps) {
  return (
    <View style={styles.reviewRow}>
      <Text style={styles.reviewRowLabel}>{label}</Text>
      <Text style={styles.reviewRowValue}>{value}</Text>
    </View>
  );
}
