# Use an official Python runtime as a parent image
FROM python:3.13-alpine

# Set the working directory in the container to /app
WORKDIR /app

# Add the current directory contents into the container at /app
ADD . /app

# Install curl and other dependencies
RUN apk --no-cache add curl curl-dev gcc musl-dev linux-headers jq && mkdir -p /app/edgar_data

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make entrypoint script executable
RUN chmod +x /app/scripts/entrypoint.sh

# Run makedb.py to create the database cache
RUN python makedb.py

# Run as a non-root user (k8s deployment sets runAsNonRoot: true).
# USER must be a numeric UID, not a name: Kubernetes' runAsNonRoot admission
# check verifies the UID without executing anything in the image, so a named
# user (USER company_dns) is unresolvable to it and fails closed with
# "cannot verify user is non-root". A numeric UID here fixes that.
RUN addgroup -S -g 10001 company_dns && adduser -S -u 10001 -G company_dns company_dns \
    && chown -R company_dns:company_dns /app
USER 10001

# Set environment variable for production
ENV ENVIRONMENT=production

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Use entrypoint script to configure hosts
# ENTRYPOINT ["/app/scripts/entrypoint.sh"]

# Run the command to start the application
CMD ["python", "company_dns.py"]