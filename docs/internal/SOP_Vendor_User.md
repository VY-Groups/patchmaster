# Standard Operating Procedure: Vendor Portal User

**Audience:** Vendor staff, sales, account managers, support, admins
**Purpose:** Internal operating guide for customer records, license issuance, renewals, and support handling
**Version:** 2.2.0

---

## Table of Contents
1. [Portal Overview](#1-portal-overview)
2. [License Lifecycle](#2-license-lifecycle)
3. [Managing Customers](#3-managing-customers)
4. [Special Cases](#4-special-cases)
5. [Security And Compliance](#5-security-and-compliance)

---

## 1. Portal Overview

**URL:** `https://portal.patchmaster.internal`
**Access:** Restricted to VPN or internal network.

### Dashboard Metrics
- **Active Licenses:** Total revenue-generating deployments
- **Expiring Soon:** Licenses expiring in less than 30 days
- **Recent Activity:** Audit trail of who generated, reissued, revoked, or downloaded a license

### Core Rule
Vendor records are authoritative. Customer-side activation does not automatically update the Vendor portal. Vendor staff must keep customer, entitlement, and binding records current.

---

## 2. License Lifecycle

Understanding the current licensing model is critical for correct customer support.

### Step 1: Record The Commercial Terms
Before issuing anything, confirm the Vendor record includes:
1. customer identity
2. technical contact
3. purchased plan and tier
4. host entitlement
5. expiry term
6. whether the final production license must be hardware-bound

### Step 2: Issue A Testing Or POC License First
Use a testing or POC license when:
- the customer is validating the product
- the final production license must be tied to a verified hardware or MAC ID

Testing and POC licenses are intentionally flexible:
- they activate on the customer side
- they work in offline or air-gapped environments
- they let the customer complete validation before final binding

### Step 3: Collect The Verified Binding ID
If the final production license must be hardware-bound:
1. customer activates the testing or POC license in Patch-SecOps Solution
2. customer shares the verified hardware or MAC ID with Vendor
3. Vendor staff records that value in the customer record

**Critical:** Do not generate a final bound production license until the verified binding ID is stored in Vendor.

### Step 4: Generate The Final Production License
When you click **Generate**, the system now:
1. creates the license claims payload with customer, plan, dates, features, entitlement, and binding metadata
2. signs it with the vendor private signing authority
3. encrypts it into the production-safe `PM2-...` license format

Legacy `PM1-...` support still exists for transition and recovery scenarios, but new production licenses should be `PM2`.

### Step 5: Deliver The License Securely
- Download the generated key
- Send it via encrypted email or secure file transfer
- Do not paste raw license keys into Slack, Teams, or public ticket threads

### Step 6: Customer Activation
The customer activates the key in Patch-SecOps Solution. Patch-SecOps Solution validates locally:
1. signature
2. encrypted payload integrity
3. expiry
4. host entitlement
5. hardware binding when required

Vendor public internet exposure is not required for customer-side activation or validation.

### Step 7: Expiry And Renewal
- **30 days prior:** customer sees warning state in Patch-SecOps Solution
- **0 days:** licensed operations become restricted until a valid license is activated

Renewal process:
1. open the customer profile
2. confirm renewed term, tier, and host entitlement
3. keep or update the stored hardware binding ID if needed
4. generate a new production license
5. customer activates the new license in Patch-SecOps Solution

---

## 3. Managing Customers

### Onboarding A New Client
1. Verify contract: confirm tier, plan, and host count
2. Create the customer profile:
   - legal entity name
   - technical point of contact
   - region if needed for internal operational tracking
   - notes relevant to licensing or support
3. Issue the initial license:
   - use a 30-day testing or POC license for evaluations
   - if production binding will be required later, wait for the verified hardware or MAC ID before generating the final production key

### Upgrading A Client
Scenario: customer bought 100 hosts and now needs 500.
1. Find the customer
2. Edit **Max Hosts** from 100 to 500
3. Click **Re-issue License**
4. Send the new key that matches the latest entitlement and binding requirements

### Keeping Records Accurate
Vendor must manually maintain:
- customer contacts
- plan and tier history
- hardware or MAC binding records
- renewal notes
- emergency extension notes
- reissue reasons

---

## 4. Special Cases

### Case A: Lost License Key
Customer deleted their key.
1. Open the customer profile
2. Check **License History**
3. Download the most recent active key
4. Resend it

Do not generate a new one unless entitlement or binding details changed.

### Case B: Air-Gapped Installation
Customer cannot use online activation.
- Patch-SecOps Solution licenses are offline-first
- Patch-SecOps Solution does not need to phone home to Vendor for license verification
- send the key file and let the customer activate locally

### Case C: Emergency Extension
Contract negotiation is stuck but the license expires tomorrow.
1. Generate a temporary key
2. Keep the same tier and core entitlement
3. Set the expiry to a short bridge window, for example 14 days
4. If the customer is already hardware-bound, keep the same stored binding ID
5. Send it with clear internal notes

### Case D: Final Bound Production License
Customer completed POC and sent the verified hardware or MAC ID.
1. confirm the value is recorded on the customer record
2. confirm plan, tier, host count, and expiry
3. generate the final `PM2-...` production license
4. document who verified the binding and when

---

## 5. Security And Compliance

### Audit Logs
Every action should be attributable:
- who performed it
- what action was taken
- which customer it affected
- when it happened

### Red Flags
- generating enterprise licenses for test customers without approval
- reissuing keys without updating records
- generating final bound licenses without a stored verified hardware or MAC ID
- downloading keys for accounts you do not manage

### Authority Protection
The vendor signing authority is highly sensitive.
- never place private authority files in customer bundles
- keep operator-only authority files restricted
- do not share them over chat or ticket systems

### Authority Rotation
If the license authority set is compromised:
1. DevOps rotates the authority set
2. affected customer licenses may no longer validate
3. Vendor must re-generate and re-send affected licenses immediately

This is a severe incident. Protect vendor credentials and authority files carefully.
