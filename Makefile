HPROGS = hbal hn1 hscan hail
HSRCS := $(wildcard Ganeti/HTools/*.hs)
HDDIR = apidoc

DOCS = README.html NEWS.html

# Haskell rules

all: $(HPROGS)

$(HPROGS): %: %.hs Ganeti/HTools/Version.hs $(HSRCS) Makefile
	ghc --make -O2 -W $@

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
	rm -f $(HPROGS)
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

.PHONY : all doc maintainer-clean clean dist
