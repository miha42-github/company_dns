FROM tiangolo/uwsgi-nginx-flask:python3.8
COPY ./requirements.txt /var/www/requirements.txt
COPY ./app /app
RUN pip3 install -r /var/www/requirements.txt