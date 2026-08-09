-- BAD_PARKING이 최초 OPEN될 때 대표 구역과 함께 고정한 추가 침범 구역을
-- 재시작 뒤에도 보존한다. Backend publication 계약에는 아직 노출하지 않는다.

ALTER TABLE incidents
ADD COLUMN related_zone_ids_payload TEXT NOT NULL DEFAULT '[]'
CHECK (
    json_valid(related_zone_ids_payload)
    AND json_type(related_zone_ids_payload) = 'array'
    AND json_array_length(related_zone_ids_payload) <= 2
    AND (
        json_array_length(related_zone_ids_payload) = 0
        OR zone_id IS NOT NULL
    )
);
