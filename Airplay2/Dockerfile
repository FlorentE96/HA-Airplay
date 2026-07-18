FROM mikebrady/shairport-sync:latest

RUN apk add --no-cache envsubst jq
RUN apk add --no-cache alsa-plugins-pulse
RUN apk add --no-cache pulseaudio

COPY start-addon.sh /start-addon.sh
RUN chmod +x /start-addon.sh

COPY shairport-sync.conf.tpl /etc/shairport-sync.conf

ENTRYPOINT ["/start-addon.sh"]
