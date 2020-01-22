# image
FROM python:slim
WORKDIR /app

# Copy all related files
COPY ./requirements.txt /app/requirements.txt
COPY ./apputils.py /app/apputils.py
COPY ./dbcontrol.py /app/dbcontrol.py
COPY ./pyedgar.conf /app/pyedgar.conf
COPY ./edgar_cache.db /app/edgar_cache.db
COPY ./.db_exists /app/.db_exists

# Set Flask Environment variables
ENV FLASK_APP app_edgar.py
ENV FLASK_RUN_HOST 0.0.0.0

# Run commands to prep the service
RUN pip3 install -r requirements.txt

COPY . /app

CMD [ "flask", "run" ]