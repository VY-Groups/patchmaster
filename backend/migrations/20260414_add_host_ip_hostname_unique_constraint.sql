-- Migration: Add unique constraint on hosts (ip, hostname) to prevent duplicates
-- Date: 2026-04-14
-- Description: Prevents multiple hosts with the same IP and hostname from being created

-- First, remove any existing duplicate hosts (keep the most recently updated one)
WITH duplicates AS (
    SELECT 
        id,
        ip,
        hostname,
        ROW_NUMBER() OVER (
            PARTITION BY ip, hostname 
            ORDER BY 
                CASE WHEN is_online THEN 1 ELSE 0 END DESC,
                updated_at DESC NULLS LAST,
                last_heartbeat DESC NULLS LAST,
                created_at DESC
        ) as rn
    FROM hosts
    WHERE ip IS NOT NULL AND hostname IS NOT NULL
)
DELETE FROM hosts
WHERE id IN (
    SELECT id FROM duplicates WHERE rn > 1
);

-- Add the unique constraint (drop first: the models declare the same
-- constraint, so create_all has often already created it)
ALTER TABLE hosts
DROP CONSTRAINT IF EXISTS uq_hosts_ip_hostname;

ALTER TABLE hosts 
ADD CONSTRAINT uq_hosts_ip_hostname 
UNIQUE (ip, hostname);

-- Add comment for documentation
COMMENT ON CONSTRAINT uq_hosts_ip_hostname ON hosts IS 
'Ensures each combination of IP address and hostname is unique to prevent duplicate host entries';
