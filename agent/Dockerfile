# BASE_IMAGE picks the distro the fake fleet runs (plan.md S0-8): the default
# keeps the original Debian image for anyone building ./agent without args.
ARG BASE_IMAGE=python:3.10-slim
FROM ${BASE_IMAGE}

WORKDIR /opt/patch-agent

# python:* images already ship python3; distro bases need it installing.
# Gate on pip, not on python3: rockylinux:9 ships python3 without pip.
# Alpine also gets a toolchain: psutil has no musl wheel everywhere.
RUN set -eux; \
    if python3 -m pip --version >/dev/null 2>&1; then \
        :; \
    elif command -v apt-get >/dev/null 2>&1; then \
        apt-get update; \
        apt-get install -y --no-install-recommends python3 python3-pip; \
        rm -rf /var/lib/apt/lists/*; \
    elif command -v dnf >/dev/null 2>&1; then \
        dnf install -y python3 python3-pip; \
        dnf clean all; \
    else \
        apk add --no-cache python3 py3-pip gcc musl-dev linux-headers python3-dev; \
    fi

COPY requirements.txt .
# Retry chain: distros marking python PEP 668 (Alpine, newer Rocky) refuse
# system installs; old pips do not know --break-system-packages; as a last
# resort drop the EXTERNALLY-MANAGED marker (container, not a host).
RUN python3 -m pip install --no-cache-dir -r requirements.txt \
    || python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt \
    || { rm -f /usr/lib/python3*/EXTERNALLY-MANAGED; \
         python3 -m pip install --no-cache-dir -r requirements.txt; }

COPY . .

CMD ["python3", "main.py"]
