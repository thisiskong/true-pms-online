BINARY     := pms-poller
MODULE     := github.com/thisiskong/true-pms-online
BUILD_DIR  := .

.PHONY: build build-linux test test-verbose clean fmt vet

build:
	go build -o $(BINARY) ./cmd/poller

build-linux:
	GOOS=linux GOARCH=386 go build -o $(BINARY) ./cmd/poller

test:
	go test ./...

test-verbose:
	go test -v ./...

test-run:
	go test ./... -run $(RUN)

fmt:
	go fmt ./...

vet:
	go vet ./...

clean:
	rm -f $(BINARY)
