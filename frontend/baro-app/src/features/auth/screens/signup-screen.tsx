import { router } from 'expo-router';

import { ResponsiveContainer, Screen, Stack } from '@/components/ui';
import { Palette, Spacing } from '@/styles';

import { AuthErrorBanner } from '../components/auth-error-banner';
import { AuthHeader } from '../components/auth-header';
import { SignupProgress } from '../components/signup/signup-progress';
import { SignupStepActions } from '../components/signup/signup-step-actions';
import { SignupSteps } from '../components/signup/signup-steps';
import { useSignupForm } from '../hooks/use-signup-form';

const COMPLETE_BACKGROUND_GRADIENT = ['#eae7fb', '#f7f6fb'] as const;

export default function SignupScreen() {
  const signup = useSignupForm();
  const isCompleteStep = signup.step === 4;
  const goToAuthenticatedArea = (href: '/resident' | '/resident/vehicles') => {
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
          <AuthHeader
            title={isCompleteStep ? '회원가입 완료' : '회원가입'}
            onBack={signup.goToPreviousStep}
          />

          {!isCompleteStep && <SignupProgress step={signup.step} />}

          <SignupSteps
            signup={signup}
            onRegisterVehicle={() => goToAuthenticatedArea('/resident/vehicles')}
            onGoHome={() => goToAuthenticatedArea('/resident')}
          />

          {signup.errorMessage ? <AuthErrorBanner message={signup.errorMessage} /> : null}

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
