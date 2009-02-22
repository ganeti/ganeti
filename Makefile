HPROGS = hbal hn1
HSRCS := $(filter-out $(HPROGS), $(wildcard src/*.hs))
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
	haddock --odir $(HDDIR) --html --ignore-all-exports \
	    -t htools -p haddock-prologue \
        --source-module="src/%{MODULE/.//}.html" \
        --source-entity="src/%{MODULE/.//}.html#%{NAME}" \
	    $(HSRCS)

clean:
	rm -f *.o *.cmi *.cmo *.cmx *.old hn1 zn1 *.prof *.ps *.stat *.aux \
        gmon.out *.hi README.html TAGS

.PHONY : all doc clean hn1
