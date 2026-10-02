FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /a1-ei-adapter ./cmd/a1-ei-adapter

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /a1-ei-adapter /usr/local/bin/a1-ei-adapter
ENTRYPOINT ["/usr/local/bin/a1-ei-adapter"]
