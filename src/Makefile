all: hn1 hbal

hn1: Version.hs
	ghc --make -O2 -W hn1

hbal: Version.hs
	ghc --make -O2 -W hbal

clean:
	rm -f *.o *.old hn1 hbal *.prof *.ps *.stat *.aux \
        *.hi README.html TAGS Version.hs

Version.hs: Version.hs.in ../version
	sed -e "s/%ver%/$$(cat ../version)/" < $< > $@

.PHONY : all clean hn1 hbal
