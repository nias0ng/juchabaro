import { Text, View } from 'react-native';

import { FormErrorBanner } from '@/components/ui';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { RequestInfoCard } from './request-info-card';
import { RequestPhoto } from './request-photo';
import { RequestReminderNotice } from './request-reminder-notice';
import { RequestTimeActions } from './request-time-actions';
import { createStyles } from './request-detail-section.styles';

const AUTO_ESCALATION_MESSAGE = '관리자에게 신고 데이터가 자동으로 전송되었습니다.';

type RequestDetailSectionProps = {
  requestId: number;
  photos: { imageId: number; imageUrl: string }[];
  summaryTitle: string;
  reasonQuote: string;
  violationType: string;
  plateNumber: string;
  location: string;
  requestedAtLabel: string;
  showActions: boolean;
  reminderMessage: string;
  noticeMessage?: string;
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
  requestId,
  photos,
  summaryTitle,
  reasonQuote,
  violationType,
  plateNumber,
  location,
  requestedAtLabel,
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
  const styles = useThemedStyles(createStyles);
  return (
    <View style={styles.root}>
      <RequestPhoto photos={photos} />

      <View style={styles.mainCard}>
        <View style={styles.summary}>
          <Text style={styles.summaryMeta}>
            #{requestId} · {requestedAtLabel}
          </Text>
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
            <RequestReminderNotice tone="danger" message={AUTO_ESCALATION_MESSAGE} />
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
    </View>
  );
}
