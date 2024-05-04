# Use an official Python runtime as a parent image
# FROM python:3.12-slim
FROM python:3.12-alpine

# Set the working directory in the container to /app
WORKDIR /app

# Add the current directory contents into the container at /app
ADD . /app

# Install curl and create directory
# RUN apt-get update && apt-get install -y curl && mkdir -p /app/edgar_data
RUN apk --no-cache add curl curl-dev gcc musl-dev linux-headers && mkdir -p /app/edgar_data

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Run makedb.py to create the database cache
RUN python makedb.py

# Make port 80 available to the world outside this container
EXPOSE 8000

# Run the command to start the application
CMD ["python", "company_dns.py"]