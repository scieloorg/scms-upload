#!/bin/bash
#
# Bash script for SciELO Upload Installation/Update
#
# How it works:
#       ./install <Upload version>
#
#     Check the tag version at https://github.com/scieloorg/scms-upload/releases


if [ -z "$1" ]; then
    # Version is mandatory
    echo "Version not informed. Please, inform the Upload version. E.g.: v2.3.4, ./install.sh v2.3.4"
    exit 128
fi

UPLOAD_DIR=./upload
ENV_FILES_DIR=.envs/.production
IS_UPDATE=0

echo "Checking directory $UPLOAD_DIR$ENV_FILES_DIR ..."

if [ ! -d "$UPLOAD_DIR/$ENV_FILES_DIR" ]; then
    echo "Installing version $1 ..."
    git clone --no-checkout --filter=blob:none --depth=1 --branch $1 --sparse https://github.com/scieloorg/scms-upload $UPLOAD_DIR
    cd $UPLOAD_DIR
    git sparse-checkout init --cone
    git sparse-checkout set .envs/.production-template compose/production/postgres/maintenance
    git checkout $1
    mv .envs/.production-template $ENV_FILES_DIR
else
    echo "Updating to version $1 ..."
    echo "  Downloading files from Git repository ..."
    cd $UPLOAD_DIR
    wget -O Makefile https://raw.githubusercontent.com/scieloorg/scms-upload/refs/tags/$1/Makefile
    wget -O production.yml https://raw.githubusercontent.com/scieloorg/scms-upload/refs/tags/$1/production.yml
    IS_UPDATE=1
fi

echo $1 > VERSION

echo "Version $(cat VERSION) installed/updated!"

if [ $IS_UPDATE -eq 1 ]; then
    # For installation: make Docker login and build DB
    read -p "Enter the Docker login user: " DOCKER_USER
    docker login -u $DOCKER_USER
    make build compose=production.yml
    make django_migrate compose=production.yml
else
    # For updating: update Django containers and make DB migrations
    make update_webapp compose=production.yml
    make django_migrate_fresh_migrations compose=production.yml
fi

make up compose=production.yml
make ps compose=production.yml

cd -
exit 0 

