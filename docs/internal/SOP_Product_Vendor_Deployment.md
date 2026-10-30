# Patch-SecOps Solution Product And Vendor Deployment SOP

## Purpose
This document defines the exact deployment order for:
- Patch-SecOps Solution Product
- Patch-SecOps Solution Vendor Portal

It also defines how to handle private license authority files safely.

## Version
- Release version: `2.0.0`

## Required Build Artifacts
Use only these 2 deployable tarballs:

1. Product tarball  
   `dist/patchmaster-product-2.0.0.tar.gz`
2. Vendor tarball  
   `vendor/dist/patchmaster-vendor-2.0.0.tar.gz`

## Internal Backup Files
These files are internal only and must be stored securely:

- `dist/private/patchmaster-license-authority.env`
- `dist/private/patchmaster-license-authority-2.0.0.env`
- `dist/private/patchmaster-license-public.env`
- `dist/private/patchmaster-license-public-2.0.0.env`

## Important Rules
- Do not give `patchmaster-license-authority.env` to customers.
- Do not deploy from `dist/private` directly.
- Do not unpack internal private files into customer-facing delivery bundles.
- Patch-SecOps Solution customer installs must use the product tarball only.
- Vendor installs must use the vendor tarball only.
- Keep `dist/private` only for backup, rebuild continuity, and disaster recovery.

## Deployment Order

### 1. Deploy Patch-SecOps Solution Product On Customer Server
Copy `patchmaster-product-2.0.0.tar.gz` to the customer server.

Run:

```bash
cd /home/patchmaster
tar -xzf patchmaster-product-2.0.0.tar.gz
cd patchmaster-product-2.0.0/packaging
./install-bare.sh --with-monitoring
```

Verify:

```bash
systemctl status patchmaster-backend --no-pager -n 20
systemctl status nginx --no-pager -n 20
```

Open in browser:

```text
http://<server-ip>/
```

### 2. Deploy Vendor Portal On Vendor Server
Copy `patchmaster-vendor-2.0.0.tar.gz` to the vendor server.

Run:

```bash
cd /opt
tar -xzf patchmaster-vendor-2.0.0.tar.gz
cd patchmaster-vendor-2.0.0
./install-vendor.sh
```

Verify:

```bash
systemctl status patchmaster-vendor --no-pager -n 20
systemctl status nginx --no-pager -n 20
```

## License Workflow

### 3. Create Testing Or POC License In Vendor Portal
- Create the customer record in Vendor Portal.
- Generate a testing or POC license first.
- Share that testing key with the customer.

### 4. Customer Activates Testing License In Patch-SecOps Solution
- Customer logs into Patch-SecOps Solution.
- Customer opens the License page.
- Customer pastes the testing license.
- Customer activates the testing license.

### 5. Customer Shares Verified Hardware Or MAC ID
- After testing is complete, the customer shares the final verified hardware or MAC ID.
- Vendor records this identifier in Vendor Portal.

### 6. Generate Final Production License
- Vendor generates the final production license using the verified customer binding ID.
- Vendor shares the final production key with the customer.

### 7. Customer Activates Final Production License
- Customer opens the License page in Patch-SecOps Solution.
- Customer pastes the final production license.
- Customer activates it.

## What The Tarballs Already Contain

### Product Tarball
`patchmaster-product-2.0.0.tar.gz` already includes:
- product runtime files
- customer install scripts
- `patchmaster-license-public.env`

### Vendor Tarball
`patchmaster-vendor-2.0.0.tar.gz` already includes:
- vendor portal runtime files
- vendor installer
- `patchmaster-license-authority.env`

## Recovery And Rebuild Guidance
Use `dist/private` only when:
- the Vendor server must be rebuilt while keeping the same license authority
- the Product side must keep the same runtime trust material
- disaster recovery is required
- a future rebuild must preserve the same license authority set

## Final Summary
- Deploy customers with the product tarball only.
- Deploy vendors with the vendor tarball only.
- Keep `dist/private` internal and secure.
- Never share `patchmaster-license-authority.env` with customers.
