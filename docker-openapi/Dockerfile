# openapi

FROM google/cloud-sdk:alpine

ARG version

LABEL Description="OpenAPI for NCBI ElasticBLAST Cloud Job Submission Module for Azure Kubernetes Service"
LABEL Version=${version}
LABEL Vendor="Microsoft"
LABEL Maintainer=moonchoi@microsoft.com


COPY ./nginx/default.conf /etc/nginx/conf.d/default.conf

WORKDIR /app
COPY ./app /app

RUN apk -U upgrade && \
    apk add --no-cache bash gettext curl unzip jq python3 py3-pip && \
    rm -rf /var/cache/apk/*

# Install system dependencies
RUN apk add --no-cache --update \
    python3 \
    py3-pip \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev \
    cargo \
    make \
    zip \
    unzip


# Create and activate a virtual environment for Azure CLI
RUN python3 -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir azure-cli --break-system-packages\
    && deactivate

ENV PATH="/opt/venv/bin:$PATH"
    
RUN wget -O azcopy_v10.tar.gz https://aka.ms/downloadazcopy-v10-linux && \
    tar -xf azcopy_v10.tar.gz --strip-components=1 && \
    ls -al && \
    cp ./azcopy /usr/bin 


RUN gcloud -q components install kubectl

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
