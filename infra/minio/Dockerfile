# MinIO no longer publishes community images (minio/minio is gone from Docker Hub),
# so build the server and the mc client from source.
FROM golang:alpine AS build
RUN apk add --no-cache git
ENV CGO_ENABLED=0 GOTOOLCHAIN=auto
RUN go install github.com/minio/minio@latest
RUN go install github.com/minio/mc@latest

FROM alpine:3.20
RUN apk add --no-cache curl ca-certificates
COPY --from=build /go/bin/minio /go/bin/mc /usr/local/bin/
EXPOSE 9000
ENTRYPOINT ["minio"]
