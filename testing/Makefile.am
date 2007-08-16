TESTS = ganeti.hooks_unittest.py ganeti.utils_unittest.py
TESTS_ENVIRONMENT = PYTHONPATH=.:$(srcdir)

check_DATA = ganeti
ganeti:
	rm -f ganeti
	ln -s $(top_srcdir)/lib ganeti

EXTRA_DIST = $(TESTS) mocks.py ganeti.qa.py qa-sample.yaml
