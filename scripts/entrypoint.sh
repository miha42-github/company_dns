#!/bin/sh
set -e

# Path to the hosts.json file
HOSTS_FILE="/app/html/hosts.json"

# Check if COMPANY_DNS_HOST environment variable is set
if [ -n "$COMPANY_DNS_HOST" ]; then
  echo "Setting primary host to $COMPANY_DNS_HOST"

  # Check if this host already exists in the JSON
  HOST_EXISTS=$(cat $HOSTS_FILE | jq -r ".hosts[] | select(.name == \"$COMPANY_DNS_HOST\") | .name")
  
  if [ -z "$HOST_EXISTS" ]; then
    # Host doesn't exist, need to add it
    # Determine protocol based on hostname
    if echo "$COMPANY_DNS_HOST" | grep -q "localhost"; then
      PROTOCOL="http://"
    else
      PROTOCOL="https://"
    fi
    
    # Add new host and set it as primary, setting all others to non-primary
    cat $HOSTS_FILE | jq ".hosts = (.hosts | map(.isPrimary = false)) + [{\"name\": \"$COMPANY_DNS_HOST\", \"url\": \"${PROTOCOL}${COMPANY_DNS_HOST}\", \"isPrimary\": true, \"description\": \"Custom Host\"}]" > $HOSTS_FILE.tmp
  else
    # Host exists, just set it as primary
    cat $HOSTS_FILE | jq ".hosts = (.hosts | map(if .name == \"$COMPANY_DNS_HOST\" then .isPrimary = true else .isPrimary = false end))" > $HOSTS_FILE.tmp
  fi
  
  # Replace the original file
  mv $HOSTS_FILE.tmp $HOSTS_FILE
  echo "Updated hosts.json file with $COMPANY_DNS_HOST as primary"
fi

# Execute the main application
exec "$@"