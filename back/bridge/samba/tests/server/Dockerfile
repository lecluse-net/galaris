FROM debian:trixie-20260623-slim
RUN apt-get update && apt-get install -y --no-install-recommends samba smbclient \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd synthetic \
    && useradd -M -g synthetic writer \
    && useradd -M -g synthetic reader \
    && printf 'synthetic-writer-password\nsynthetic-writer-password\n' | smbpasswd -s -a writer \
    && printf 'synthetic-reader-password\nsynthetic-reader-password\n' | smbpasswd -s -a reader
COPY smb.conf /etc/samba/smb.conf
# Enough metadata to exercise fragmented RPC responses and server pagination.
RUN for index in $(seq -w 0 31); do \
      printf '\n[volume-%s]\npath = /shares/secondary\nvalid users = writer reader\nread only = yes\ncomment = ' "$index" >> /etc/samba/smb.conf; \
      head -c 600 /dev/zero | tr '\000' 'x' >> /etc/samba/smb.conf; \
      printf '\n' >> /etc/samba/smb.conf; \
    done
CMD ["sh", "-c", "mkdir -p /shares/synthetic /shares/secondary && chown writer:synthetic /shares/synthetic /shares/secondary && chmod 2770 /shares/synthetic /shares/secondary && exec smbd --foreground --no-process-group --debug-stdout"]
