import { usePushTokenRegistration } from '@/features/notification/hooks/use-push-token-registration';

export function PushTokenRegistrar() {
  usePushTokenRegistration();
  return null;
}
