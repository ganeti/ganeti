HSRCS := $(wildcard src/*.hs)
HDDIR = apidoc

# Haskell rules

all:
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
	ln -sf hn1.html $(HDDIR)/src/Main.html
	haddock --odir $(HDDIR) --html --ignore-all-exports \
	    -t hn1 -p haddock-prologue \
        --source-module="src/%{MODULE/.//}.html" \
        --source-entity="src/%{MODULE/.//}.html#%{NAME}" \
	    $(HSRCS)

clean:
	rm -f *.o *.cmi *.cmo *.cmx *.old hn1 zn1 *.prof *.ps *.stat *.aux \
        gmon.out *.hi README.html TAGS

.PHONY : all doc clean hn1
