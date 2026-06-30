TARGET  ?= dv02

SHELL  := pwsh.exe
.SHELLFLAGS := -NoProfile -Command

.PHONY: deploy

deploy:
	scp -r nokia pms@$(TARGET):/home/pms/online/sbin
