#!/bin/bash

go build -o serviceapi cmd/serviceapi/serviceapi.go

serviceapi --get-spl1 BKK26AGNG01
# serviceapi --get-spl1 BKK03001G00
# serviceapi --get-spl1 ANC01003G00
# serviceapi --get-spl1 APTSKE1AVW0

