# ElasticBLAST demo directory

This directory contains the sources to create a docker image to facilitate
demos for ElasticBLAST by NCBI staff working on this project with the
necessary accounts set up.

**N.B**: The demos are limited to GCP _for now_.

## Instructions

### To run a demo on AWS

    docker run -it --rm gcr.io/ncbi-sandbox-blast/ncbi/elastic-blast-demo

    # Provide your AWS credentials. These will be deleted once the container exits.
    # You can obtain these from your environment (run "env | grep ^AWS") or
    # your AWS configuration file (see ~/.aws/credentials or ~/.aws/config)
    aws configure set aws_access_key_id <YOUR_ACCESS_KEY_ID>
    aws configure set aws_secret_access_key <YOUR_SECRET_ACCESS_KEY>
    aws configure set default.region us-east-1

    # Verify AWS account
    make aws-creds

    #################### DEMO STARTS HERE
    # Create a bucket for results
    make aws-init
    # Run the demo
    make aws-run

    # On a separate terminal, connect to the running docker container
    docker exec -ti `docker ps -q` bash
    # Check the log file 
    make aws-log
    # Inspect the AWS Batch dashboard via the AWS web console:
    # https://console.aws.amazon.com/batch
    # Click on elasticblast-masterblaster

    # You can try this command *AFTER* the gcp-run command has completed successfully
    make aws-status

    # Wait until results are ready...

    # Check the results
    make aws-results
    # Delete the ElasticBLAST resources
    make aws-delete
    # Delete the bucket created for the results
    make aws-distclean

### To run a demo on GCP

Open the [GCP cloud shell (https://console.cloud.google.com/?cloudshell=true)](https://console.cloud.google.com/?cloudshell=true) 
and enter the following commands:

    docker run -it --rm gcr.io/ncbi-sandbox-blast/ncbi/elastic-blast-demo

    # Set up GCP access. After running this command, a URL will be printed on
    # your terminal. It is advisable to open said URL in an browser incognito window
    gcloud auth login --no-launch-browser <YOUR_GCP_EMAIL_ADDRESS>  # E.g.: $USER@ncbi.nlm.nih.gov. 
    # Check that the GCP project is set:
    gcloud config get-value project
    # If your GCP project is unset, run the command below, otherwise, skip the next command
    gcloud config set project <YOUR_GCP_PROJECT> # This may be ncbi-sandbox-blast or strides-ncbi-cloud-education
    # If your GCP project is not ncbi-sandbox-blast, please run the command below, otherwise, skip the next command
    export ELB_GCP_PROJECT=<YOUR_GCP_PROJECT>

    # Verify GCP account
    make gcp-creds

    #################### DEMO STARTS HERE
    # Create a bucket for results
    make gcp-init
    # Run the demo
    make gcp-run

    # On a separate terminal, connect to the running docker container
    docker exec -ti `docker ps -q` bash
    # Check the log file 
    make gcp-log
    # Inspect the GKE cluster via the GCP web console:
    # https://console.cloud.google.com/kubernetes/list
    # Click on elasticblast-masterblaster

    # You can try this command *AFTER* the gcp-run command has completed successfully
    make gcp-status

    # Wait until results are ready...

    # Check the results
    make gcp-results
    # Delete the ElasticBLAST resources
    make gcp-delete
    # Delete the bucket created for the results
    make gcp-distclean

**N.B.**: Only one person can have a demo running at once.

### To build the docker image

**N.B.**: This step is not really necessary, as there is a [TeamCity
build](https://teamcity.ncbi.nlm.nih.gov/buildConfiguration/Blast_ElasticBlast_BuildDemoDockerImage?mode=builds)
which automatically runs this for every release.

The command below builds the image using [GCP Cloud
Build](https://cloud.google.com/cloud-build).

    make gcp-build gcp-check

If you do not have GCP credentials and/or just want to build the image outside
GCP, you can run the command below. This **requires** `docker` available in
your `PATH` and your ability to run docker commands:

    make

