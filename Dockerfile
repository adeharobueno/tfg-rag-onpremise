FROM docker.n8n.io/n8nio/n8n:2.21.4
USER root
RUN set -e; \
    BASE=/usr/local/lib/node_modules/n8n/node_modules; \
    V1=$(ls -d $BASE/.pnpm/pdf-parse@1.*/node_modules/pdf-parse \
         2>/dev/null | sort -V | tail -1); \
    test -n "$V1" || { echo 'ERROR: no hay pdf-parse v1'; exit 1; }; \
    rm -f $BASE/pdf-parse; \
    ln -s "$V1" $BASE/pdf-parse
USER node
