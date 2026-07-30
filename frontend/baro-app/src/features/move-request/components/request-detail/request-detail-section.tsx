import { Text, View } from 'react-native';

import { FormErrorBanner } from '@/components/ui';

import { RequestInfoCard } from './request-info-card';
import { RequestPhoto } from './request-photo';
import { RequestReminderNotice } from './request-reminder-notice';
import { RequestTimeActions } from './request-time-actions';
import { styles } from './request-detail-section.styles';

type RequestDetailSectionProps = {
  photos: { imageId: number; imageUrl: string }[];
  summaryTitle: string;
  reasonQuote: string;
  violationType: string;
  plateNumber: string;
  location: string;
  // 이미 응답한 요청을 "상세 보기"로 열람할 때는 안내 문구/응답 버튼을 뺀다.
  showActions: boolean;
  reminderMessage: string;
  submitError?: string;
  actionsDisabled: boolean;
  onPressImmediate: () => void;
  onPress30Min: () => void;
  onPress60Min: () => void;
  onPressDecline: () => void;
};

// E-11: 이동 요청 상세 화면 본문 (사진 + 사유/위반정보 + 응답 액션)
export function RequestDetailSection({
  photos,
  summaryTitle,
  reasonQuote,
  violationType,
  plateNumber,
  location,
  showActions,
  reminderMessage,
  submitError,
  actionsDisabled,
  onPressImmediate,
  onPress30Min,
  onPress60Min,
  onPressDecline,
}: RequestDetailSectionProps) {
  return (
    <>
      <RequestPhoto photos={photos} />

      <View style={styles.mainCard}>
        <View style={styles.summary}>
          <Text style={styles.summaryTitle}>{summaryTitle}</Text>
          <Text style={styles.summaryReason}>{reasonQuote}</Text>
        </View>

        <RequestInfoCard violationType={violationType} plateNumber={plateNumber} location={location} />

        {showActions ? (
          <>
            <RequestReminderNotice message={reminderMessage} />

            {submitError ? <FormErrorBanner message={submitError} /> : null}

            <RequestTimeActions
              disabled={actionsDisabled}
              onPressImmediate={onPressImmediate}
              onPress30Min={onPress30Min}
              onPress60Min={onPress60Min}
              onPressDecline={onPressDecline}
            />
          </>
        ) : null}
      </View>
    </>
  );
}
