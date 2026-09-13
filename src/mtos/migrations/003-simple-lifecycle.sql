INSERT OR IGNORE INTO layout_location VALUES ('off_track');

CREATE TABLE lifecycle_v3 (
 asset_id TEXT PRIMARY KEY REFERENCES asset(id),
 possession TEXT NOT NULL CHECK(possession IN ('planned','ordered','shipped','sheltered','received')),
 status TEXT NOT NULL CHECK(status IN ('unavailable','stored','active','parked','maintenance','retired')),
 location TEXT NOT NULL REFERENCES layout_location(name), purchased_on TEXT,
 revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
 acquisition TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(acquisition)),
 CHECK(possession='received' OR status='unavailable'),
 CHECK(status NOT IN ('active','parked') OR location!='off_track')
);
INSERT INTO lifecycle_v3
 SELECT asset_id, possession, COALESCE(status,'unavailable'),
        COALESCE(location,'off_track'),
        CASE WHEN json_extract(acquisition,'$.acquired') GLOB '????-??-??'
             THEN json_extract(acquisition,'$.acquired') ELSE NULL END,
        revision+1, updated_at,
        json_patch(acquisition, json_object(
          'legacy_ordered_on',ordered_on, 'legacy_shipped_on',shipped_on,
          'legacy_received_on',received_on, 'legacy_retired_on',retired_on))
 FROM lifecycle;
DROP TABLE lifecycle;
ALTER TABLE lifecycle_v3 RENAME TO lifecycle;

CREATE TABLE media_v3 (
 asset_id TEXT NOT NULL REFERENCES asset(id), sequence INTEGER NOT NULL CHECK(sequence >= 1),
 filename TEXT NOT NULL, sha256 TEXT NOT NULL, width INTEGER NOT NULL,
 height INTEGER NOT NULL, size_bytes INTEGER NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(asset_id,sequence), UNIQUE(asset_id,filename)
);
INSERT INTO media_v3(asset_id,sequence,filename,sha256,width,height,size_bytes,created_at)
 SELECT asset_id,sequence,filename,sha256,width,height,size_bytes,created_at FROM media;
DROP TABLE media;
ALTER TABLE media_v3 RENAME TO media;
UPDATE asset SET revision=revision+1;
PRAGMA user_version=3;
