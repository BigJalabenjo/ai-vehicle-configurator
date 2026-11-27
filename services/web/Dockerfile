FROM nginx:1.27-alpine
# Rendered at container start: ${EMBED_ORIGINS} is filled in from the environment (nginx image templates).
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV EMBED_ORIGINS=""
COPY index.html app.js i18n.js voice.js voice-worklet.js login.html login.js styles.css /usr/share/nginx/html/
# Optional brand assets (logo, fonts); see assets/README.md
COPY assets /usr/share/nginx/html/assets
# Make the files readable by nginx, drop non-assets, and list the brand files that are present,
# so the client only requests files that exist.
RUN cd /usr/share/nginx/html/assets && \
    find . \( -name README.md -o -name .gitkeep -o -name .DS_Store \) -delete && \
    chmod -R a+rX . && \
    out="["; for f in logo.* cars/* fonts/*.woff2 fonts/*.woff fonts/*.otf fonts/*.ttf; do \
      [ -f "$f" ] || continue; [ "$out" = "[" ] || out="$out,"; out="$out\"$f\""; done; \
    echo "$out]" > manifest.json && cat manifest.json
EXPOSE 8080
