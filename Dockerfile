# Use an official Python runtime as a parent image
FROM python:3.13.5-alpine

# Set the working directory in the container to /app
WORKDIR /app

# Add the current directory contents into the container at /app
ADD . /app

# Install curl, jq and create directory
RUN apk --no-cache add curl curl-dev gcc musl-dev linux-headers jq && mkdir -p /app/edgar_data

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make entrypoint script executable
RUN chmod +x /app/scripts/entrypoint.sh

# Run makedb.py to create the database cache
RUN python makedb.py

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Set default host if not provided
ENV COMPANY_DNS_HOST=company-dns.mediumroast.io

# Use entrypoint script to configure hosts
ENTRYPOINT ["/app/scripts/entrypoint.sh"]

# Run the command to start the application
CMD ["python", "company_dns.py"]