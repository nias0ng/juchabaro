/**
 * ⚠️ TEMP PREVIEW — 삭제 예정 파일.
 *
 * MainIcon / BackButton / BottomNavBar / Screen(header, bottomBar)를 Figma와 육안 비교하기 위한
 * 임시 확인용 라우트다. 실제 화면과 연결되어 있지 않으며, 검증이 끝나면 이 파일을 삭제해도 된다.
 * (docs/superpowers/specs/2026-07-30-global-shared-components-design.md 참고)
 */
import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { BackButton, BottomNavBar, DEFAULT_NAV_ITEMS, MainIcon, Screen, Stack, ThemedText } from '@/components/ui';

export default function DevPreviewGlobalComponentsScreen() {
  const [activeKey, setActiveKey] = useState(DEFAULT_NAV_ITEMS[0].key);

  return (
    <Screen
      scroll
      header={
        <View style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8 }}>
          <BackButton onPress={() => router.back()} />
          <ThemedText type="subtitle">임시 프리뷰 (삭제 예정)</ThemedText>
        </View>
      }
      bottomBar={
        <BottomNavBar
          items={DEFAULT_NAV_ITEMS.map((item, index) => ({ ...item, badge: index === 3 }))}
          activeKey={activeKey}
          onPressItem={setActiveKey}
        />
      }
    >
      <Stack gap={24} style={{ padding: 16, alignItems: 'center' }}>
        <ThemedText type="title">MainIcon</ThemedText>
        <Stack direction="row" gap={16} style={{ alignItems: 'center' }}>
          <MainIcon size={48} />
          <MainIcon />
          <MainIcon size={128} />
        </Stack>
      </Stack>
    </Screen>
  );
}
