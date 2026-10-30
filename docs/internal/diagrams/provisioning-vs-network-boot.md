# Patch-SecOps Solution Provisioning Vs Network Boot

## 1. Current Provisioning Center Flow

```mermaid
flowchart TD
    A["Operator opens Provisioning Center"] --> B["Choose registered source host"]
    B --> C["Capture full-system image"]
    C --> D["Store golden image on Patch-SecOps Solution server"]
    D --> E["Create provisioning template"]
    E --> F["Choose registered target hosts"]
    F --> G["Queue rollout through operations queue"]
    G --> H["Target agents download and restore image"]
    H --> I["Patch-SecOps Solution records per-target results"]
```

## 2. Managed Network Boot Flow

```mermaid
flowchart TD
    A["Operator opens Network Boot"] --> B["Create boot network"]
    B --> C["Define addressing, relay binding, BIOS and UEFI boot files"]
    C --> D["Create boot profile"]
    D --> E["Choose install mode and install source"]
    E --> F["Optional: link stored golden image template"]
    F --> G["Patch-SecOps Solution generates iPXE script"]
    G --> H["Patch-SecOps Solution generates answer file"]
    H --> I["Operator validates rollout design and standards"]
    I --> J["Relay bundle prepared for deployment"]
    J --> K["Bare-metal endpoint boots and enrolls"]
```

## 3. Managed Relay Workflow

```mermaid
flowchart LR
    A["Define networks<br/>and relay binding"] --> B["Publish boot artifacts<br/>and answer files"]
    B --> C["Install and validate<br/>managed relays"]
    C --> D["Run bare-metal rollout<br/>and first-boot enrollment"]
```

## 4. Current Provisioning Vs Managed Network Boot

```mermaid
flowchart LR
    subgraph CURRENT["Current Provisioning Center"]
        A1["Requires enrolled agent"]
        A2["Uses snapshot + restore APIs"]
        A3["Best for reimage and recovery"]
    end

    subgraph RELAY["Managed Network Boot"]
        B1["Designed for pre-agent hosts"]
        B2["Uses iPXE + answer generation"]
        B3["Includes relay bundle + unattended boot"]
    end
```

## 5. Trust And Delivery Boundary

```mermaid
flowchart TD
    A["Provisioning Center"] --> B["Managed host already trusted by Patch-SecOps Solution agent"]
    C["Managed Network Boot"] --> D["Pre-agent delivery boundary"]
    D --> E["HTTP boot artifacts"]
    D --> F["Relay DNS/DHCP/TFTP configuration"]
    D --> G["First-boot agent enrollment"]
```

## Operator Instructions

1. Use `Provisioning Center` for live image rollouts to already-enrolled endpoints.
2. Use `Network Boot` to define rollout standards, boot networks, install profiles, and relay bindings.
3. Preview generated iPXE and answer templates, then validate the managed relay configuration before rollout.
4. Treat `Network Boot` as the live bare-metal workspace for managed-relay deployment.
