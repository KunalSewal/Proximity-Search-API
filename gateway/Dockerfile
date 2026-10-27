# Gateway: nginx reverse proxy in front of the API + static file server for link files.
FROM nginx:1.28-alpine

# Read by the image's entrypoint, which runs envsubst on /etc/nginx/templates/*.template
# and writes the result to /etc/nginx/conf.d/ before nginx starts.
ENV API_HOST=api \
    API_PORT=8000 \
    MAX_UPLOAD=64m

RUN rm -f /etc/nginx/conf.d/default.conf \
    && mkdir -p /srv/links
COPY default.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO /dev/null http://127.0.0.1/gateway-health || exit 1
