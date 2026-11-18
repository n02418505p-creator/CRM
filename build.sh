#!/usr/bin/env bash
# Render build script: install, collect static files, update the database.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py setup_complaints
