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
# Created: Tue Aug 31 11:29:06 EDT 2021

SHELL=/bin/bash
.PHONY: all pre-check check clean build publish gcp-build gcp-check gcp-clean

IMG?=ncbi/elasticblast-janitor
VERSION?=0.0.1
GCP_PROJECT?=$(shell gcloud config get-value project 2>/dev/null)
GCP_TEST_BUCKET?=gs://elasticblast-test/query-split-run-test

all: gcp-build gcp-check

build:
	docker build --build-arg version=${VERSION} -f Dockerfile.gcp -t ${IMG}:${VERSION} .
	docker tag ${IMG}:${VERSION} ${IMG}:latest

publish: build
	docker push ${IMG}:${VERSION}
	docker push ${IMG}:latest

clean:
	-docker image rm ${IMG}:${VERSION} ${IMG}:latest

check:
	-docker run --rm ${IMG}:${VERSION} elastic-blast --version
	-docker run --rm ${IMG}:${VERSION}

gcp-build:
	gcloud builds submit --config cloudbuild.yaml --substitutions _VERSION=${VERSION},_IMG=${IMG}

TAG?=${USER}
# Use this target to build an image from your local sources as opposed to those on PyPI.org
# Your image will be named gcr.io/${GCP_PROJECT}/${IMG}:${USER} and aliased as
# gcr.io/${GCP_PROJECT}/${IMG}:latest
gcp-build-from-local-sources: VERSION=$(shell elastic-blast --version | cut -f 2 -d ' ')
gcp-build-from-local-sources:
	rsync -a ../setup.py ../setup.cfg_cloud ../src ../bin ../requirements ${PWD}/
	sed -i~ -e '/^value = $${VERSION}/d;' setup.cfg_cloud
	echo "value = ${VERSION}" >> setup.cfg_cloud
	mv Dockerfile.gcp Dockerfile.gcp~
	mv Dockerfile-build-from-local-sources.gcp Dockerfile.gcp
	-gcloud builds submit --config cloudbuild.yaml --substitutions _VERSION=${TAG},_IMG=${IMG}
	rm -fr src bin requirements setup.cfg_cloud setup.py
	mv Dockerfile.gcp Dockerfile-build-from-local-sources.gcp
	mv Dockerfile.gcp~ Dockerfile.gcp

.PHONY: gcp-test
gcp-test:
	gcloud builds submit --config cloudrun.yaml --substitutions _IMG="gcr.io/${GCP_PROJECT}/${IMG}:${VERSION}"

gcp-clean:
	-gcloud container images delete gcr.io/${GCP_PROJECT}/${IMG}:${VERSION}

gcp-check:
	-gcloud container images list --repository=gcr.io/${GCP_PROJECT}/${IMG}
	-gcloud container images list-tags gcr.io/${GCP_PROJECT}/${IMG}
	-gcloud container images describe gcr.io/${GCP_PROJECT}/${IMG}:latest
	-gcloud container images describe gcr.io/${GCP_PROJECT}/${IMG}:${VERSION}
	#gcloud builds submit --config test-cloudbuild.yaml --substitutions _TAG=$(VERSION),_IMG=${IMG}

gcp-list-tagless-images:
	gcloud container images list-tags gcr.io/${GCP_PROJECT}/${IMG} \
		--filter='-tags:*' --format="get(digest)"
