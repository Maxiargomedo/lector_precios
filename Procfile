web: waitress-serve --port=$PORT --threads=4 mi_proyecto.wsgi:application
release: python manage.py migrate && python manage.py collectstatic --noinput
