#!/usr/bin/python
#

# Copyright (C) 2013, 2016 Google Inc.
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


"""Script for unittesting the ganeti.storage.filestorage module"""

import os
import shutil
import tempfile
import unittest

from ganeti import errors
from ganeti.storage import filestorage
from ganeti.utils import io
from ganeti import utils
from ganeti import constants

import testutils


class TestFileStorageSpaceInfo(unittest.TestCase):

  def testSpaceInfoPathInvalid(self):
    """Tests that an error is raised when the given path is not existing.

    """
    self.assertRaises(errors.CommandError, filestorage.GetFileStorageSpaceInfo,
                      "/path/does/not/exist/")

  def testSpaceInfoPathValid(self):
    """Smoke test run on a directory that exists for sure.

    """
    filestorage.GetFileStorageSpaceInfo("/")


class TestCheckFileStoragePath(unittest.TestCase):
  def _WriteAllowedFile(self, allowed_paths_filename, allowed_paths):
    allowed_paths_file = open(allowed_paths_filename, 'w')
    allowed_paths_file.write('\n'.join(allowed_paths))
    allowed_paths_file.close()

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.allowed_paths = [os.path.join(self.tmpdir, "allowed")]
    for path in self.allowed_paths:
      os.mkdir(path)
    self.allowed_paths_filename = os.path.join(self.tmpdir, "allowed-path-file")
    self._WriteAllowedFile(self.allowed_paths_filename, self.allowed_paths)

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testCheckFileStoragePathExistance(self):
    filestorage._CheckFileStoragePathExistance(self.tmpdir)

  def testCheckFileStoragePathExistanceFail(self):
    path = os.path.join(self.tmpdir, "does/not/exist")
    self.assertRaises(errors.FileStoragePathError,
        filestorage._CheckFileStoragePathExistance, path)

  def testCheckFileStoragePathNotWritable(self):
    path = os.path.join(self.tmpdir, "isnotwritable/")
    os.mkdir(path)
    os.chmod(path, 0)
    self.assertRaises(errors.FileStoragePathError,
        filestorage._CheckFileStoragePathExistance, path)
    os.chmod(path, 777)

  def testCheckFileStoragePath(self):
    path = os.path.join(self.allowed_paths[0], "allowedsubdir")
    os.mkdir(path)
    result = filestorage.CheckFileStoragePath(
        path, _allowed_paths_file=self.allowed_paths_filename)
    self.assertEqual(None, result)

  def testCheckFileStoragePathNotAllowed(self):
    path = os.path.join(self.tmpdir, "notallowed")
    result = filestorage.CheckFileStoragePath(
        path, _allowed_paths_file=self.allowed_paths_filename)
    self.assertTrue("not acceptable" in result)


class TestLoadAllowedFileStoragePaths(testutils.GanetiTestCase):
  def testDevNull(self):
    self.assertEqual(filestorage._LoadAllowedFileStoragePaths("/dev/null"), [])

  def testNonExistantFile(self):
    filename = "/tmp/this/file/does/not/exist"
    assert not os.path.exists(filename)
    self.assertEqual(filestorage._LoadAllowedFileStoragePaths(filename), [])

  def test(self):
    tmpfile = self._CreateTempFile()

    utils.WriteFile(tmpfile, data="""
      # This is a test file
      /tmp
      /srv/storage
      relative/path
      """)

    self.assertEqual(filestorage._LoadAllowedFileStoragePaths(tmpfile), [
      "/tmp",
      "/srv/storage",
      "relative/path",
      ])


class TestComputeWrongFileStoragePathsInternal(unittest.TestCase):
  def testPaths(self):
    paths = filestorage._GetForbiddenFileStoragePaths()

    for path in ["/bin", "/usr/local/sbin", "/lib64", "/etc", "/sys"]:
      self.assertTrue(path in paths)

    self.assertEqual(set(map(os.path.normpath, paths)), paths)

  def test(self):
    vfsp = filestorage._ComputeWrongFileStoragePaths
    self.assertEqual(vfsp([]), [])
    self.assertEqual(vfsp(["/tmp"]), [])
    self.assertEqual(vfsp(["/bin/ls"]), ["/bin/ls"])
    self.assertEqual(vfsp(["/bin"]), ["/bin"])
    self.assertEqual(vfsp(["/usr/sbin/vim", "/srv/file-storage"]),
                     ["/usr/sbin/vim"])


class TestComputeWrongFileStoragePaths(testutils.GanetiTestCase):
  def test(self):
    tmpfile = self._CreateTempFile()

    utils.WriteFile(tmpfile, data="""
      /tmp
      x/y///z/relative
      # This is a test file
      /srv/storage
      /bin
      /usr/local/lib32/
      relative/path
      """)

    self.assertEqual(
        filestorage.ComputeWrongFileStoragePaths(_filename=tmpfile),
        ["/bin",
         "/usr/local/lib32",
         "relative/path",
         "x/y/z/relative",
        ])


class TestCheckFileStoragePathInternal(unittest.TestCase):
  def testNonAbsolute(self):
    for i in ["", "tmp", "foo/bar/baz"]:
      self.assertRaises(errors.FileStoragePathError,
                        filestorage._CheckFileStoragePath, i, ["/tmp"])

    self.assertRaises(errors.FileStoragePathError,
                      filestorage._CheckFileStoragePath, "/tmp", ["tmp", "xyz"])

  def testNoAllowed(self):
    self.assertRaises(errors.FileStoragePathError,
                      filestorage._CheckFileStoragePath, "/tmp", [])

  def testNoAdditionalPathComponent(self):
    self.assertRaises(errors.FileStoragePathError,
                      filestorage._CheckFileStoragePath, "/tmp/foo",
                      ["/tmp/foo"])

  def testAllowed(self):
    filestorage._CheckFileStoragePath("/tmp/foo/a", ["/tmp/foo"])
    filestorage._CheckFileStoragePath("/tmp/foo/a/x", ["/tmp/foo"])


class TestCheckFileStoragePathExistance(testutils.GanetiTestCase):
  def testNonExistantFile(self):
    filename = "/tmp/this/file/does/not/exist"
    assert not os.path.exists(filename)
    self.assertRaises(errors.FileStoragePathError,
                      filestorage.CheckFileStoragePathAcceptance, "/bin/",
                      _filename=filename)
    self.assertRaises(errors.FileStoragePathError,
                      filestorage.CheckFileStoragePathAcceptance,
                      "/srv/file-storage", _filename=filename)

  def testAllowedPath(self):
    tmpfile = self._CreateTempFile()

    utils.WriteFile(tmpfile, data="""
      /srv/storage
      """)

    filestorage.CheckFileStoragePathAcceptance(
        "/srv/storage/inst1", _filename=tmpfile)

    # No additional path component
    self.assertRaises(errors.FileStoragePathError,
                      filestorage.CheckFileStoragePathAcceptance,
                      "/srv/storage", _filename=tmpfile)

    # Forbidden path
    self.assertRaises(errors.FileStoragePathError,
                      filestorage.CheckFileStoragePathAcceptance,
                      "/usr/lib64/xyz", _filename=tmpfile)


class TestFileDeviceHelper(testutils.GanetiTestCase):

  @staticmethod
  def _Make(path, create_with_size=None, create_folders=False):
    skip_checks = lambda path: None
    if create_with_size:
      return filestorage.FileDeviceHelper.CreateFile(
        path, create_with_size, create_folders=create_folders,
        _file_path_acceptance_fn=skip_checks
      )
    else:
      return filestorage.FileDeviceHelper(path,
                                          _file_path_acceptance_fn=skip_checks)

  class TempEnvironment(object):

    def __init__(self, create_file=False, delete_file=True):
      self.create_file = create_file
      self.delete_file = delete_file

    def __enter__(self):
      self.directory = tempfile.mkdtemp()
      self.subdirectory = io.PathJoin(self.directory, "pinky")
      os.mkdir(self.subdirectory)
      self.path = io.PathJoin(self.subdirectory, "bunny")
      self.volume = TestFileDeviceHelper._Make(self.path)
      if self.create_file:
        open(self.path, mode="w").close()
      return self

    def __exit__(self, *args):
      if self.delete_file:
        os.unlink(self.path)
      os.rmdir(self.subdirectory)
      os.rmdir(self.directory)
      return False #don't swallow exceptions

  def testOperationsOnNonExistingFiles(self):
    path = "/e/no/ent"
    volume = TestFileDeviceHelper._Make(path)

    # These should fail horribly.
    volume.Exists(assert_exists=False)
    self.assertRaises(errors.BlockDeviceError, volume.Exists,
                      assert_exists=True)
    self.assertRaises(errors.BlockDeviceError, volume.Size)
    self.assertRaises(errors.BlockDeviceError, volume.Grow,
                      0.020, True, False, None)

    # Removing however fails silently.
    volume.Remove()

    # Make sure we don't create all directories for you unless we ask for it
    self.assertRaises(errors.BlockDeviceError, TestFileDeviceHelper._Make,
                      path, create_with_size=1)

  def testFileCreation(self):
    with TestFileDeviceHelper.TempEnvironment() as env:
      TestFileDeviceHelper._Make(env.path, create_with_size=1)

      self.assertTrue(env.volume.Exists())
      env.volume.Exists(assert_exists=True)
      self.assertRaises(errors.BlockDeviceError, env.volume.Exists,
                        assert_exists=False)

    self.assertRaises(errors.BlockDeviceError, TestFileDeviceHelper._Make,
                      "/enoent", create_with_size=0.042)

  def testFailSizeDirectory(self):
  # This should still fail.
   with TestFileDeviceHelper.TempEnvironment(delete_file=False) as env:
     test_helper = TestFileDeviceHelper._Make(env.subdirectory)
     self.assertRaises(errors.BlockDeviceError, test_helper.Size)

  def testGrowFile(self):
    with TestFileDeviceHelper.TempEnvironment(create_file=True) as env:
      self.assertRaises(errors.BlockDeviceError, env.volume.Grow, -1,
                        False, True, None)

      env.volume.Grow(2, False, True, None)
      self.assertEqual(2.0, env.volume.Size() / 1024.0**2)

  def testRemoveFile(self):
    with TestFileDeviceHelper.TempEnvironment(create_file=True,
                                              delete_file=False) as env:
      env.volume.Remove()
      env.volume.Exists(assert_exists=False)

  def testRenameFile(self):
    """Test if we can rename a file."""
    with TestFileDeviceHelper.TempEnvironment(create_file=True) as env:
      new_path = os.path.join(env.subdirectory, 'middle')
      env.volume.Move(new_path)
      self.assertEqual(new_path, env.volume.path)
      env.volume.Exists(assert_exists=True)
      env.path = new_path # update the path for the context manager


class TestFileStorage(testutils.GanetiTestCase):

  @testutils.patch_object(filestorage, "FileDeviceHelper")
  @testutils.patch_object(filestorage.FileStorage, "Attach")
  def testCreate(self, attach_mock, helper_mock):
    attach_mock.return_value = True
    helper_mock.return_value = None
    test_unique_id = ("test_driver", "/test/file")


    expect = filestorage.FileStorage(test_unique_id, [], 123, {}, {})
    got = filestorage.FileStorage.Create(test_unique_id, [], 123, None, {},
                                         False, {}, test_kwarg="test")

    self.assertEqual(expect, got)

  def testCreateFailure(self):
    test_unique_id = ("test_driver", "/test/file")

    self.assertRaises(errors.ProgrammerError, filestorage.FileStorage.Create,
                      test_unique_id, [], 123, None, {}, True, {})


if __name__ == "__main__":
  testutils.GanetiTestProgram()
