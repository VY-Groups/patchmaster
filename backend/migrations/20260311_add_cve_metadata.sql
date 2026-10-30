ALTER TABLE cves ADD COLUMN IF NOT EXISTS cwe_id VARCHAR(50) DEFAULT '';
-- "references" is a reserved word in Postgres, hence the quoting
ALTER TABLE cves ADD COLUMN IF NOT EXISTS "references" TEXT DEFAULT '';
ALTER TABLE cves ADD COLUMN IF NOT EXISTS affected_products TEXT DEFAULT '';
ALTER TABLE cves ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'manual';
