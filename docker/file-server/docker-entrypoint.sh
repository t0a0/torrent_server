#!/bin/sh
set -eu

if [ -z "${DOWNLOAD_LINK_SECRET:-}" ]; then
  echo "DOWNLOAD_LINK_SECRET is required for file-server" >&2
  exit 1
fi

envsubst '${DOWNLOAD_LINK_SECRET}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf
