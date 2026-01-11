#!/usr/bin/env bash

#    Name: svc_ctl.sh
#    Purpose: Service control for the mediumroast.io
#    Copyright: Copyright 2021-2025 mediumroast.io. All rights reserved.
#    Author(s): Michael Hay, John Goodman

###################################
###
### Environment variables
###
###################################

# Service specific variables
SERVICE_NAME="www.mediumroast.io"
HELLO_EMAIL="hello@mediumroast.io"
IMAGE_NAME="company_dns"
IMAGE_TAG="latest"
FULL_IMAGE_NAME="${IMAGE_NAME}:${IMAGE_TAG}"
MEMORY_LIMIT="1g"
PORT="8000"

# Colors
NC='\033[0m'
ORANGE='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;94m'
GREEN='\033[0;92m'

# Generic variables
SERVICE="company_dns"
SERVICE_DIR="company_dns/"
APP_DIR="app/"

###################################
###
### Generic functions
###
###################################

# Print action with fixed width, awaiting status
function print_action () {
    MSG="${1}"
    printf "%-65s" "${MSG}"
}

# Print status: OK, FAIL, SKIP, WARN
function print_status () {
    STATUS="${1}"
    case "${STATUS}" in
        ok|OK)
            echo -e "[ ${GREEN} OK ${NC} ]"
            ;;
        fail|FAIL)
            echo -e "[ ${RED}FAIL${NC} ]"
            ;;
        skip|SKIP)
            echo -e "[ ${ORANGE}SKIP${NC} ]"
            ;;
        warn|WARN)
            echo -e "[ ${ORANGE}WARN${NC} ]"
            ;;
        *)
            echo -e "[ ${BLUE}${STATUS}${NC} ]"
            ;;
    esac
}

# Check command exit status and print result
function check_error () {
    EXIT=$1
    CMD=$2
    if [ $EXIT -eq 0 ]; then
        print_status "ok"
    else
        print_status "fail"
        echo -e "${RED}Error:${NC} ${CMD} exited with code: ${EXIT}"
        exit 1
    fi
}

# Validate environment and dependencies
function check_dependencies () {
    if ! command -v docker &> /dev/null; then
        print_action "Checking Docker availability"
        print_status "warn"
    else
        print_action "Checking Docker availability"
        print_status "ok"
    fi
    
    if [ ! -f "company_dns.py" ]; then
        print_action "Checking company_dns.py"
        print_status "fail"
        echo -e "${RED}Error:${NC} company_dns.py not found"
        exit 1
    else
        print_action "Checking company_dns.py"
        print_status "ok"
    fi
}

function get_container_id () {
    docker ps -q --filter "ancestor=${FULL_IMAGE_NAME}"
}

# Execute docker run with standard parameters (background or foreground mode)
function execute_docker_run () {
    local MODE=$1
    if [ "${MODE}" = "background" ]; then
        docker run -d -m ${MEMORY_LIMIT} -p ${PORT}:8000 ${FULL_IMAGE_NAME}
    else
        docker run -m ${MEMORY_LIMIT} -p ${PORT}:8000 ${FULL_IMAGE_NAME}
    fi
}

function bring_down_server () {
    docker_image=$(get_container_id)
    if [ -z "$docker_image" ]; then
        print_action "Killing ${SERVICE} container"
        print_status "skip"
    else
        print_action "Killing ${SERVICE} container (${docker_image})"
        docker kill ${docker_image} > /dev/null 2>&1
        check_error $? "docker kill"
    fi
}

function stop_server () {
    docker_image=$(get_container_id)
    if [ -z "$docker_image" ]; then
        print_action "Stopping ${SERVICE} container"
        print_status "skip"
    else
        print_action "Stopping ${SERVICE} container (${docker_image})"
        docker stop ${docker_image} > /dev/null 2>&1
        check_error $? "docker stop"
    fi
}

function start_server () {
    docker_image=$(get_container_id)
    if [ ! -z "$docker_image" ]; then
        print_action "Starting ${SERVICE} (already running as ${docker_image})"
        print_status "skip"
    else
        print_action "Starting ${SERVICE}"
        execute_docker_run "background" > /dev/null 2>&1
        check_error $? "docker run"
    fi
}

function build_server () {
    print_action "Building Docker image ${FULL_IMAGE_NAME}"
    docker build -t ${FULL_IMAGE_NAME} . > /dev/null 2>&1
    check_error $? "docker build"
}

function rebuild_server () {
    stop_server
    build_server
    start_server
}

function status_server () {
    docker_image=$(get_container_id)
    if [ -z "$docker_image" ]; then
        print_action "Checking ${SERVICE} status"
        print_status "fail"
        echo "  Status: NOT RUNNING"
    else
        print_action "Checking ${SERVICE} status"
        print_status "ok"
        container_info=$(docker ps --filter "id=${docker_image}" --format "{{.Status}}")
        echo "  Container: ${docker_image}"
        echo "  Status: ${container_info}"
        echo "  Port: ${PORT}:8000"
    fi
}

function run_foreground () {
    print_action "Starting ${SERVICE} in foreground"
    print_status "ok"
    echo ""
    execute_docker_run "foreground"
}

function tail_backend () {
    docker_image=$(get_container_id)
    if [ -z "$docker_image" ]; then
        print_action "Tailing logs for ${SERVICE}"
        print_status "fail"
        echo "  Error: No running container found"
    else
        print_action "Tailing logs for ${SERVICE} (${docker_image})"
        print_status "ok"
        echo ""
        docker logs -f ${docker_image}
    fi
}

function cleanup_server () {
    # Find all containers (including stopped ones) for this image
    print_action "Finding containers for ${FULL_IMAGE_NAME}"
    all_containers=$(docker ps -a -q --filter "ancestor=${FULL_IMAGE_NAME}")
    
    if [ -z "$all_containers" ]; then
        print_status "skip"
        echo "  No containers found"
    else
        container_count=$(echo "$all_containers" | wc -l | tr -d ' ')
        print_status "ok"
        echo "  Found ${container_count} container(s)"
        
        # Get running containers
        running_containers=$(get_container_id)
        
        # Remove stopped containers
        removed_count=0
        
        for container in $all_containers; do
            # Skip if the container is running
            if [[ "$running_containers" == *"$container"* ]]; then
                continue
            fi
            
            print_action "  Removing container ${container}"
            docker rm $container > /dev/null 2>&1
            check_error $? "docker rm"
            if [ $? -eq 0 ]; then
                removed_count=$((removed_count+1))
            fi
        done
        
        if [ $removed_count -eq 0 ]; then
            echo "  No stopped containers to remove"
        else
            echo "  Removed ${removed_count} container(s)"
        fi
    fi
    
    # Optional: Clean up dangling images
    print_action "Cleaning up dangling images"
    dangling_images=$(docker images -q -f "dangling=true")
    if [ -z "$dangling_images" ]; then
        print_status "skip"
        echo "  No dangling images found"
    else
        docker rmi $(docker images -q -f "dangling=true") > /dev/null 2>&1
        check_error $? "docker rmi"
    fi
}

###################################
###
### Service specific functions
###
###################################

function print_help () {
    clear
    echo "NAME:"
    echo "    $0 <sub-command>"
    echo ""
    echo "DESCRIPTION:"
    echo "    Control functions to run the ${SERVICE}"
    echo ""
    echo "COMMANDS:"
    echo "    help        - Display this help message"
    echo "    check-deps  - Validate dependencies and files"
    echo "    start       - Start the service in the background"
    echo "    stop        - Stop the running container gracefully"
    echo "    kill        - Forcefully stop the running container"
    echo "    build       - Build the Docker image"
    echo "    rebuild     - Rebuild image and restart the service"
    echo "    foreground  - Run the service in the foreground"
    echo "    tail        - View logs of the running container"
    echo "    status      - Check the status of the service"
    echo "    cleanup     - Remove stopped containers and clean up resources"
    echo ""
    exit 0
}

###################################
###
### Main control shell logic
###
###################################

if [ $# -eq 0 ]; then
    print_help
    exit 0
fi

case "${1}" in
    help)
        print_help
        ;;
    check-deps)
        check_dependencies
        ;;
    start)
        check_dependencies
        start_server
        ;;
    stop)
        stop_server
        ;;
    kill)
        bring_down_server
        ;;
    build)
        check_dependencies
        build_server
        ;;
    rebuild)
        check_dependencies
        rebuild_server
        ;;
    foreground)
        check_dependencies
        run_foreground
        ;;
    tail)
        tail_backend
        ;;
    status)
        status_server
        ;;
    cleanup)
        cleanup_server
        ;;
    *)
        echo -e "${RED}Error:${NC} Unknown command: ${1}"
        echo ""
        print_help
        ;;
esac

exit 0
