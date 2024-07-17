Query splitting docker image
============================

This docker image encapsulates the functionality to perform query splitting
for ElasticBLAST on the cloud (as opposed to the local client invoking
ElasticBLAST).

The `Makefile` contains targets to build, test and deploy the docker image in
various repositories.

If you have `docker` available, run `make build` to build the image, and `make
check` to test it locally.

You will need credentials for NCBI-AWS-ELASTICBLAST-OPERATIONS to push to AWS ECR, see *To get NCBI AWS credentials in NCBI-AWS-ELASTICBLAST-OPERATIONS* in  [README-ncbi.md](../README-ncbi.md).
