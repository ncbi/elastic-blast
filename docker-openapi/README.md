# ElasticBLAST docker image

This directory contains the tools needed to build the docker image used to
run BLAST in ElasticBLAST.

The `Makefile` contains targets to build, test and deploy the docker image in
various repositories.

If you have `docker` available, run `make azure-build` to build the image, and `make
check` to test it locally.

kubectl create deployment elb-openapi --image=elbacr.azurecr.io/elb-openapi:0.2
kubectl expose deployment elb-openapi --type=LoadBalancer --port=80 --target-port=8000