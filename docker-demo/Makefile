#                           PUBLIC DOMAIN NOTICE
#              National Center for Biotechnology Information
#  
# This software is a "United States Government Work" under the
# terms of the United States Copyright Act.  It was written as part of
# the authors' official duties as United States Government employees and
# thus cannot be copyrighted.  This software is freely available
# to the public for use.  The National Library of Medicine and the U.S.
# Government have not placed any restriction on its use or reproduction.
#   
# Although all reasonable efforts have been taken to ensure the accuracy
# and reliability of the software and data, the NLM and the U.S.
# Government do not and cannot warrant the performance or results that
# may be obtained by using this software or data.  The NLM and the U.S.
# Government disclaim all warranties, express or implied, including
# warranties of performance, merchantability or fitness for any particular
# purpose.
#   
# Please cite NCBI in any work or product based on this material.

# Makefile for building a container to run an ElasticBLAST demo
#
# Author: Christiam Camacho
# Created: Tue Oct 13 10:48:55 EDT 2020

SHELL=/bin/bash
.PHONY: all pre-check check clean build publish

IMG?=ncbi/elastic-blast-demo
VERSION?=$(shell git describe --abbrev=0 --tags)

all: build check

build:
	docker build --build-arg version=${VERSION} -t ${IMG}:${VERSION} .
	docker tag ${IMG}:${VERSION} ${IMG}:latest

publish: build
	docker push ${IMG}:${VERSION}
	docker push ${IMG}:latest

clean:
	-docker image rm ${IMG}:${VERSION} ${IMG}:latest

check:
	docker run --rm ${IMG}:${VERSION} gcloud version
	docker run --rm ${IMG}:${VERSION} aws --version
	docker run --rm ${IMG}:${VERSION} kubectl version --client=true
	docker run --rm ${IMG}:${VERSION} elastic-blast --version
	docker run --rm ${IMG}:${VERSION} ls -lRa

TAG?=${USER}
gcp-build:
	gcloud builds submit --config cloudbuild.yaml --substitutions _TAG=$(TAG),_VERSION=${VERSION},_IMG=${IMG}

# Use this target to build an image from your local sources as opposed to those on PyPI.org
# Your image will be named gcr.io/${GCP_PROJECT}/${IMG}:${USER}
gcp-build-from-local-sources:
	rsync -a ../setup.py ../setup.cfg_cloud ../src ../bin ../requirements ${PWD}/
	sed -i~ -e '/^value = $${VERSION}/d;' setup.cfg_cloud
	echo "value = ${VERSION}" >> setup.cfg_cloud
	mv Dockerfile Dockerfile~
	mv Dockerfile-build-from-local-sources Dockerfile
	-gcloud builds submit --config cloudbuild.yaml --substitutions _TAG=$(TAG),_VERSION=${VERSION},_IMG=${IMG}
	rm -fr src bin requirements setup.cfg_cloud setup.py
	mv Dockerfile Dockerfile-build-from-local-sources
	mv Dockerfile~ Dockerfile

GCP_PROJECT?=$(shell gcloud config get-value project 2>/dev/null)
gcp-check:
	-gcloud container images list --repository=gcr.io/${GCP_PROJECT}/${IMG}
	-gcloud container images list-tags gcr.io/ncbi-sandbox-blast/ncbi/elastic-blast-demo
	-gcloud container images describe gcr.io/ncbi-sandbox-blast/ncbi/elastic-blast-demo:latest
	-gcloud container images describe gcr.io/ncbi-sandbox-blast/ncbi/elastic-blast-demo:${VERSION}
	gcloud builds submit --config test-cloudbuild.yaml --substitutions _TAG=$(TAG),_IMG=${IMG}

gcp-list-tagless-images:
	gcloud container images list-tags gcr.io/ncbi-sandbox-blast/ncbi/elastic-blast-demo \
		--filter='-tags:*' --format="get(digest)"
