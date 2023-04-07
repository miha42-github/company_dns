FROM tiangolo/uwsgi-nginx-flask:python3.11
COPY ./requirements.txt /var/www/requirements.txt
RUN pip3 install --no-cache-dir --upgrade -r /var/www/requirements.txt
COPY ./app /app