-- Preserve historical acquisition values while adopting the new vocabulary.
CREATE TABLE layout_location(name TEXT PRIMARY KEY);
INSERT INTO layout_location VALUES
 ('main_west_1'),('main_west_2'),('main_east_1'),('main_east_2'),
 ('main_north_1'),('main_north_2'),('main_south_1'),('main_south_2'),
 ('yard_west_1'),('yard_west_2'),('yard_west_3'),('yard_west_4'),
 ('yard_south_1'),('yard_south_2'),('yard_south_3'),('yard_south_4'),
 ('park_1'),('park_2'),('test_main_1'),('test_prog_1');

CREATE TABLE lifecycle_v2 (
 asset_id TEXT PRIMARY KEY REFERENCES asset(id),
 possession TEXT NOT NULL CHECK(possession IN ('planned','ordered','shipped','sheltered','received')),
 status TEXT CHECK(status IN ('stored','active','parked','maintenance','retired')),
 location TEXT REFERENCES layout_location(name),
 ordered_on TEXT, shipped_on TEXT, received_on TEXT, retired_on TEXT,
 revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
 acquisition TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(acquisition)),
 CHECK((possession='received' AND status IS NOT NULL) OR (possession!='received' AND status IS NULL)),
 CHECK(status NOT IN ('active','parked') OR location IS NOT NULL),
 CHECK((status IS 'retired') = (retired_on IS NOT NULL))
);
INSERT INTO lifecycle_v2
 SELECT asset_id,
 CASE WHEN possession IN ('parked','missed') THEN 'sheltered' ELSE possession END,
 CASE WHEN status='active' AND (location IS NULL OR location NOT IN (SELECT name FROM layout_location)) THEN 'stored' ELSE status END,
 CASE WHEN location IN (SELECT name FROM layout_location) THEN location ELSE NULL END,
 ordered_on,shipped_on,received_on,retired_on,revision+1,updated_at,
 CASE WHEN location IS NOT NULL AND location NOT IN (SELECT name FROM layout_location)
      THEN json_set(acquisition,'$.legacy_location',location,'$.legacy_possession',possession,'$.legacy_status',status)
      WHEN possession IN ('parked','missed') THEN json_set(acquisition,'$.legacy_possession',possession)
      ELSE acquisition END
 FROM lifecycle;
DROP TABLE lifecycle;
ALTER TABLE lifecycle_v2 RENAME TO lifecycle;
UPDATE asset SET revision=revision+1;
PRAGMA user_version=2;
