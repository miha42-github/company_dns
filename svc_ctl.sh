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

function check_error () {
    EXIT=$1
    CMD=$2

    if [ $EXIT -eq 0 ]; then
        echo -e "${GREEN}ok${NC}"
    else
        echo "${RED}FAILED${NC}, ${CMD} exited with code: ${EXIT}"
        exit -1
    fi
}

# Validate environment and dependencies before proceeding
function check_dependencies () {
    FUNC="Checking dependencies"
    print_header "${FUNC}"
    if ! command -v docker &> /dev/null; then
        print_detail "${ORANGE}Warning:${NC} Docker not found"
    else
        print_detail "Docker: ${GREEN}found${NC}"
    fi
    if [ ! -f "company_dns.py" ]; then
        print_detail "${RED}Error:${NC} company_dns.py not found"
        exit 1
    else
        print_detail "company_dns.py: ${GREEN}found${NC}"
    fi
    print_footer "${FUNC}"
}

function print_header () {
    HEADER="${1}"
    echo -e ">>>> ${ORANGE}BEGIN:${NC} ${BLUE}${HEADER}${NC}"
}

function print_step () {
    MSG="${1}"
    SEP=" ... "
    echo -n -e "${ORANGE}${MSG}${NC}${SEP}"
}

function print_detail () {
    DETAIL="${1}"
    echo -e "${BLUE}${DETAIL}${NC}"
}

function print_footer () {
    FOOTER="${1}"
    echo -e ">>>> ${ORANGE}END:${NC} ${BLUE}${FOOTER}${NC}"
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
    FUNC="Bring down service"
    STEP="bring_down_server"
    print_header "${FUNC}"
    docker_image=$(get_container_id)

    if [ -z "$docker_image" ]; then
        print_step "No running container found for ${FULL_IMAGE_NAME}"
        echo -e "${ORANGE}skipped${NC}"
    else
        print_step "Bringing down ${FULL_IMAGE_NAME} (${docker_image})"
        docker kill ${docker_image} > /dev/null 2>&1
        check_error $? "docker kill"
    fi

    print_footer "${FUNC}"
}

function stop_server () {
    FUNC="Stop ${SERVICE}"
    STEP="stop_server"
    print_header "${FUNC}"
    docker_image=$(get_container_id)

    if [ -z "$docker_image" ]; then
        print_step "No running container found for ${FULL_IMAGE_NAME}"
        echo -e "${ORANGE}skipped${NC}"
    else
        print_step "Stopping ${FULL_IMAGE_NAME} (${docker_image})"
        docker stop ${docker_image} > /dev/null 2>&1
        check_error $? "docker stop"
    fi

    print_footer "${FUNC}"
}

function start_server () {
    FUNC="Start ${SERVICE} in the background"
    print_header "${FUNC}"
    
    docker_image=$(get_container_id)
    if [ ! -z "$docker_image" ]; then
        print_step "Container already running as ${docker_image}"
        echo -e "${ORANGE}skipped${NC}"
    else
        print_step "Starting ${FULL_IMAGE_NAME}"
        execute_docker_run "background" > /dev/null 2>&1
        check_error $? "docker run"
        
        docker_image=$(get_container_id)
        print_detail "Container started as ${docker_image}"
    fi
    
    print_footer "${FUNC}"
}

function build_server () {
    FUNC="Build ${SERVICE}"
    print_header "${FUNC}"
    
    print_step "Building Docker image ${FULL_IMAGE_NAME}"
    docker build -t ${FULL_IMAGE_NAME} . > /dev/null 2>&1
    check_error $? "docker build"
    
    print_footer "${FUNC}"
}

function rebuild_server () {
    FUNC="Rebuild and restart ${SERVICE}"
    print_header "${FUNC}"
    
    stop_server
    build_server
    start_server
    
    print_footer "${FUNC}"
}

function status_server () {
    FUNC="Check status of ${SERVICE}"
    print_header "${FUNC}"
    
    docker_image=$(get_container_id)
    if [ -z "$docker_image" ]; then
        print_detail "Status: ${RED}NOT RUNNING${NC}"
    else
        container_info=$(docker ps --filter "id=${docker_image}" --format "{{.Status}} - Created: {{.CreatedAt}}")
        print_detail "Status: ${GREEN}RUNNING${NC}"
        print_detail "Container ID: ${docker_image}"
        print_detail "Container info: ${container_info}"
        print_detail "Port mapping: ${PORT}:8000"
    fi
    
    print_footer "${FUNC}"
}

function run_foreground () {
    FUNC="Run $SERVICE in the foreground"
    print_header "${FUNC}"
    
    print_step "Starting ${FULL_IMAGE_NAME} in foreground"
    echo ""
    execute_docker_run "foreground"
    
    print_footer "${FUNC}"
}

function tail_backend () {
    FUNC="Tail logs for ${SERVICE}"
    print_header "${FUNC}"
    
    docker_image=$(get_container_id)
    if [ -z "$docker_image" ]; then
        print_detail "${RED}Error:${NC} No running container found for ${FULL_IMAGE_NAME}"
    else
        print_detail "Tailing logs for container ${docker_image}"
        echo ""
        docker logs -f ${docker_image}
    fi
    
    print_footer "${FUNC}"
}

function cleanup_server () {
    FUNC="Clean up stale containers for ${SERVICE}"
    print_header "${FUNC}"
    
    # Find all containers (including stopped ones) for this image
    print_step "Finding all containers for ${FULL_IMAGE_NAME}"
    all_containers=$(docker ps -a -q --filter "ancestor=${FULL_IMAGE_NAME}")
    
    if [ -z "$all_containers" ]; then
        echo -e "${ORANGE}No containers found${NC}"
    else
        container_count=$(echo "$all_containers" | wc -l | tr -d ' ')
        echo -e "${GREEN}found ${container_count}${NC}"
        
        # Get running containers
        running_containers=$(get_container_id)
        
        # Remove stopped containers
        print_step "Removing stopped containers"
        removed_count=0
        
        for container in $all_containers; do
            # Skip if the container is running
            if [[ "$running_containers" == *"$container"* ]]; then
                print_detail "Skipping running container: ${container}"
                continue
            fi
            
            print_detail "Removing container: ${container}"
            docker rm $container > /dev/null 2>&1
            if [ $? -eq 0 ]; then
                removed_count=$((removed_count+1))
            fi
        done
        
        if [ $removed_count -eq 0 ]; then
            echo -e "${ORANGE}No containers removed${NC}"
        else
            echo -e "${GREEN}removed ${removed_count} containers${NC}"
        fi
    fi
    
    # Optional: Clean up dangling images
    print_step "Cleaning up dangling images"
    dangling_images=$(docker images -q -f "dangling=true")
    if [ -z "$dangling_images" ]; then
        echo -e "${ORANGE}No dangling images found${NC}"
    else
        docker rmi $(docker images -q -f "dangling=true") > /dev/null 2>&1
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}cleaned up dangling images${NC}"
        else
            echo -e "${RED}failed to clean up images${NC}"
        fi
    fi
    
    print_footer "${FUNC}"
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
