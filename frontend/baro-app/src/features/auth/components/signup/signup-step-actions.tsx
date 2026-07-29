import { AppButton, Stack } from '@/components/ui';
import { Spacing } from '@/styles';

import type { SignupStep } from '../../types/signup';

import { styles } from './signup-step-actions.styles';

type SignupStepActionsProps = {
  step: SignupStep;
  canSubmit: boolean;
  onNext: () => void;
  onPrevious?: () => void;
};

export function SignupStepActions({ step, canSubmit, onNext, onPrevious }: SignupStepActionsProps) {
  if (step === 3) {
    return (
      <Stack direction="row" gap={Spacing.sm}>
        {onPrevious ? (
          <AppButton label="이전" variant="muted" size="lg" onPress={onPrevious} />
        ) : null}
        <AppButton
          label="가입 신청 완료하기"
          variant="neutral"
          size="lg"
          style={styles.grow}
          disabled={!canSubmit}
          onPress={onNext}
        />
      </Stack>
    );
  }

  return (
    <AppButton
      label="다음"
      variant={step === 1 ? 'primary' : 'neutral'}
      size="lg"
      fullWidth
      disabled={!canSubmit}
      onPress={onNext}
    />
  );
}
