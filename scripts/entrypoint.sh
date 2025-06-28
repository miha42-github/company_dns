#!/bin/sh
set -e

# Path to the hosts.js file
HOSTS_FILE="/app/html/hosts.js"

# Check if COMPANY_DNS_HOST environment variable is set
if [ -n "$COMPANY_DNS_HOST" ]; then
  echo "Setting primary host to $COMPANY_DNS_HOST"

  # Determine protocol based on hostname
  if echo "$COMPANY_DNS_HOST" | grep -q "localhost"; then
    PROTOCOL="http://"
  else
    PROTOCOL="https://"
  fi
  
  # Update the JavaScript file using sed
  # 1. Add the host to companyDnsServers if not present
  if ! grep -q "\"$COMPANY_DNS_HOST\":" $HOSTS_FILE; then
    sed -i "s/const companyDnsServers = {/const companyDnsServers = {\n  \"$COMPANY_DNS_HOST\": \"$PROTOCOL$COMPANY_DNS_HOST\",/g" $HOSTS_FILE
  fi
  
  # 2. Update the primaryHost value
  sed -i "s/const primaryHost = \"[^\"]*\"/const primaryHost = \"$COMPANY_DNS_HOST\"/g" $HOSTS_FILE
  
  echo "Updated hosts.js file with $COMPANY_DNS_HOST as primary"
fi

# Execute the main application
exec "$@"