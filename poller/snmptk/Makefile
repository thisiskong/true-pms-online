MODULE      := true-pms-online
DEPLOY_USER := pms
DEPLOY_HOST := dv02
DEPLOY_PATH := /home/pms/online/sbin

.PHONY: build build-linux deploy test test-verbose clean fmt vet

build: build-linux

build-linux:
	GOOS=linux GOARCH=386 go build -tags gosnmp_nodebug -o snmptk  ./cmd/snmptk
	GOOS=linux GOARCH=386 go build -tags gosnmp_nodebug -o sping    ./cmd/sping
	GOOS=linux GOARCH=386 go build                      -o serviceapi ./cmd/serviceapi

deploy: build-linux
	echo "put snmptk $(DEPLOY_PATH)/snmptk" | sftp $(DEPLOY_USER)@$(DEPLOY_HOST)
	echo "put sping $(DEPLOY_PATH)/sping" | sftp $(DEPLOY_USER)@$(DEPLOY_HOST)
	echo "put serviceapi $(DEPLOY_PATH)/serviceapi" | sftp $(DEPLOY_USER)@$(DEPLOY_HOST)
	ssh $(DEPLOY_USER)@$(DEPLOY_HOST) "sudo setcap cap_net_raw=+ep $(DEPLOY_PATH)/snmptk"
	ssh $(DEPLOY_USER)@$(DEPLOY_HOST) "sudo setcap cap_net_raw=+ep $(DEPLOY_PATH)/sping"

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
	rm -f snmptk sping serviceapi
