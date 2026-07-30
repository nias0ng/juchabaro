import { router } from 'expo-router';

import {
  FormErrorBanner,
  ResponsiveContainer,
  Screen,
  ScreenHeader,
  Stack,
} from '@/components/ui';
import { Palette, Spacing } from '@/styles';

import { SignupProgress } from '../components/signup/signup-progress';
import { SignupStepActions } from '../components/signup/signup-step-actions';
import { SignupSteps } from '../components/signup/signup-steps';
import { useSignupForm } from '../hooks/use-signup-form';

const COMPLETE_BACKGROUND_GRADIENT = ['#eae7fb', '#f7f6fb'] as const;

export default function SignupScreen() {
  const signup = useSignupForm();
  const isCompleteStep = signup.step === 4;
  const goToAuthenticatedArea = (href: '/resident' | '/auth/register-car') => {
    router.replace(signup.autoLoginFailed ? '/auth/login' : href);
  };

  return (
    <Screen
      scroll
      avoidKeyboard
      backgroundColor={Palette.gray50}
      backgroundGradient={isCompleteStep ? COMPLETE_BACKGROUND_GRADIENT : undefined}
    >
      <ResponsiveContainer> 
        <Stack gap={Spacing.xl}>
          <ScreenHeader
            title={isCompleteStep ? '회원가입 완료' : '회원가입'}
            onBack={signup.goToPreviousStep}
          />

          {!isCompleteStep && <SignupProgress step={signup.step} />}

          <SignupSteps
            signup={signup}
            onRegisterVehicle={() => goToAuthenticatedArea('/auth/register-car')}
            onGoHome={() => goToAuthenticatedArea('/resident')}
          />

          {signup.errorMessage ? <FormErrorBanner message={signup.errorMessage} /> : null}

          {!isCompleteStep && (
            <SignupStepActions
              step={signup.step}
              canSubmit={signup.canSubmitStep}
              isSubmitting={signup.isSubmitting}
              onNext={signup.goToNextStep}
              onPrevious={signup.goToPreviousStep}
            />
          )}
        </Stack>
      </ResponsiveContainer>
    </Screen>
  );
}
