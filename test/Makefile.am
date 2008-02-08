TESTS = \
  ganeti.config_unittest.py \
  ganeti.hooks_unittest.py \
  ganeti.utils_unittest.py \
  ganeti.bdev_unittest.py \
  ganeti.locking_unittest.py

TESTS_ENVIRONMENT = PYTHONPATH=.:$(top_builddir)

check-am: do-pre-check

do-pre-check:
	$(MAKE) -C $(top_builddir) pre-check

EXTRA_DIST = $(TESTS) mocks.py $(wildcard data/*.txt)
CLEANFILES = *.py[co]
