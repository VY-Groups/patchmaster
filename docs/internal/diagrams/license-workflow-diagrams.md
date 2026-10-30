# Patch-SecOps Solution Internal License And Release Architecture

## 1. Build And Artifact Flow

```mermaid
flowchart TD
    A["Run build_release.py / build-stable.sh"] --> B["Generate or reuse license authority set<br/>Ed25519 signing + X25519 encryption"]
    B --> C["Write internal recovery copy<br/>dist/private/patchmaster-license-authority.env"]
    B --> D["Write internal product runtime copy<br/>dist/private/patchmaster-license-public.env"]
    D --> E["Bundle runtime verification and decryption material<br/>inside customer product tarball"]
    C --> F["Bundle private authority inside vendor tarball"]
    A --> G["Export developer folder<br/>dist/developer/patchmaster-developer-kit-2.0.0/"]
```

## 2. What Goes Where

```mermaid
flowchart LR
    A["Customer Product Tarball"] --> B["patchmaster-product-2.0.0.tar.gz<br/>includes runtime license bundle only"]
    C["Vendor Tarball"] --> D["patchmaster-vendor-2.0.0.tar.gz<br/>includes private authority bundle"]
    E["Internal Recovery Files"] --> F["dist/private/<br/>runtime + authority recovery copies"]

    B --> G["Patch-SecOps Solution Server"]
    D --> H["Vendor Server"]
    F --> I["Operator secure storage"]
```

## 3. Patch-SecOps Solution Install Flow

```mermaid
flowchart TD
    A["Operator copies customer product tarball"] --> B["Extract patchmaster-product-2.0.0.tar.gz"]
    B --> C["Run packaging/install-bare.sh"]
    C --> D["Installer reads bundled patchmaster-license-public.env"]
    D --> E["Writes LICENSE_VERIFY_PUBLIC_KEY + LICENSE_DECRYPT_PRIVATE_KEY<br/>into Patch-SecOps Solution env"]
    E --> F["Patch-SecOps Solution verifies and decrypts licenses locally"]
```

## 4. Vendor Install Flow

```mermaid
flowchart TD
    A["Operator copies vendor tarball"] --> B["Extract patchmaster-vendor-2.0.0.tar.gz"]
    B --> C["Run install-vendor.sh"]
    C --> D["Installer reads bundled patchmaster-license-authority.env"]
    D --> E["Writes LICENSE_SIGN_PRIVATE_KEY + LICENSE_ENCRYPT_PUBLIC_KEY<br/>into Vendor env"]
    E --> F["Writes matching runtime compatibility keys into Vendor env"]
    F --> G["Vendor can generate PM2 licenses"]
```

## 5. Runtime License Flow

```mermaid
flowchart LR
    A["Vendor records customer and purchase"] --> B["Issue POC or testing license"]
    B --> C["Customer activates testing license in Patch-SecOps Solution"]
    C --> D["Customer shares verified hardware or MAC ID with Vendor"]
    D --> E["Vendor updates customer record with final binding ID"]
    E --> F["Vendor generates final bound PM2 license"]
    F --> G["Customer activates final PM2 in Patch-SecOps Solution"]
    H["Patch-SecOps Solution runtime license bundle"] --> I["Verify Ed25519 signature and decrypt claims locally"]
    G --> I
    I -->|Valid| J["License accepted"]
    I -->|Invalid| K["Signature, decrypt, or binding validation failed"]
```

### Runtime Clarification
- Patch-SecOps Solution verifies and decrypts the license locally with its bundled runtime license material.
- Customer POC or testing happens on the customer side before the final bound license is generated.
- Vendor records the customer hardware or MAC ID in the Vendor portal and uses that stored binding ID for final license generation.
- Vendor public internet exposure is not required for Patch-SecOps Solution license verification.

## 6. Trust Boundary

```mermaid
flowchart TD
    A["Customer Product Tarball"] --> B["Contains runtime verification and decryption bundle only"]
    C["Vendor Tarball"] --> D["Contains private signing authority"]
    E["dist/private copies"] --> F["Recovery only, never customer-facing"]
    B --> G["Customer cannot mint licenses from product package"]
    D --> H["Only vendor side can mint new valid licenses"]
```

## 7. Safe Usage Rule

```mermaid
flowchart TD
    A["Need Vendor and Patch-SecOps Solution to work together"] --> B["Use product and vendor packages that share the same license authority set"]
    B --> C["Vendor signs with the matching private key"]
    B --> D["Patch-SecOps Solution verifies and decrypts with the matching runtime bundle"]
    C --> E["New PM2 licenses validate correctly"]
    D --> E
```

## 8. Transition Compatibility

```mermaid
flowchart TD
    A["Old HMAC / shared-secret licenses"] --> B["Still supported as fallback"]
    C["Legacy PM1 signed licenses"] --> D["Still readable during transition"]
    E["New licenses"] --> F["Use PM2 encrypted + signed format"]
    B --> G["Transition compatibility path"]
    D --> G
    F --> H["Preferred production path"]
```

## Internal Operator Instructions

### Recommended Internal Deployment
1. Build artifacts with `bash scripts/build-stable.sh`
2. Keep `dist/private/patchmaster-license-authority.env` private
3. Deliver `dist/patchmaster-product-2.0.0.tar.gz` to the Patch-SecOps Solution server
4. Deliver `vendor/dist/patchmaster-vendor-2.0.0.tar.gz` to the Vendor server
5. Install Patch-SecOps Solution with `bash packaging/install-bare.sh --with-monitoring`
6. Install Vendor with `bash install-vendor.sh`
7. Use a POC or testing license first if you need the customer hardware or MAC ID for final binding
8. Record that verified hardware or MAC ID in the Vendor portal
9. Generate the final bound PM2 license after Vendor install completes
10. Paste the newly generated PM2 license into Patch-SecOps Solution

### Internal Release Hygiene
- Do not give `patchmaster-license-authority.env` to customers
- Keep product and vendor packages aligned to the same license authority set to avoid license mismatch
- The customer product tarball is safe because it contains no vendor signing authority
- The vendor tarball is internal because it contains signing authority
- Customers do not need the Vendor portal to be reachable in order to activate and verify a valid license

### Internal Distribution Layout
- Customer-facing release: `dist/patchmaster-product-2.0.0.tar.gz`
- Vendor/internal release: `vendor/dist/patchmaster-vendor-2.0.0.tar.gz`
- Developer-only source bundle: `dist/developer/patchmaster-developer-kit-2.0.0/`
- Internal recovery files: `dist/private/patchmaster-license-authority.env` and `dist/private/patchmaster-license-public.env`
