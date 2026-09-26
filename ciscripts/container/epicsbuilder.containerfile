FROM docker.ictrl.frm2.tum.de:5443/mlzbase/trixie AS epicsbuilder
# change this to force a rebuild of the epicsbuilder stage, e.g. when the epics-debhelper or epics-base repos have been updated
ARG BUILD_DATE=2026-03-19
USER root
ENV  DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Berlin
RUN  apt-get update && apt-get install -y gnupg ca-certificates && apt-get upgrade -y && apt-get clean
# this needs to be done after installing transport-https!
COPY 01norecommend /etc/apt/apt.conf.d/01norecommend

RUN apt-get update && apt-get -y install lintian git-buildpackage pristine-tar build-essential libreadline-dev debhelper dh-exec libparse-debcontrol-perl libtie-ixhash-perl

RUN  mkdir dpack && \
 cd dpack && \
 mkdir tmp && \
 git clone https://github.com/epicsdeb/epics-debhelper.git && \
 cd epics-debhelper && \
 gbp buildpackage --git-pristine-tar --git-export-dir=$PWD/../tmp  --git-no-sign-tags --no-sign  && \
 dpkg -i ../tmp/*.deb && \
 cd ../.. && rm -rf dpack
RUN apt-get -y install  g++-mingw-w64
RUN  mkdir dpack && \
 cd dpack && \
 mkdir out && \
 git clone https://github.com/epicsdeb/epics-base.git && \
 cd epics-base && \
 gbp buildpackage --git-no-pristine-tar --git-export-dir=$PWD/../out  --git-no-sign-tags  --no-sign