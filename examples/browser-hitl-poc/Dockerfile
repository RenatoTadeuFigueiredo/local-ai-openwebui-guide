FROM ghcr.io/open-webui/computer@sha256:bbcf59b541dba201ca91084a1f7857ca617b94aa0f770b0fd2dd279e2e56a7ce

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends novnc python3-websockify x11vnc xvfb \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /etc/chromium/policies/managed /app

COPY --chown=root:root --chmod=0644 chromium-policy.json /etc/chromium/policies/managed/browser-hitl.json
COPY --chown=cptr:cptr --chmod=0644 chromium-policy.json /app/chromium-policy.json
COPY --chown=cptr:cptr --chmod=0644 pyproject.toml /app/pyproject.toml
COPY --chown=cptr:cptr --chmod=0755 browser_hitl /app/browser_hitl
COPY --chown=cptr:cptr --chmod=0755 openwebui /app/openwebui
COPY --chown=cptr:cptr --chmod=0755 tests /app/tests
RUN find /app/browser_hitl /app/openwebui /app/tests -type f -exec chmod 0644 {} +
WORKDIR /app
RUN uv pip install --python /home/cptr/.venv/bin/python --no-cache --no-deps 'pyee==13.0.1' \
    && uv pip install --python /home/cptr/.venv/bin/python --no-cache --no-deps 'playwright==1.62.0' \
    && uv pip install --python /home/cptr/.venv/bin/python --no-cache 'PyJWT[crypto]==2.13.0' \
    && uv pip install --python /home/cptr/.venv/bin/python --no-cache 'pytest==9.0.2' 'pytest-asyncio==1.3.0' \
    && uv pip install --python /home/cptr/.venv/bin/python --no-cache --no-deps .

USER cptr
RUN /home/cptr/.venv/bin/python -m pytest -q -p no:cacheprovider /app/tests
ENV HOME=/home/cptr \
    BROWSER_HITL_HOST=0.0.0.0 \
    BROWSER_HITL_PORT=3210 \
    BROWSER_HITL_ROOT=/data/browser-hitl

ENTRYPOINT []
CMD ["/home/cptr/.venv/bin/python", "-m", "browser_hitl.api"]
