ALTER TABLE vehicles DROP INDEX plate_number;
CREATE INDEX idx_vehicles_plate_number ON vehicles (plate_number);