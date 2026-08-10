import { useMemo, useState } from 'react';
import { ScrollView, View } from 'react-native';

import type { ParkingSession } from '../api/types';
import { pickPrimarySession, toVehicleStatusDisplay } from '../utils/parking-session';

import { styles } from './vehicle-status-carousel.styles';
import { VehicleStatusCard } from './vehicle-status-card';

type VehicleStatusCarouselProps = {
  sessions: ParkingSession[];
  isLoading?: boolean;
  hasError?: boolean;
};

export function VehicleStatusCarousel({
  sessions,
  isLoading = false,
  hasError = false,
}: VehicleStatusCarouselProps) {
  const [pageWidth, setPageWidth] = useState(0);
  const orderedSessions = useMemo(() => {
    const primarySession = pickPrimarySession(sessions);
    if (!primarySession) return [];

    return [
      primarySession,
      ...sessions.filter((session) => session.sessionId !== primarySession.sessionId),
    ];
  }, [sessions]);

  if (isLoading || hasError || orderedSessions.length === 0) {
    return (
      <VehicleStatusCard
        session={null}
        isLoading={isLoading}
        hasError={hasError}
      />
    );
  }

  if (orderedSessions.length === 1) {
    return <VehicleStatusCard session={toVehicleStatusDisplay(orderedSessions[0])} />;
  }

  const totalCount = orderedSessions.length;

  return (
    <View
      style={styles.container}
      onLayout={(event) => setPageWidth(event.nativeEvent.layout.width)}
    >
      {pageWidth > 0 ? (
        <ScrollView
          horizontal
          pagingEnabled
          directionalLockEnabled
          nestedScrollEnabled
          showsHorizontalScrollIndicator={false}
          style={styles.scroll}
        >
          {orderedSessions.map((session, index) => (
            <View
              key={session.sessionId}
              style={[styles.page, { width: pageWidth }]}
              accessibilityLabel={`주차 차량 ${index + 1}/${totalCount}`}
            >
              <VehicleStatusCard
                session={toVehicleStatusDisplay(session)}
                pageLabel={`${index + 1}/${totalCount}`}
                contained
              />
            </View>
          ))}
        </ScrollView>
      ) : (
        <VehicleStatusCard session={toVehicleStatusDisplay(orderedSessions[0])} />
      )}
    </View>
  );
}
