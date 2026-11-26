import { router } from 'expo-router';
import { Text, View } from 'react-native';

import type { MoveResponseType } from '@/features/move-request/api/types';
import type { RequestDetailViewModel } from '@/features/move-request/hooks/use-request-detail-view-model';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './request-detail-body.styles';
import { RequestCompletedSection } from './request-completed/request-completed-section';
import { RequestDetailSection } from './request-detail/request-detail-section';
import { RequestOverdueSection } from './request-overdue/request-overdue-section';
import { RequestReminderSection } from './request-reminder/request-reminder-section';
import { RequestWaitingSection } from './request-waiting/request-waiting-section';

const SUMMARY_TITLE = '고객님의 차량 이동을\n요청드립니다';
const REQUESTER_SUMMARY_TITLE = '차량 이동을\n요청했습니다';
const REMINDER_MESSAGE = '응답이 없으면 한 시간 후에 한 번 더 알려드리고,\n그 이후에는 관리사무소로 전달합니다.';
const REQUESTER_PENDING_MESSAGE =
  '차량 소유자에게 이동 요청을 전달했습니다.\n응답이 오면 진행 상황을 알려드립니다.';
// REMINDER_SENT: 무응답으로 1차 재알림까지 나간 상태. 그래도 아직 응답은 받을 수 있다.
const REMINDER_SENT_MESSAGE = '이미 한 번 알려드렸어요.\n계속 응답이 없으면 관리사무소로 전달됩니다.';
// NEED_ADMIN: 재알림에도 계속 무응답이었거나, 사용자가 "이동 어려움"으로 응답해 관리사무소로 넘어간 상태.
const NEED_ADMIN_MESSAGE = '관리사무소로 전달되었습니다.\n확인 후 별도로 연락드릴 예정입니다.';
const ADMIN_ESCALATION_PENDING_MESSAGE =
  '마지막 재알림 후 1시간 동안 응답이 없으면\n관리사무소로 이관됩니다.';
const ADMIN_ESCALATED_MESSAGE =
  '마지막 재알림 후 1시간 동안 응답이 없어\n관리사무소로 이관되었습니다.';
const ADMIN_ESCALATED_DIRECT_MESSAGE =
  '차량 이동이 어렵다는 응답에 따라\n관리사무소로 이관되었습니다.';

type RequestDetailBodyProps = {
  vm: RequestDetailViewModel;
  statusMessage?: string;
  onPressHome: () => void;
};

// request-detail-screen이 requestStatus/파생 상태에 따라 골라 그리는 본문(E-11~E-16). 화면 하나가
// 아주 많은 상태를 가지므로, 어떤 섹션을 보여줄지 고르는 로직만 이 컴포넌트에 모아둔다.
export function RequestDetailBody({ vm, statusMessage, onPressHome }: RequestDetailBodyProps) {
  const styles = useThemedStyles(createStyles);
  const { display } = vm;

  // WILL_MOVE 응답이 성공하면 F-02(응답 완료)로 넘어간다. F-02의 10초 카운트다운이 끝나면
  // 다시 이 라우트로 돌아오는데, 그때는 requestStatus가 이미 RESPONDED라서 자동으로 E-12(대기 화면)가 그려진다.
  // CANNOT_MOVE_NOW는 F-02에 해당하는 Figma 화면이 없어 이 화면에서 바로 NEED_ADMIN 안내로 전환한다.
  const handleRespond = async (responseType: MoveResponseType, estimatedMinutes: number | null) => {
    const result = await vm.respond(responseType, estimatedMinutes);
    if (result && responseType === 'WILL_MOVE') {
      router.push({ pathname: '/resident/response-complete', params: { requestId: String(result.requestId) } });
    }
  };

  if (statusMessage || !display) {
    return (
      <View style={styles.statusContainer}>
        <Text style={styles.statusText}>{statusMessage}</Text>
      </View>
    );
  }

  if (vm.isCompleted && vm.completedDisplay) {
    return (
      <RequestCompletedSection
        endTimeLabel={vm.completedDisplay.endTimeLabel}
        durationLabel={vm.completedDisplay.durationLabel}
        timeline={vm.completedDisplay.timeline}
        onPressHome={onPressHome}
      />
    );
  }

  if (vm.showOverdueView && vm.overdueDisplay) {
    return (
      <RequestOverdueSection
        elapsedLabel={vm.countdown.elapsedLabel}
        timeline={vm.overdueDisplay.timeline}
        onPressDetail={() => vm.setShowDetail(true)}
      />
    );
  }

  if (vm.showEscalationView && vm.escalationDisplay) {
    const wasEscalatedAfterReminder = vm.escalationDisplay.escalationDueAt !== null;

    return (
      <RequestReminderSection
        badgeLabel={vm.isNeedAdmin ? '관리사무소 이관' : vm.escalationDisplay.reminderRoundLabel}
        description={
          vm.isNeedAdmin
            ? wasEscalatedAfterReminder
              ? ADMIN_ESCALATED_MESSAGE
              : ADMIN_ESCALATED_DIRECT_MESSAGE
            : ADMIN_ESCALATION_PENDING_MESSAGE
        }
        countdownLabel={
          vm.isNeedAdmin
            ? '이관 완료'
            : vm.escalationDisplay.escalationDueAt
              ? vm.escalationCountdown.label
              : '확인 중'
        }
        countdownCaption={vm.isNeedAdmin ? '관리사무소 처리 중' : '관리사무소 이관까지'}
        countdownProgress={vm.isNeedAdmin ? 1 : vm.escalationCountdown.progress}
        plateNumber={display.plateNumber}
        actionLabel={vm.isNeedAdmin ? '이관 완료' : '이관 대기'}
        timeline={vm.escalationDisplay.timeline}
        pendingStep={vm.escalationDisplay.pendingStep}
      />
    );
  }

  if (vm.showWaitingView && vm.waitingDisplay) {
    return (
      <RequestWaitingSection
        countdownLabel={vm.countdown.label}
        progress={vm.countdown.progress}
        dueTimeLabel={vm.waitingDisplay.dueTimeLabel}
        respondedTimeLabel={vm.waitingDisplay.respondedTimeLabel}
        onPressDetail={() => vm.setShowDetail(true)}
      />
    );
  }

  return (
    <RequestDetailSection
      requestId={display.requestId}
      photos={display.photos}
      summaryTitle={vm.viewMode === 'requester' ? REQUESTER_SUMMARY_TITLE : SUMMARY_TITLE}
      reasonQuote={display.reasonQuote}
      violationType={display.violationTypeLabel}
      plateNumber={display.plateNumber}
      location={display.location}
      requestedAtLabel={display.requestedAtLabel}
      showActions={vm.showResponseActions}
      reminderMessage={
        vm.viewMode === 'requester'
          ? REQUESTER_PENDING_MESSAGE
          : vm.isReminderSentNoResponse
            ? REMINDER_SENT_MESSAGE
            : REMINDER_MESSAGE
      }
      noticeMessage={vm.isNeedAdmin ? NEED_ADMIN_MESSAGE : undefined}
      isAutoEscalation={vm.isAutoEscalationType}
      occupancyElapsedLabel={vm.occupancyElapsedLabel}
      submitError={vm.submitError}
      actionsDisabled={vm.hasResponded || vm.isSubmitting}
      onPressImmediate={() => handleRespond('WILL_MOVE', 10)}
      onPress30Min={() => handleRespond('WILL_MOVE', 30)}
      onPress60Min={() => handleRespond('WILL_MOVE', 60)}
      onPressDecline={() => handleRespond('CANNOT_MOVE_NOW', null)}
    />
  );
}
