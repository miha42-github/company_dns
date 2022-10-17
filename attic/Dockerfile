# image
FROM python:slim
WORKDIR /app

# Copy all related support file
COPY ./requirements.txt /app/requirements.txt
COPY ./edgar_cache.db /app/edgar_cache.db
COPY ./pyedgar.conf /app/pyedgar.conf
COPY ./.db_exists /app/.db_exists

# Copy the code
COPY ./main.py /app/main.py
# COPY ./dbcontrol.py /app/dbcontrol.py <-- likely unneeded
# COPY ./dbshell.py /app/dbshell.py <-- likely unneeded
COPY ./lib/edgar.py /app/lib/edgar.py
COPY ./lib/wikipedia.py /app/lib/wikipedia.py
COPY ./lib/firmographics.py /app/lib/firmographics.py

# Set Flask Environment variables
ENV FLASK_APP main.py
ENV FLASK_RUN_HOST 0.0.0.0

# Run commands to prep the service
RUN pip3 install -r requirements.txt

COPY . /app

CMD [ "flask", "run" ]