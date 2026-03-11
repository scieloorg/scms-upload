#!/bin/bash

upload_version=$1
if [ ! $1 ]; then
    echo "Version not informed. Please, inform the Upload version. E.g.: v2.3.4, ./install.sh v2.3.4"
    exit 128
fi

UPLOAD_DIR=./upload
ENV_FILES_DIR=.envs/.production

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
    #wget -O production.yml https://raw.githubusercontent.com/scieloorg/scms-upload/refs/tags/$1/production.yml
fi


echo $1 > VERSION

echo "Version $(cat VERSION) installed/updated!"

read -p "Enter the Docker login user: " DOCKER_USER
docker login -u $DOCKER_USER

make build compose=production.yml
make django_migrate compose=production.yml
make up compose=production.yml
make ps compose=production.yml

cd -
exit 0 

