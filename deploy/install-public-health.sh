#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer with sudo." >&2
    exit 1
fi

deploy_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
site_name="whisp-health"

install -o root -g root -m 644 "$deploy_dir/nginx/$site_name" "/etc/nginx/sites-available/$site_name"
ln -sfn "/etc/nginx/sites-available/$site_name" "/etc/nginx/sites-enabled/$site_name"

nginx -t
systemctl reload nginx

echo "Published http://159.198.66.238/healthz"
