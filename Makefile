HPROGS = hbal hn1
HSRCS := $(filter-out $(HPROGS), $(wildcard src/*.hs))
HDDIR = apidoc

# Haskell rules

all: hbal hn1

hn1 hbal: Ganeti/HTools/Version.hs
	ghc --make -O2 -W $@

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
	rm -f *.o hn1 zn1 *.prof *.ps *.stat *.aux \
	    gmon.out *.hi README.html TAGS Ganeti/HTools/Version.hs
	git describe >/dev/null && rm -f version

version:
	git describe > $@

Ganeti/HTools/Version.hs: Ganeti/HTools/Version.hs.in version
	sed -e "s/%ver%/$$(cat ../version)/" < $< > $@

dist: version
	VN=$$(cat version|sed 's/^v//') ; \
	ANAME="htools-$$VN.tar" ; \
	rm -f $$ANAME $$ANAME.gz ; \
	git archive --format=tar --prefix=htools-$$VN/ HEAD > $$ANAME ; \
	tar -r -f $$ANAME --owner root --group root \
	    --transform="s,^,htools-$$VN/," version ; \
	gzip -v9 $$ANAME ; \
	tar tzvf $$ANAME.gz

.PHONY : all doc clean hn1 dist
