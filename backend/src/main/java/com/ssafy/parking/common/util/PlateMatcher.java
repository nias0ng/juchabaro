package com.ssafy.parking.common.util;

public final class PlateMatcher {

    private PlateMatcher() {}

    /** 공백·구분자 제거 (숫자/영문/한글만 남김) */
    public static String normalize(String s) {
        return (s == null) ? "" : s.replaceAll("[^0-9A-Za-z가-힣]", "");
    }

    /** Levenshtein 편집거리 */
    public static int distance(String a, String b) {
        int[] prev = new int[b.length() + 1];
        int[] curr = new int[b.length() + 1];
        for (int j = 0; j <= b.length(); j++) prev[j] = j;
        for (int i = 1; i <= a.length(); i++) {
            curr[0] = i;
            for (int j = 1; j <= b.length(); j++) {
                int cost = (a.charAt(i - 1) == b.charAt(j - 1)) ? 0 : 1;
                curr[j] = Math.min(Math.min(curr[j - 1] + 1, prev[j] + 1), prev[j - 1] + cost);
            }
            int[] tmp = prev; prev = curr; curr = tmp;
        }
        return prev[b.length()];
    }
}