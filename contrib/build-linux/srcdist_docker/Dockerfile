FROM ubuntu:20.04@sha256:9d42d0e3e57bc067d10a75ee33bdd1a5298e95e5fc3c5d1fce98b455cb879249

ENV LC_ALL=C.UTF-8 LANG=C.UTF-8 TZ=America/New_York

RUN apt-get update -q && \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install -qy \
        git \
        wget \
        make \
        autotools-dev \
        autoconf \
        autopoint \
        libtool \
        xz-utils \
        libssl-dev \
        zlib1g-dev \
        libffi7 \
        libffi-dev \
        libncurses5-dev \
        libsqlite3-dev \
        libusb-1.0-0-dev \
        libudev-dev \
        gettext \
        libzbar0 \
        faketime \
        python3 \
        python3-pip \
        python3-venv \
        pkg-config \
        libjpeg-dev \
        && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get autoremove -y && \
    apt-get clean
