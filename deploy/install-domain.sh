#!/bin/sh
# Serve Whisp on a domain over HTTPS: installs the nginx site, then asks Let's Encrypt
# for a certificate. The domain's DNS A record must already point at this server.
#
#   sudo ./deploy/install-domain.sh whisp.example.com [you@example.com]
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer with sudo." >&2
    exit 1
fi
if [ $# -lt 1 ]; then
    echo "Usage: sudo $0 <domain> [email for Let's Encrypt notices]" >&2
    exit 1
fi

domain="$1"
email="${2:-}"
if ! printf '%s' "$domain" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$'; then
    echo "Not a valid domain name: $domain" >&2
    exit 1
fi
if ! command -v certbot >/dev/null 2>&1; then
    echo "certbot is not installed. Run: sudo apt install certbot python3-certbot-nginx" >&2
    exit 1
fi

deploy_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
site_name="whisp-domain"

install -o root -g root -m 644 "$deploy_dir/nginx/whisp-ratelimit.conf" /etc/nginx/conf.d/whisp-ratelimit.conf
sed "s/__DOMAIN__/$domain/g" "$deploy_dir/nginx/whisp-domain.template" > "/etc/nginx/sites-available/$site_name"
chmod 644 "/etc/nginx/sites-available/$site_name"
ln -sfn "/etc/nginx/sites-available/$site_name" "/etc/nginx/sites-enabled/$site_name"
nginx -t
systemctl reload nginx

if [ -n "$email" ]; then
    certbot --nginx -d "$domain" --redirect --non-interactive --agree-tos -m "$email"
else
    certbot --nginx -d "$domain" --redirect --non-interactive --agree-tos --register-unsafely-without-email
fi

echo "Whisp is served at https://$domain"
echo "Set WHISP_PUBLIC_BASE_URL=https://$domain in .env and redeploy to register the webhook."
