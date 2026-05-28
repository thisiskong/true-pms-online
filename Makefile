BINARY      := poller-uptime
MODULE      := github.com/thisiskong/true-pms-online
BUILD_DIR   := .
DEPLOY_USER := pms
DEPLOY_HOST := dv02
DEPLOY_PATH := /home/pms/online/sbin/$(BINARY)

.PHONY: build build-linux deploy test test-verbose clean fmt vet

build: build-linux

build-linux:
	GOOS=linux GOARCH=386 go build -o $(BINARY) ./cmd/poller-uptime

deploy: build-linux
	echo "put $(BINARY) $(DEPLOY_PATH)" | sftp $(DEPLOY_USER)@$(DEPLOY_HOST)

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
