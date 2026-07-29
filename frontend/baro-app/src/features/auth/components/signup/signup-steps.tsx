import type { SignupFormController } from '../../hooks/use-signup-form';

import { SignupAccountForm } from './signup-account-form';
import { SignupCompleteView } from './signup-complete-view';
import { SignupConfirmForm } from './signup-confirm-form';
import { SignupHouseholdForm } from './signup-household-form';

type SignupStepsProps = {
  signup: SignupFormController;
  onRegisterVehicle: () => void;
  onGoHome: () => void;
};

/* 단계에 맞게 입력 폼 렌더링 함 */
export function SignupSteps({ signup, onRegisterVehicle, onGoHome }: SignupStepsProps) {
  const {
    step,
    complexName,
    accountValues,
    householdValues,
    confirmValues,
    changeAccountValue,
    changeHouseholdValue,
    changeConfirmValue,
    goToStep,
  } = signup;

  if (step === 1) {
    return <SignupAccountForm values={accountValues} onChange={changeAccountValue} />;
  }

  if (step === 2) {
    return (
      <SignupHouseholdForm
        complexName={complexName}
        values={householdValues}
        onChange={changeHouseholdValue}
      />
    );
  }

  if (step === 3) {
    return (
      <SignupConfirmForm
        account={accountValues}
        household={householdValues}
        complexName={complexName}
        values={confirmValues}
        onChange={changeConfirmValue}
        onEditAccount={() => goToStep(1)}
        onEditHousehold={() => goToStep(2)}
      />
    );
  }

  return (
    <SignupCompleteView
      account={accountValues}
      household={householdValues}
      complexName={complexName}
      onRegisterVehicle={onRegisterVehicle}
      onGoHome={onGoHome}
    />
  );
}
