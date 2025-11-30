#!/bin/sh

# Exit immediately if a command exits with a non-zero status.
set -e

# Apply database migrations
echo "Applying database migrations..."
python manage.py migrate

# Then exec the container's main process (what's specified as CMD in Dockerfile).
# This replaces the script process with the python process, ensuring signals are handled correctly.
echo "Starting server..."
exec "$@"