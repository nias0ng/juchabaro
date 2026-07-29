import { useCallback, useMemo, useState } from 'react';
import { Keyboard } from 'react-native';

import { useAuth } from '@/providers/auth-provider';
import { ApiError } from '@/services/api-error';

import { registerVehicle } from '../api/vehicle-api';
import type {
  HouseholdCarFormValues,
  RegisterCarStep,
  RegisterCarType,
  VisitorCarFormValues,
} from '../types/register-car';
import { isHouseholdCarFormValid, isVisitorCarFormValid, toVisitDateString } from '../validation/register-car';

const INITIAL_HOUSEHOLD_VALUES: HouseholdCarFormValues = {
  plateNumber: '',
  carModel: '',
  isElectric: false,
  isDisabled: false,
};

const INITIAL_VISITOR_VALUES: VisitorCarFormValues = {
  plateNumber: '',
  visitDate: '',
  isElectric: false,
  isDisabled: false,
};

/**
 * 차량 등록 화면(G-01~G-03)의 입력값과 단계 이동, 등록 완료 처리(G-04)를 함께 관리한다.
 * 화면 이동(성공 시 어디로 갈지)은 onRegistered로 주입받아 화면 쪽에서 결정한다.
 */
export function useRegisterCarForm(onRegistered: () => void) {
  const { accessToken } = useAuth();

  const [step, setStep] = useState<RegisterCarStep>('household');
  const [carType, setCarType] = useState<RegisterCarType>('household');
  const [householdValues, setHouseholdValues] = useState(INITIAL_HOUSEHOLD_VALUES);
  const [visitorValues, setVisitorValues] = useState(INITIAL_VISITOR_VALUES);
  const [isRegistering, setIsRegistering] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>();
  const [isVisitDatePickerOpen, setIsVisitDatePickerOpen] = useState(false);

  const canSubmitStep = useMemo(() => {
    if (step === 'household') return isHouseholdCarFormValid(householdValues);
    if (step === 'visitor') return isVisitorCarFormValid(visitorValues);
    return true;
  }, [step, householdValues, visitorValues]);

  const changeHouseholdValue = useCallback(
    <K extends keyof HouseholdCarFormValues>(key: K, value: HouseholdCarFormValues[K]) => {
      setHouseholdValues((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const changeVisitorValue = useCallback(
    <K extends keyof VisitorCarFormValues>(key: K, value: VisitorCarFormValues[K]) => {
      setVisitorValues((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  /** 같은 필드를 여러 번 눌러도 picker가 중복으로 열리지 않게 막고, 열려있던 키보드는 먼저 닫는다. */
  const openVisitDatePicker = useCallback(() => {
    setIsVisitDatePickerOpen((prev) => {
      if (prev) return prev;
      Keyboard.dismiss();
      return true;
    });
  }, []);

  /** "닫기"로 취소할 때만 쓰인다. 값은 그대로 두고 picker만 닫는다. */
  const closeVisitDatePicker = useCallback(() => {
    setIsVisitDatePickerOpen(false);
  }, []);

  /** 캘린더에서 날짜를 탭했을 때 호출된다. 값 반영과 picker 닫기를 함께 처리한다. */
  const selectVisitDate = useCallback((date: Date) => {
    setVisitorValues((prev) => ({ ...prev, visitDate: toVisitDateString(date) }));
    setIsVisitDatePickerOpen(false);
  }, []);

  const selectCarType = useCallback((type: RegisterCarType) => {
    setErrorMessage(undefined);
    setCarType(type);
    setStep(type);
  }, []);

  const goToConfirm = useCallback(() => {
    if (!canSubmitStep) return;
    setErrorMessage(undefined);
    setStep('confirm');
  }, [canSubmitStep]);

  /** 확인 단계에서 뒤로 가거나 "수정하기"를 누르면 직전에 입력하던 차량 성격 화면으로 돌아간다. */
  const goToInputStep = useCallback(() => {
    setErrorMessage(undefined);
    setStep(carType);
  }, [carType]);

  const handleCompleteRegistration = useCallback(async () => {
    if (isRegistering) return;

    setErrorMessage(undefined);
    setIsRegistering(true);

    try {
      if (carType === 'household') {
        await registerVehicle(
          {
            ownerType: 'RESIDENT',
            plateNumber: householdValues.plateNumber,
            carModel: householdValues.carModel,
            isElectric: householdValues.isElectric,
            isDisabled: householdValues.isDisabled,
          },
          accessToken ?? undefined,
        );
      } else {
        await registerVehicle(
          {
            ownerType: 'VISITOR',
            plateNumber: visitorValues.plateNumber,
            visitDate: visitorValues.visitDate,
            isElectric: visitorValues.isElectric,
            isDisabled: visitorValues.isDisabled,
          },
          accessToken ?? undefined,
        );
      }

      onRegistered();
    } catch (error) {
      setErrorMessage(error instanceof ApiError ? error.message : '차량 등록에 실패했습니다.');
    } finally {
      setIsRegistering(false);
    }
  }, [isRegistering, carType, householdValues, visitorValues, accessToken, onRegistered]);

  return {
    step,
    carType,
    householdValues,
    visitorValues,
    isRegistering,
    errorMessage,
    canSubmitStep,
    isVisitDatePickerOpen,
    changeHouseholdValue,
    changeVisitorValue,
    selectCarType,
    goToConfirm,
    goToInputStep,
    openVisitDatePicker,
    closeVisitDatePicker,
    selectVisitDate,
    handleCompleteRegistration,
  };
}

export type RegisterCarFormController = ReturnType<typeof useRegisterCarForm>;
