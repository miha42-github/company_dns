#!/usr/bin/env bash

#    Name: svc_ctl.sh
#    Purpose: Service control for the mediumroast.io
#    Copyright: Copyright 2021 and 2022 mediumroast.io. All rights reserved.
#    Author(s): Michael Hay, John Goodman

###################################
###
### Environment variables
###
###################################

# Service specific variables
SERVICE_NAME="www.mediumroast.io"
HELLO_EMAIL="hello@mediumroast.io"
IMAGE_NAME="company_dns:latest"
MEMORY_LIMIT="1g"
PORT="8080"

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
		

function bring_down_server () {
    FUNC="Bring down service"
    STEP="bring_down_server"
    print_header "${FUNC}"
    docker_image=`docker ps |grep " ${IMAGE_NAME} " |awk '{print $1}'`

	print_step "Bring down ${IMAGE_NAME}"
        docker kill ${docker_image}

    print_footer $FUNC
}

function bring_up_server () {
    FUNC="Bring up service"
    STEP="bring_up_server"
    print_header $FUNC

        print_step "Create cache db"
        create_db

        print_step "Build docker images"
        docker-compose build

    	print_step "Pull docker images"
        docker-compose pull

	    print_step "Bring up ${SERVICE}"
        docker-compose up -d

    print_footer $FUNC
}

function stop_server () {
    FUNC="Stop ${SERVICE}"
    STEP="stop_server"
    print_header $FUNC
    docker_image=`docker ps |grep " ${IMAGE_NAME} " |awk '{print $1}'`

	print_step "Stop $IMAGE_NAME"
        docker stop ${docker_image}

    print_footer $FUNC
}

function start_server () {
    FUNC="Start ${SERVICE} in the background"
    STEP="start_server"
    print_header "${FUNC}"
    docker run -d -m ${MEMORY_LIMIT} -p ${PORT}:${PORT} ${SERVICE}
    docker_image=`docker ps |grep " ${SERVICE} " |awk '{print $1}'`
}

function build_server () {
    FUNC="Build ${SERVICE}"
    print_header "${FUNC}"
    docker build -t ${IMAGE_NAME} .  
    print_footer "${FUNC}"
}

function run_foreground () {
    FUNC="Run $SERVICE in the foreground"
    print_header "${FUNC}"
    docker run -m ${MEMORY_LIMIT} -p 8000:8000 ${SERVICE}
    print_footer "${FUNC}"
}

function tail_backend () {
    FUNC="Tail logs for ${SERVICE}"
    print_header "${FUNC}"
    docker_image=`docker ps |grep " ${SERVICE} " |awk '{print $1}'`
    echo "'${docker_image}'"
    docker logs -f ${docker_image}
    print_footer "${FUNC}"
}

###################################
###
### Service specific functions
###
###################################


function create_db () {
    python3 ./makedb.py
}

function print_help () {
    clear
    echo "NAME:"
    echo "    $0 <sub-command>"
    echo ""
    echo "DESCRIPTION:"
    echo "    Control functions to run the ${SERVICE}"
    echo ""
    echo "COMMANDS:"
    echo "    help up down start stop create_db build delete_db foreground tail"
    echo ""
    echo "    help - call up this help text"
    echo "    up - bring up the service including building and pulling the docker image"
    echo "    down - bring down the service and remove the docker image"
    echo "    start - start the service using docker-compose "
    echo "    stop - stop the docker service"
    echo "    create_db - create a new database cache for the ${SERVICE}"
    echo "    build - build the docker images for the server"
    echo "    foreground - run the server in the foreground to watch for output"
    echo "    tail - tail the logs for a server running in the background"
    echo ""
    exit -1
}

###################################
###
### Main control shell logic
###
###################################


if [ ! $1 ] || [ $1 == "help" ]; then
    print_help

elif [ $1 == "up" ]; then
    create_db
    bring_up_server

elif [ $1 == "down" ]; then
    bring_down_server

elif [ $1 == "start" ]; then
    start_server

elif [ $1 == "stop" ]; then
    stop_server

elif [ $1 == "build" ]; then
    create_db
    build_server

elif [ $1 == "foreground" ]; then
    run_foreground

elif [ $1 == "tail" ]; then
    tail_backend

elif [ $1 == "create_db" ]; then
    create_db

fi

exit 0
