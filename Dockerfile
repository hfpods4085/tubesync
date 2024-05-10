FROM alpine:3.19 as ffmpeg
ADD https://johnvansickle.com/ffmpeg/builds/ffmpeg-git-amd64-static.tar.xz /ffmpeg.tar.xz
RUN tar --strip-components 1 -xJf /ffmpeg.tar.xz

FROM python:3.11-slim-bookworm

# adds file from the shinsenter/s6-overlay image
COPY --from=shinsenter/s6-overlay:v3.1.6.2 / /

# add ffmpeg
COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe

# instal python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

## add PUID and PGID support
COPY docker/fix-permission /etc/cont-init.d/10-adduser
RUN groupadd --gid 1000 abc && \
    useradd -u 1000 -g 1000 --create-home -d /app -s /bin/false abc

COPY docker/services/ /etc/services.d
COPY tubesync /app/tubesync
WORKDIR /app
ENV HOME=/app \
    INTERVAL_BILIBILI=600 \
    INTERVAL_YOUTUBE=60

# important: sets s6-overlay entrypoint
ENTRYPOINT ["/init"]
