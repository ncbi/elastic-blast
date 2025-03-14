# openapi

FROM python:3.11-slim

ARG version

LABEL Description="OpenAPI for NCBI ElasticBLAST Cloud Job Submission Module for Azure Kubernetes Service"
LABEL Version=${version}
LABEL Vendor="Microsoft"
LABEL Maintainer=moonchoi@microsoft.com


COPY ./nginx/default.conf /etc/nginx/conf.d/default.conf

WORKDIR /app
COPY ./app /app

RUN ls -al

RUN apt-get -y -m update && \
    apt-get install -y apt-transport-https ca-certificates gnupg curl apt-utils


# Install Google Cloud SDK
RUN curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee /etc/apt/sources.list.d/google-cloud-sdk.list

RUN curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key | gpg --dearmor -o /usr/share/keyrings/kubernetes-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/kubernetes-archive-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /" | tee /etc/apt/sources.list.d/kubernetes.list



# RUN apk -U upgrade && \
#     apk add --no-cache bash gettext curl unzip jq python3 py3-pip && \
#     rm -rf /var/cache/apk/*
RUN apt-get -y -m update && \
    apt-get install -y kubectl zip unzip gnupg curl google-cloud-cli git wget jq && \
    pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir -r requirements.txt && \
    rm -rf /var/lib/apt/lists/* requirements.txt



# Install system dependencies
# RUN apk add --no-cache --update \
#     gcc \
#     musl-dev \
#     # python3-dev \
#     libffi-dev \
#     openssl-dev \
#     cargo \
#     make 


# Create and activate a virtual environment for Azure CLI
RUN python3 -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --upgrade pip \
    && pip install --no-cache-dir azure-cli --break-system-packages\
    && deactivate

ENV PATH="/opt/venv/bin:$PATH"

RUN wget -O azcopy_v10.tar.gz https://aka.ms/downloadazcopy-v10-linux && \
    tar -xf azcopy_v10.tar.gz --strip-components=1 && \
    ls -al && \
    cp ./azcopy /usr/bin && \
    rm -rf ./azcopy azcopy_v10.tar.gz


# RUN gcloud -q components install kubectl

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
