#!/bin/sh
set -e

: "${BACKEND_PORT:=8000}"

echo "Applying migrations..."
python manage.py migrate --noinput

if [ "$1" = "daphne" ]; then
  echo "Starting Daphne on port ${BACKEND_PORT}"
  exec daphne -b 0.0.0.0 -p ${BACKEND_PORT} ragreader.asgi:application
fi

exec "$@"
