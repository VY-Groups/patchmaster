-- Performance optimization indexes for PatchMaster 2.0.14
-- Addresses ISSUE-007 and ISSUE-008 from QA testing

-- ISSUE-007: Add index for dashboard top_vulnerable query
-- This query orders by cve_count DESC, so we need a descending index
CREATE INDEX IF NOT EXISTS idx_hosts_cve_count_desc ON hosts (cve_count DESC);

-- ISSUE-008: Add trigram indexes for global search ILIKE queries
-- These indexes enable fast pattern matching for hostname, IP, and OS searches
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_hosts_hostname_trgm ON hosts USING gin (hostname gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_hosts_ip_trgm ON hosts USING gin (ip gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_hosts_os_trgm ON hosts USING gin (os gin_trgm_ops);

-- Additional index for online status filtering (used in dashboard and host lists)
CREATE INDEX IF NOT EXISTS idx_hosts_is_online ON hosts (is_online);

-- Index for reboot_required filtering (used in dashboard)
CREATE INDEX IF NOT EXISTS idx_hosts_reboot_required ON hosts (reboot_required);

-- Composite index for CVE queries (severity + status)
-- (the table is host_cves; host_cve was a stale name that made this script fail)
CREATE INDEX IF NOT EXISTS idx_host_cve_status_severity ON host_cves (status, cve_id);

-- Index for job status queries (used frequently in job lists and dashboard)
CREATE INDEX IF NOT EXISTS idx_patch_jobs_status_created ON patch_jobs (status, created_at DESC);

-- Index for job host lookups
CREATE INDEX IF NOT EXISTS idx_patch_jobs_host_id ON patch_jobs (host_id);

-- Comments for documentation
COMMENT ON INDEX idx_hosts_cve_count_desc IS 'Optimizes dashboard top_vulnerable query (ISSUE-007)';
COMMENT ON INDEX idx_hosts_hostname_trgm IS 'Enables fast ILIKE pattern matching for hostname search (ISSUE-008)';
COMMENT ON INDEX idx_hosts_ip_trgm IS 'Enables fast ILIKE pattern matching for IP search (ISSUE-008)';
COMMENT ON INDEX idx_hosts_os_trgm IS 'Enables fast ILIKE pattern matching for OS search (ISSUE-008)';
