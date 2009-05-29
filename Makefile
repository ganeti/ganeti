HPROGS = hbal hn1 hscan hail
HALLPROGS = $(HPROGS) test
HSRCS := $(wildcard Ganeti/HTools/*.hs)
HDDIR = apidoc

DOCS = README.html NEWS.html

HFLAGS = -O2 -W -fwarn-monomorphism-restriction -fwarn-tabs
HEXTRA =

HPCEXCL = --exclude Main --exclude Ganeti.HTools.QC

# Haskell rules

all: $(HPROGS)

$(HALLPROGS): %: %.hs Ganeti/HTools/Version.hs $(HSRCS) Makefile
	ghc --make $(HFLAGS) $(HEXTRA) $@

test: HEXTRA=-fhpc

$(DOCS) : %.html : %
	rst2html $< $@

doc: $(DOCS)
	rm -rf $(HDDIR)
	mkdir -p $(HDDIR)/Ganeti/HTools
	cp hscolour.css $(HDDIR)/Ganeti/HTools
	for file in $(HSRCS); do \
		HsColour -css -anchor \
		$$file > $(HDDIR)/Ganeti/HTools/`basename $$file .hs`.html ; \
	done
	haddock --odir $(HDDIR) --html --ignore-all-exports \
		-t htools -p haddock-prologue \
		--source-module="%{MODULE/.//}.html" \
		--source-entity="%{MODULE/.//}.html#%{NAME}" \
		$(HSRCS)

maintainer-clean:
	rm -rf $(HDDIR)
	rm -f $(DOCS) TAGS version Ganeti/HTools/Version.hs

clean:
	rm -f $(HALLPROGS)
	rm -f *.o *.prof *.ps *.stat *.aux *.hi
	cd Ganeti/HTools && rm -f *.o *.prof *.ps *.stat *.aux *.hi

version:
	git describe > $@

Ganeti/HTools/Version.hs: Ganeti/HTools/Version.hs.in version
	sed -e "s/%ver%/$$(cat version)/" < $< > $@

dist: Ganeti/HTools/Version.hs version doc
	VN=$$(cat version|sed 's/^v//') ; \
	ANAME="htools-$$VN.tar" ; \
	rm -f $$ANAME $$ANAME.gz ; \
	git archive --format=tar --prefix=htools-$$VN/ HEAD > $$ANAME ; \
	tar -r -f $$ANAME --owner root --group root \
	    --transform="s,^,htools-$$VN/," version apidoc $(DOCS) ; \
	gzip -v9 $$ANAME ; \
	tar tzvf $$ANAME.gz

check: test
	rm -f *.tix *.mix
	./test
ifeq ($(T),markup)
	mkdir -p coverage
	hpc markup --destdir=coverage test $(HPCEXCL)
else
	hpc report test $(HPCEXCL)
endif

.PHONY : all doc maintainer-clean clean dist check
