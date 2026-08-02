import { Text, View } from 'react-native';

import { FormErrorBanner } from '@/components/ui';

import { RequestInfoCard } from './request-info-card';
import { RequestPhoto } from './request-photo';
import { RequestReminderNotice } from './request-reminder-notice';
import { RequestTimeActions } from './request-time-actions';
import { styles } from './request-detail-section.styles';

const AUTO_ESCALATION_EMPHASIS = '5분 후 관리자에게 신고 데이터가 자동 전송됩니다.';
const AUTO_ESCALATION_MESSAGE = '전송 이후에는 취소할 수 없으며, 관리자가 확인 후 일괄 신고합니다.';

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
  // showActions가 false일 때만 쓰인다. 응답 버튼 자리에 대신 보여줄 안내(예: 관리사무소 전달 안내).
  noticeMessage?: string;
  // 충전구역 초과 점유/장애인 구역 위반: AI가 자동 감지해서 응답을 받을 사람이 없다.
  // showActions가 true여도 응답 버튼 대신 경과 시간 + 자동 전송 경고만 보여준다.
  isAutoEscalation?: boolean;
  occupancyElapsedLabel?: string;
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
  noticeMessage,
  isAutoEscalation,
  occupancyElapsedLabel,
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

        {showActions && isAutoEscalation ? (
          <View style={styles.autoEscalation}>
            <View style={styles.timerRow}>
              <Text style={styles.label}>경과 시간</Text>
              <Text style={styles.timerValue}>{occupancyElapsedLabel ?? '00:00'}</Text>
            </View>
            <RequestReminderNotice
              tone="danger"
              emphasis={AUTO_ESCALATION_EMPHASIS}
              message={AUTO_ESCALATION_MESSAGE}
            />
          </View>
        ) : showActions ? (
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
        ) : noticeMessage ? (
          <RequestReminderNotice message={noticeMessage} />
        ) : null}
      </View>
    </>
  );
}
