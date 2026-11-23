web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 60
worker: celery -A config worker --loglevel=INFO
beat: celery -A config beat --loglevel=INFO
