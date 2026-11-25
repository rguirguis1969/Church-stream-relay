ARG BASE=ubuntu:24.04
FROM ${BASE}

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      nginx libnginx-mod-rtmp ffmpeg python3 python3-flask python3-waitress \
      supervisor ca-certificates tini \
 && rm -rf /var/lib/apt/lists/* \
 && rm -f /etc/nginx/sites-enabled/default

COPY conf/nginx.conf /etc/nginx/nginx.conf
COPY conf/supervisord.conf /etc/supervisor/supervisord.conf
COPY conf/entrypoint.sh /entrypoint.sh
COPY app/ /app/
RUN chmod 755 /entrypoint.sh

VOLUME /data
EXPOSE 1935 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/login',timeout=4)" || exit 1
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
