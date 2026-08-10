import { onMounted, onUnmounted, ref } from 'vue';

// 필터 바의 드롭다운(상태/유형/날짜 등) 여러 개 중 하나만 열려 있게 관리하고,
// 드롭다운 바깥을 클릭하면 닫히게 한다. 사건 목록·이력 관리·주차 구역 관리
// 화면이 전부 이 동작을 그대로 써서 composable로 뺐다.
export function useDropdownFilter<T extends string>() {
  const filterBarRef = ref<HTMLElement | null>(null);
  const openDropdown = ref<T | null>(null);

  function handleClickOutside(event: MouseEvent) {
    if (filterBarRef.value && !filterBarRef.value.contains(event.target as Node)) {
      openDropdown.value = null;
    }
  }

  onMounted(() => document.addEventListener('mousedown', handleClickOutside));
  onUnmounted(() => document.removeEventListener('mousedown', handleClickOutside));

  function toggleDropdown(name: T) {
    openDropdown.value = openDropdown.value === name ? null : name;
  }

  return { filterBarRef, openDropdown, toggleDropdown };
}
