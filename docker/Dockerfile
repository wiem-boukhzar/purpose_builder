# Backend container for the FastAPI service. Built from the binary context in
# Jenkins (docker/ directory). Apollo credentials are injected at runtime.
FROM registry.access.redhat.com/ubi9/python-312


ARG nexusHostWithBasicAuth
ARG nexusHostWithoutScheme
ARG nexusCdsRepo=pypi-cds-dev-local


ARG HTTPS_PROXY
ARG HTTP_PROXY
ARG NO_PROXY


ENV https_proxy=${HTTPS_PROXY}
ENV http_proxy=${HTTP_PROXY}
ENV no_proxy=${NO_PROXY}
ENV LANG=C.UTF-8


USER root
RUN mkdir -p /app /app/logs


RUN yum -y update && \
   yum install -y gcc gcc-c++ make redhat-rpm-config python3-devel && \
   yum clean all


RUN chown -R 1001:0 /app && \
   chmod -R g=u /app


WORKDIR /app


# Install OS CA so pip can reach internal Nexus when provided
RUN openssl s_client -showcerts -host ${nexusHostWithoutScheme} -port 443  </dev/null| \
   sed -ne '/-BEGIN CERTIFICATE-/,/-END CERTIFICATE-/p' > /etc/pki/ca-trust/source/anchors/oc_app.crt && \
   update-ca-trust


ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-bundle.crt
ENV SSL_CERT_DIR=/etc/ssl/certs/
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt


COPY requirements.txt /app


RUN if [ ! -z ${nexusHostWithBasicAuth} ]; \
   then pip install -i ${nexusHostWithBasicAuth}/repository/pypi-all/simple \
       --extra-index-url ${nexusHostWithBasicAuth}/repository/${nexusCdsRepo}/simple \
       --trusted-host ${nexusHostWithoutScheme} --upgrade pip && \
   pip install -i ${nexusHostWithBasicAuth}/repository/pypi-all/simple \
       --extra-index-url ${nexusHostWithBasicAuth}/repository/${nexusCdsRepo}/simple \
       --trusted-host ${nexusHostWithoutScheme} -r requirements.txt; \
   else pip install --upgrade pip && pip install -r requirements.txt; \
   fi && \
   pip check


# Set certificates for python modules not looking at env vars
RUN cat $REQUESTS_CA_BUNDLE >> $(echo -e "import certifi\nprint(certifi.where())" | python)


# Copy code and data into the image
COPY src /app/src
COPY data /app/data


ENV PYTHONPATH=/app/src:$PYTHONPATH


# Precompute MONDO indexes so runtime doesn't need to parse the full RDF graph.
RUN python -m ontology_validation.precompute


# deactivate internet access by default
ENV HTTPS_PROXY=
ENV HTTP_PROXY=
ENV https_proxy=
ENV http_proxy=


USER 1001


ENV HOME=/app


EXPOSE 8080


CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8080"]





