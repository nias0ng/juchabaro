import { router } from 'expo-router';

import { ResponsiveContainer, Screen, ScreenHeader, Stack } from '@/components/ui';
import { Gradients, Palette, Spacing } from '@/styles';

import { AuthErrorBanner } from '../components/auth-error-banner';
import { SignupProgress } from '../components/signup/signup-progress';
import { SignupStepActions } from '../components/signup/signup-step-actions';
import { SignupSteps } from '../components/signup/signup-steps';
import { useSignupForm } from '../hooks/use-signup-form';
import { styles } from './signup-screen.styles';

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
      backgroundGradient={isCompleteStep ? Gradients.signupCompleteBackground : undefined}
    >
      <ResponsiveContainer> 
        <Stack gap={Spacing.xl}>
          <ScreenHeader
            title={isCompleteStep ? '회원가입 완료' : '회원가입'}
            onBack={signup.goToPreviousStep}
            style={styles.header}
          />

          {!isCompleteStep && <SignupProgress step={signup.step} />}

          <SignupSteps
            signup={signup}
            onRegisterVehicle={() => goToAuthenticatedArea('/auth/register-car')}
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
