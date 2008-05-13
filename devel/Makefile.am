EXTRA_DIST = upload.in
CLEANFILES = upload

all-local: upload
upload: upload.in
	sed \
	  -e 's#@PREFIX@#$(prefix)#g' \
	< $< > $@
	chmod u+x $@
