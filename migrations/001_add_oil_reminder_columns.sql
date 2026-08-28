-- 第三弾拡張①: 既存SQLite DBに一度だけ適用する。
-- 実行前に必ずDBファイルをバックアップすること。

ALTER TABLE gears
    ADD COLUMN maintenance_reminder_disabled BOOLEAN NOT NULL DEFAULT 0;

ALTER TABLE gears
    ADD COLUMN maintenance_reminder_snoozed_stage INTEGER;
