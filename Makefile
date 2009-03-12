HPROGS = hbal hn1
HSRCS := $(filter-out $(HPROGS), $(wildcard src/*.hs))
HDDIR = apidoc

# Haskell rules

all: version
	$(MAKE) -C src

README.html: README
	rst2html $< $@

doc: README.html
	rm -rf $(HDDIR)
	mkdir -p $(HDDIR)/src
	cp hscolour.css $(HDDIR)/src
	for file in $(HSRCS); do \
		HsColour -css -anchor \
		$$file > $(HDDIR)/src/`basename $$file .hs`.html ; \
	done
	haddock --odir $(HDDIR) --html --ignore-all-exports \
		-t htools -p haddock-prologue \
		--source-module="src/%{MODULE/.//}.html" \
		--source-entity="src/%{MODULE/.//}.html#%{NAME}" \
		$(HSRCS)

clean:
	rm -f *.o *.cmi *.cmo *.cmx *.old hn1 zn1 *.prof *.ps *.stat *.aux \
        gmon.out *.hi README.html TAGS version

version:
	git describe > $@

dist: version
	VN=$$(cat version|sed 's/^v//') ; \
	ANAME="htools-$$VN.tar" ; \
    git archive --format=tar --prefix=htools-$$VN/ HEAD > $$ANAME ; \
	tar -r -f $$ANAME --transform="s,^,htools-$$VN/," version

.PHONY : all doc clean hn1 dist
