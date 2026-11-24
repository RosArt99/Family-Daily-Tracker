# Odoo 17 plus the Python packages our addons need on top of the stock image.
# Rebuild after changing this file:  docker compose build odoo && docker compose up -d
FROM odoo:17.0

USER root
# Newer pip refuses to install into the system Python without this; older pip ignores it.
ENV PIP_BREAK_SYSTEM_PACKAGES=1
# anthropic: Claude API client for family_ai (assistant messages, push texts).
RUN pip3 install --no-cache-dir anthropic
USER odoo
