#!/bin/sh
set -e

: "${BACKEND_PORT:=8000}"

echo "Applying migrations..."
python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"