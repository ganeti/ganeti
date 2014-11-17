#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


"""Utilities for unit testing"""

import os
import sys
import stat
import tempfile
import unittest
import logging

from ganeti import utils


def GetSourceDir():
  return os.environ.get("TOP_SRCDIR", ".")


def TestDataFilename(name):
  """Returns the filename of a given test data file.

  @type name: str
  @param name: the 'base' of the file name, as present in
      the test/data directory
  @rtype: str
  @return: the full path to the filename, such that it can
      be used in 'make distcheck' rules

  """
  return "%s/test/data/%s" % (GetSourceDir(), name)


def ReadTestData(name):
  """Returns the content of a test data file.

  This is just a very simple wrapper over utils.ReadFile with the
  proper test file name.

  """
  return utils.ReadFile(TestDataFilename(name))


def _SetupLogging(verbose):
  """Setupup logging infrastructure.

  """
  fmt = logging.Formatter("%(asctime)s: %(threadName)s"
                          " %(levelname)s %(message)s")

  if verbose:
    handler = logging.StreamHandler()
  else:
    handler = logging.FileHandler(os.devnull, "a")

  handler.setLevel(logging.NOTSET)
  handler.setFormatter(fmt)

  root_logger = logging.getLogger("")
  root_logger.setLevel(logging.NOTSET)
  root_logger.addHandler(handler)


class GanetiTestProgram(unittest.TestProgram):
  def runTests(self):
    """Runs all tests.

    """
    _SetupLogging("LOGTOSTDERR" in os.environ)

    sys.stderr.write("Running %s\n" % self.progName)
    sys.stderr.flush()

    # Ensure assertions will be evaluated
    if not __debug__:
      raise Exception("Not running in debug mode, assertions would not be"
                      " evaluated")

    # Check again, this time with a real assertion
    try:
      assert False
    except AssertionError:
      pass
    else:
      raise Exception("Assertion not evaluated")

    return unittest.TestProgram.runTests(self)


# pylint: disable=R0904
class GanetiTestCase(unittest.TestCase):
  """Helper class for unittesting.

  This class defines a few utility functions that help in building
  unittests. Child classes must call the parent setup and cleanup.

  """
  def setUp(self):
    self._temp_files = []
    self.patches = {}
    self.mocks = {}

  def MockOut(self, name, patch=None):
    if patch is None:
      patch = name
    self.patches[name] = patch
    self.mocks[name] = patch.start()

  def tearDown(self):
    while self._temp_files:
      try:
        utils.RemoveFile(self._temp_files.pop())
      except EnvironmentError:
        pass

    for patch in self.patches.values():
      patch.stop()

    self.patches = {}
    self.mocks = {}

  def assertFileContent(self, file_name, expected_content):
    """Checks that the content of a file is what we expect.

    @type file_name: str
    @param file_name: the file whose contents we should check
    @type expected_content: str
    @param expected_content: the content we expect

    """
    actual_content = utils.ReadFile(file_name)
    self.assertEqual(actual_content, expected_content)

  def assertFileContentNotEqual(self, file_name, reference_content):
    """Checks that the content of a file is different to the reference.

    @type file_name: str
    @param file_name: the file whose contents we should check
    @type reference_content: str
    @param reference_content: the content we use as reference

    """
    actual_content = utils.ReadFile(file_name)
    self.assertNotEqual(actual_content, reference_content)

  def assertFileMode(self, file_name, expected_mode):
    """Checks that the mode of a file is what we expect.

    @type file_name: str
    @param file_name: the file whose contents we should check
    @type expected_mode: int
    @param expected_mode: the mode we expect

    """
    st = os.stat(file_name)
    actual_mode = stat.S_IMODE(st.st_mode)
    self.assertEqual(actual_mode, expected_mode)

  def assertFileUid(self, file_name, expected_uid):
    """Checks that the user id of a file is what we expect.

    @type file_name: str
    @param file_name: the file whose contents we should check
    @type expected_uid: int
    @param expected_uid: the user id we expect

    """
    st = os.stat(file_name)
    actual_uid = st.st_uid
    self.assertEqual(actual_uid, expected_uid)

  def assertFileGid(self, file_name, expected_gid):
    """Checks that the group id of a file is what we expect.

    @type file_name: str
    @param file_name: the file whose contents we should check
    @type expected_gid: int
    @param expected_gid: the group id we expect

    """
    st = os.stat(file_name)
    actual_gid = st.st_gid
    self.assertEqual(actual_gid, expected_gid)

  def assertEqualValues(self, first, second, msg=None):
    """Compares two values whether they're equal.

    Tuples are automatically converted to lists before comparing.

    """
    return self.assertEqual(UnifyValueType(first),
                            UnifyValueType(second),
                            msg=msg)

  def _CreateTempFile(self):
    """Creates a temporary file and adds it to the internal cleanup list.

    This method simplifies the creation and cleanup of temporary files
    during tests.

    """
    fh, fname = tempfile.mkstemp(prefix="ganeti-test", suffix=".tmp")
    os.close(fh)
    self._temp_files.append(fname)
    return fname

# pylint: enable=R0904


def patch_object(*args, **kwargs):
  """Unified patch_object for various versions of Python Mock.

  Different Python Mock versions provide incompatible versions of patching an
  object. More recent versions use _patch_object, older ones used patch_object.
  This function unifies the different variations.

  """
  import mock
  try:
    # pylint: disable=W0212
    return mock._patch_object(*args, **kwargs)
  except AttributeError:
    # pylint: disable=E1101
    return mock.patch_object(*args, **kwargs)


def UnifyValueType(data):
  """Converts all tuples into lists.

  This is useful for unittests where an external library doesn't keep types.

  """
  if isinstance(data, (tuple, list)):
    return [UnifyValueType(i) for i in data]

  elif isinstance(data, dict):
    return dict([(UnifyValueType(key), UnifyValueType(value))
                 for (key, value) in data.iteritems()])

  return data


class CallCounter(object):
  """Utility class to count number of calls to a function/method.

  """
  def __init__(self, fn):
    """Initializes this class.

    @type fn: Callable

    """
    self._fn = fn
    self._count = 0

  def __call__(self, *args, **kwargs):
    """Calls wrapped function with given parameters.

    """
    self._count += 1
    return self._fn(*args, **kwargs)

  def Count(self):
    """Returns number of calls.

    @rtype: number

    """
    return self._count
