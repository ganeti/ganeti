all: hn1 hbal

hn1:
	ghc --make -O2 -W hn1

hbal:
	ghc --make -O2 -W hbal

clean:
	rm -f *.o *.cmi *.cmo *.cmx *.old hn1 zn1 *.prof *.ps *.stat *.aux \
        gmon.out *.hi README.html TAGS

.PHONY : all clean hn1 hbal
