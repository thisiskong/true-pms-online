MODULE      := true-pms-online
BINARY      := poll-uptime
DEPLOY_USER := pms
DEPLOY_HOST := dv02
DEPLOY_PATH := /home/pms/online/sbin/$(BINARY)

SHELL       := pwsh.exe
.SHELLFLAGS := -NoProfile -Command

.PHONY: build build-linux deploy test test-verbose clean fmt vet

build: build-linux

build-linux:
	$$env:CGO_ENABLED=0; $$env:GOOS='linux'; $$env:GOARCH='amd64'; go build -ldflags '-extldflags "-static"' -o $(BINARY) ./cmd/poll-uptime

deploy: build-linux
	& "$$env:SystemRoot\System32\OpenSSH\scp.exe" $(BINARY) $(DEPLOY_USER)@$(DEPLOY_HOST):$(DEPLOY_PATH)
	& "$$env:SystemRoot\System32\OpenSSH\ssh.exe" $(DEPLOY_USER)@$(DEPLOY_HOST) "sudo setcap cap_net_raw=+ep $(DEPLOY_PATH)"

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
	if (Test-Path $(BINARY)) { Remove-Item $(BINARY) }
