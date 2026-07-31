import { router, useLocalSearchParams } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import {
  AppButton,
  FormErrorBanner,
  ResponsiveContainer,
  Screen,
  ScreenHeader,
  Stack,
} from '@/components/ui';
import { Palette, Spacing } from '@/styles';

import { HouseholdCarForm } from '../components/registration/household-car-form';
import { RegisterCarConfirmView } from '../components/registration/register-car-confirm-view';
import { RegisterCarLoadingView } from '../components/registration/register-car-loading-view';
import { RegisterCarVisitDatePickerModal } from '../components/registration/register-car-visit-date-picker-modal';
import { VisitorCarForm } from '../components/registration/visitor-car-form';
import { useRegisterCarForm } from '../hooks/use-register-car-form';
import type { RegisterCarStep } from '../types/register-car';
import { parseVisitDateString } from '../validation/register-car';

import { styles } from './register-car-screen.styles';

const HEADER_TITLE: Record<RegisterCarStep, string> = {
  household: '차량 등록',
  visitor: '차량 등록',
  confirm: '등록 정보 확인',
};

export default function RegisterCarScreen() {
  // 홈 화면 "방문 등록"에서 들어오면 ?carType=visitor로 넘어와서 방문 차량 입력부터 바로 시작한다.
  const { carType: carTypeParam } = useLocalSearchParams<{ carType?: string }>();
  const initialCarType = carTypeParam === 'visitor' ? 'visitor' : 'household';

  const handleRegistrationSuccess = () => {
    // 등록 완료 후 내 차량 관리 화면으로 돌아간다. 등록 화면은 back stack에 남기지 않는다.
    router.replace('/resident/vehicles');
  };

  const registerCar = useRegisterCarForm(handleRegistrationSuccess, initialCarType);
  const { step, isRegistering } = registerCar;

  const handleBack = () => {
    if (step === 'confirm') {
      registerCar.goToInputStep();
      return;
    }
    // 세대 차량에서 직접 넘어온 경우에만 "뒤로"가 세대 차량으로 돌아간다. 방문 등록으로 바로
    // 들어온 경우엔 방문 화면이 시작점이니, 뒤로가기는 홈으로 나가는 게 맞다.
    if (step === 'visitor' && initialCarType === 'household') {
      registerCar.selectCarType('household');
      return;
    }
    router.back();
  };

  return (
    <View style={styles.flex}>
      <Screen
        scroll
        avoidKeyboard
        backgroundColor={Palette.gray50}
        edges={['top', 'right', 'left']}
        contentContainerStyle={styles.content}
      >
        <ResponsiveContainer>
          <Stack>
            <ScreenHeader title={HEADER_TITLE[step]} onBack={handleBack} />

            <Stack gap={Spacing.xl}>
              {step === 'household' && (
                <HouseholdCarForm
                  carType={registerCar.carType}
                  onChangeCarType={registerCar.selectCarType}
                  values={registerCar.householdValues}
                  onChange={registerCar.changeHouseholdValue}
                />
              )}

              {step === 'visitor' && (
                <VisitorCarForm
                  carType={registerCar.carType}
                  onChangeCarType={registerCar.selectCarType}
                  values={registerCar.visitorValues}
                  onChange={registerCar.changeVisitorValue}
                  onOpenVisitDatePicker={registerCar.openVisitDatePicker}
                />
              )}

              {step === 'confirm' && (
                <RegisterCarConfirmView
                  carType={registerCar.carType}
                  household={registerCar.householdValues}
                  visitor={registerCar.visitorValues}
                  isRegistering={isRegistering}
                  onConfirm={registerCar.handleCompleteRegistration}
                  onEdit={registerCar.goToInputStep}
                />
              )}

              {registerCar.errorMessage ? (
                <FormErrorBanner message={registerCar.errorMessage} />
              ) : null}

              {step !== 'confirm' && (
                <AppButton
                  label="차량 등록"
                  variant="neutral"
                  size="lg"
                  fullWidth
                  disabled={!registerCar.canSubmitStep}
                  onPress={registerCar.goToConfirm}
                />
              )}
            </Stack>
          </Stack>
        </ResponsiveContainer>
      </Screen>

      {isRegistering ? (
        <View style={StyleSheet.absoluteFill}>
          <RegisterCarLoadingView />
        </View>
      ) : null}

      <RegisterCarVisitDatePickerModal
        visible={registerCar.isVisitDatePickerOpen}
        selectedDate={parseVisitDateString(registerCar.visitorValues.visitDate)}
        onSelectDate={registerCar.selectVisitDate}
        onClose={registerCar.closeVisitDatePicker}
      />
    </View>
  );
}
