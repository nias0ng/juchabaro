import { router } from 'expo-router';

import { ResponsiveContainer, Screen, Stack } from '@/components/ui';
import { Palette, Spacing } from '@/styles';

import { AuthHeader } from '../components/auth-header';
import { SignupProgress } from '../components/signup/signup-progress';
import { SignupStepActions } from '../components/signup/signup-step-actions';
import { SignupSteps } from '../components/signup/signup-steps';
import { useSignupForm } from '../hooks/use-signup-form';

const COMPLETE_BACKGROUND_GRADIENT = ['#eae7fb', '#f7f6fb'] as const;

export default function SignupScreen() {
  const signup = useSignupForm();
  const isCompleteStep = signup.step === 4;

  return (
    <Screen
      scroll
      avoidKeyboard
      backgroundColor={Palette.gray50}
      backgroundGradient={isCompleteStep ? COMPLETE_BACKGROUND_GRADIENT : undefined}
    >
      <ResponsiveContainer> 
        <Stack gap={Spacing.xl}>
          <AuthHeader
            title={isCompleteStep ? '회원가입 완료' : '회원가입'}
            onBack={signup.goToPreviousStep}
          />

          {!isCompleteStep && <SignupProgress step={signup.step} />}

          // SignupSteps로 회원 가입 단계 각각을 진행
          <SignupSteps
            signup={signup}
            onRegisterVehicle={() => router.replace('/resident/vehicles')}
            onGoHome={() => router.replace('/resident')}
          />

          {!isCompleteStep && (
            <SignupStepActions
              step={signup.step}
              canSubmit={signup.canSubmitStep}
              onNext={signup.goToNextStep}
              onPrevious={signup.goToPreviousStep}
            />
          )}
        </Stack>
      </ResponsiveContainer>
    </Screen>
  );
}
