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

#FROM alpine:3.14
FROM google/cloud-sdk:alpine
ARG version

COPY requirements.txt .
COPY run.sh /usr/bin/

RUN chmod +x /usr/bin/run.sh && \
    apk -U upgrade && \
    apk add --no-cache bash python3 py3-pip py3-wheel curl unzip && \
    pip3 install --no-cache-dir --upgrade pip --break-system-packages && \
    pip3 install --no-cache-dir -r requirements.txt --break-system-packages && rm -rf /var/cache/apk/* requirements.txt

LABEL Description="NCBI ElasticBLAST Query Splitting Module"
LABEL Version=${version}
LABEL Vendor="NCBI/NLM/NIH"
LABEL Maintainer=camacho@ncbi.nlm.nih.gov


CMD ["run.sh", "-h"]
