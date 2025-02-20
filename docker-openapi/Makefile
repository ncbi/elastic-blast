#

SHELL=/bin/bash
IMG?=elb-openapi
VERSION?=0.3
AZURE_REGISTRY?=elbacr.azurecr.io

ifeq (, $(shell which vmtouch 2>/dev/null))
NOVMTOUCH?=--no-vmtouch
else
ifeq (, $(shell which blastdb_path 2>/dev/null))            # If blastdb_path is not available, vmtouch cannot do its job, so skip it.
NOVMTOUCH?=--no-vmtouch
else
NOVMTOUCH?=
endif
endif

.PHONY: all azure-build
all: build 

.PHONY: build
build:
	docker build --build-arg version=${VERSION} -t ${IMG}:${VERSION} .
	docker tag ${IMG}:${VERSION} ${IMG}:latest

.PHONY: publish 
publish: build
	docker push ${IMG}:${VERSION}
	docker push ${IMG}:latest

.PHONY: azure-build
azure-build:
	az acr build --registry $(AZURE_REGISTRY) --image $(IMG):$(VERSION) .
