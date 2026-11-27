TARGET  ?= dv02

SHELL  := pwsh.exe
.SHELLFLAGS := -NoProfile -Command

.PHONY: deploy

deploy:
	scp -r nokia pms@$(TARGET):/home/pms/online/sbin

upload-disc:
	scp output/* pms@$(TARGET):/home/pms/online/data/nokia/disc