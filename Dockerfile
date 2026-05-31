FROM odoo:19.0-20260305

USER root

# TrueType fonts for PIL dashboard renderers (list/kanban/calendar/charts).
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

USER odoo
