all: hn1 hbal

hn1:
	ghc --make -O2 -W hn1

hbal:
	ghc --make -O2 -W hbal

clean:
	rm -f *.o *.old hn1 hbal *.prof *.ps *.stat *.aux \
        *.hi README.html TAGS

.PHONY : all clean hn1 hbal
