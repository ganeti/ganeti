FROM debian:stretch

LABEL maintainer="apoikos@debian.org"

WORKDIR /build
ARG uid

RUN apt-get update
RUN DEBIAN_FRONTEND=noninteractive \
  apt-get install --yes --no-install-recommends \
  adduser \
  build-essential \
  automake \
  pandoc \
  python-all \
  ghc \
  ghc-ghci \
  cabal-install \
  libghc-cabal-dev \
  libghc-case-insensitive-dev \
  libghc-curl-dev \
  libghc-json-dev \
  libghc-snap-server-dev \
  libghc-network-dev \
  libghc-parallel-dev \
  libghc-utf8-string-dev \
  libghc-deepseq-dev \
  libghc-hslogger-dev \
  libghc-crypto-dev \
  libghc-text-dev \
  libghc-hinotify-dev \
  libghc-base64-bytestring-dev \
  libghc-zlib-dev \
  libghc-regex-pcre-dev \
  libghc-attoparsec-dev \
  libghc-vector-dev \
  libghc-lifted-base-dev \
  libghc-lens-dev \
  libghc-psqueue-dev \
  libghc-test-framework-quickcheck2-dev \
  libghc-test-framework-hunit-dev \
  libghc-temporary-dev \
  libghc-old-time-dev \
  libpcre3-dev \
  libcurl4-openssl-dev \
  python-bitarray \
  python-ipaddr \
  python-mock \
  python-openssl \
  python-paramiko \
  python-pycurl \
  python-pyinotify \
  python-pyparsing \
  python-simplejson \
  python-sphinx \
  python-yaml \
  graphviz \
  openssh-client \
  procps \
  qemu-utils \
  socat \
  iproute2

RUN adduser --uid $uid --disabled-password --disabled-login --home /build --no-create-home --gecos 'Test Runner' gntest

RUN apt-get clean

USER gntest
