FROM ubuntu:latest
LABEL authors="WPower"

ENTRYPOINT ["top", "-b"]