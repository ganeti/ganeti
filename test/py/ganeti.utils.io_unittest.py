#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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


"""Script for testing ganeti.utils.io"""

import os
import tempfile
import unittest
import shutil
import glob
import time
import signal
import stat
import errno

from ganeti import constants
from ganeti import utils
from ganeti import compat
from ganeti import errors

import testutils


class TestReadFile(testutils.GanetiTestCase):
  def testReadAll(self):
    data = utils.ReadFile(testutils.TestDataFilename("cert1.pem"))
    self.assertEqual(len(data), 814)

    h = compat.md5_hash()
    h.update(data)
    self.assertEqual(h.hexdigest(), "a491efb3efe56a0535f924d5f8680fd4")

  def testReadSize(self):
    data = utils.ReadFile(testutils.TestDataFilename("cert1.pem"),
                          size=100)
    self.assertEqual(len(data), 100)

    h = compat.md5_hash()
    h.update(data)
    self.assertEqual(h.hexdigest(), "893772354e4e690b9efd073eed433ce7")

  def testCallback(self):
    def _Cb(fh):
      self.assertEqual(fh.tell(), 0)
    data = utils.ReadFile(testutils.TestDataFilename("cert1.pem"), preread=_Cb)
    self.assertEqual(len(data), 814)

  def testError(self):
    self.assertRaises(EnvironmentError, utils.ReadFile,
                      "/dev/null/does-not-exist")


class TestReadOneLineFile(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

  def testDefault(self):
    data = utils.ReadOneLineFile(testutils.TestDataFilename("cert1.pem"))
    self.assertEqual(len(data), 27)
    self.assertEqual(data, "-----BEGIN CERTIFICATE-----")

  def testNotStrict(self):
    data = utils.ReadOneLineFile(testutils.TestDataFilename("cert1.pem"),
                                 strict=False)
    self.assertEqual(len(data), 27)
    self.assertEqual(data, "-----BEGIN CERTIFICATE-----")

  def testStrictFailure(self):
    self.assertRaises(errors.GenericError, utils.ReadOneLineFile,
                      testutils.TestDataFilename("cert1.pem"), strict=True)

  def testLongLine(self):
    dummydata = (1024 * "Hello World! ")
    myfile = self._CreateTempFile()
    utils.WriteFile(myfile, data=dummydata)
    datastrict = utils.ReadOneLineFile(myfile, strict=True)
    datalax = utils.ReadOneLineFile(myfile, strict=False)
    self.assertEqual(dummydata, datastrict)
    self.assertEqual(dummydata, datalax)

  def testNewline(self):
    myfile = self._CreateTempFile()
    myline = "myline"
    for nl in ["", "\n", "\r\n"]:
      dummydata = "%s%s" % (myline, nl)
      utils.WriteFile(myfile, data=dummydata)
      datalax = utils.ReadOneLineFile(myfile, strict=False)
      self.assertEqual(myline, datalax)
      datastrict = utils.ReadOneLineFile(myfile, strict=True)
      self.assertEqual(myline, datastrict)

  def testWhitespaceAndMultipleLines(self):
    myfile = self._CreateTempFile()
    for nl in ["", "\n", "\r\n"]:
      for ws in [" ", "\t", "\t\t  \t", "\t "]:
        dummydata = (1024 * ("Foo bar baz %s%s" % (ws, nl)))
        utils.WriteFile(myfile, data=dummydata)
        datalax = utils.ReadOneLineFile(myfile, strict=False)
        if nl:
          self.assert_(set("\r\n") & set(dummydata))
          self.assertRaises(errors.GenericError, utils.ReadOneLineFile,
                            myfile, strict=True)
          explen = len("Foo bar baz ") + len(ws)
          self.assertEqual(len(datalax), explen)
          self.assertEqual(datalax, dummydata[:explen])
          self.assertFalse(set("\r\n") & set(datalax))
        else:
          datastrict = utils.ReadOneLineFile(myfile, strict=True)
          self.assertEqual(dummydata, datastrict)
          self.assertEqual(dummydata, datalax)

  def testEmptylines(self):
    myfile = self._CreateTempFile()
    myline = "myline"
    for nl in ["\n", "\r\n"]:
      for ol in ["", "otherline"]:
        dummydata = "%s%s%s%s%s%s" % (nl, nl, myline, nl, ol, nl)
        utils.WriteFile(myfile, data=dummydata)
        self.assert_(set("\r\n") & set(dummydata))
        datalax = utils.ReadOneLineFile(myfile, strict=False)
        self.assertEqual(myline, datalax)
        if ol:
          self.assertRaises(errors.GenericError, utils.ReadOneLineFile,
                            myfile, strict=True)
        else:
          datastrict = utils.ReadOneLineFile(myfile, strict=True)
          self.assertEqual(myline, datastrict)

  def testEmptyfile(self):
    myfile = self._CreateTempFile()
    self.assertRaises(errors.GenericError, utils.ReadOneLineFile, myfile)


class TestTimestampForFilename(unittest.TestCase):
  def test(self):
    self.assert_("." not in utils.TimestampForFilename())
    self.assert_(":" not in utils.TimestampForFilename())


class TestCreateBackup(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    testutils.GanetiTestCase.tearDown(self)

    shutil.rmtree(self.tmpdir)

  def testEmpty(self):
    filename = utils.PathJoin(self.tmpdir, "config.data")
    utils.WriteFile(filename, data="")
    bname = utils.CreateBackup(filename)
    self.assertFileContent(bname, "")
    self.assertEqual(len(glob.glob("%s*" % filename)), 2)
    utils.CreateBackup(filename)
    self.assertEqual(len(glob.glob("%s*" % filename)), 3)
    utils.CreateBackup(filename)
    self.assertEqual(len(glob.glob("%s*" % filename)), 4)

    fifoname = utils.PathJoin(self.tmpdir, "fifo")
    os.mkfifo(fifoname)
    self.assertRaises(errors.ProgrammerError, utils.CreateBackup, fifoname)

  def testContent(self):
    bkpcount = 0
    for data in ["", "X", "Hello World!\n" * 100, "Binary data\0\x01\x02\n"]:
      for rep in [1, 2, 10, 127]:
        testdata = data * rep

        filename = utils.PathJoin(self.tmpdir, "test.data_")
        utils.WriteFile(filename, data=testdata)
        self.assertFileContent(filename, testdata)

        for _ in range(3):
          bname = utils.CreateBackup(filename)
          bkpcount += 1
          self.assertFileContent(bname, testdata)
          self.assertEqual(len(glob.glob("%s*" % filename)), 1 + bkpcount)


class TestListVisibleFiles(unittest.TestCase):
  """Test case for ListVisibleFiles"""

  def setUp(self):
    self.path = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.path)

  def _CreateFiles(self, files):
    for name in files:
      utils.WriteFile(os.path.join(self.path, name), data="test")

  def _test(self, files, expected):
    self._CreateFiles(files)
    found = utils.ListVisibleFiles(self.path)
    self.assertEqual(set(found), set(expected))

  def testAllVisible(self):
    files = ["a", "b", "c"]
    expected = files
    self._test(files, expected)

  def testNoneVisible(self):
    files = [".a", ".b", ".c"]
    expected = []
    self._test(files, expected)

  def testSomeVisible(self):
    files = ["a", "b", ".c"]
    expected = ["a", "b"]
    self._test(files, expected)

  def testNonAbsolutePath(self):
    self.failUnlessRaises(errors.ProgrammerError, utils.ListVisibleFiles,
                          "abc")

  def testNonNormalizedPath(self):
    self.failUnlessRaises(errors.ProgrammerError, utils.ListVisibleFiles,
                          "/bin/../tmp")

  def testMountpoint(self):
    lvfmp_fn = compat.partial(utils.ListVisibleFiles,
                              _is_mountpoint=lambda _: True)
    self.assertEqual(lvfmp_fn(self.path), [])

    # Create "lost+found" as a regular file
    self._CreateFiles(["foo", "bar", ".baz", "lost+found"])
    self.assertEqual(set(lvfmp_fn(self.path)),
                     set(["foo", "bar", "lost+found"]))

    # Replace "lost+found" with a directory
    laf_path = utils.PathJoin(self.path, "lost+found")
    utils.RemoveFile(laf_path)
    os.mkdir(laf_path)
    self.assertEqual(set(lvfmp_fn(self.path)), set(["foo", "bar"]))

  def testLostAndFoundNoMountpoint(self):
    files = ["foo", "bar", ".Hello World", "lost+found"]
    expected = ["foo", "bar", "lost+found"]
    self._test(files, expected)


class TestWriteFile(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpdir = None
    self.tfile = tempfile.NamedTemporaryFile()
    self.did_pre = False
    self.did_post = False
    self.did_write = False

  def tearDown(self):
    testutils.GanetiTestCase.tearDown(self)
    if self.tmpdir:
      shutil.rmtree(self.tmpdir)

  def markPre(self, fd):
    self.did_pre = True

  def markPost(self, fd):
    self.did_post = True

  def markWrite(self, fd):
    self.did_write = True

  def testWrite(self):
    data = "abc"
    utils.WriteFile(self.tfile.name, data=data)
    self.assertEqual(utils.ReadFile(self.tfile.name), data)

  def testWriteSimpleUnicode(self):
    data = u"abc"
    utils.WriteFile(self.tfile.name, data=data)
    self.assertEqual(utils.ReadFile(self.tfile.name), data)

  def testErrors(self):
    self.assertRaises(errors.ProgrammerError, utils.WriteFile,
                      self.tfile.name, data="test", fn=lambda fd: None)
    self.assertRaises(errors.ProgrammerError, utils.WriteFile, self.tfile.name)
    self.assertRaises(errors.ProgrammerError, utils.WriteFile,
                      self.tfile.name, data="test", atime=0)
    self.assertRaises(errors.ProgrammerError, utils.WriteFile, self.tfile.name,
                      mode=0400, keep_perms=utils.KP_ALWAYS)
    self.assertRaises(errors.ProgrammerError, utils.WriteFile, self.tfile.name,
                      uid=0, keep_perms=utils.KP_ALWAYS)
    self.assertRaises(errors.ProgrammerError, utils.WriteFile, self.tfile.name,
                      gid=0, keep_perms=utils.KP_ALWAYS)
    self.assertRaises(errors.ProgrammerError, utils.WriteFile, self.tfile.name,
                      mode=0400, uid=0, keep_perms=utils.KP_ALWAYS)

  def testPreWrite(self):
    utils.WriteFile(self.tfile.name, data="", prewrite=self.markPre)
    self.assertTrue(self.did_pre)
    self.assertFalse(self.did_post)
    self.assertFalse(self.did_write)

  def testPostWrite(self):
    utils.WriteFile(self.tfile.name, data="", postwrite=self.markPost)
    self.assertFalse(self.did_pre)
    self.assertTrue(self.did_post)
    self.assertFalse(self.did_write)

  def testWriteFunction(self):
    utils.WriteFile(self.tfile.name, fn=self.markWrite)
    self.assertFalse(self.did_pre)
    self.assertFalse(self.did_post)
    self.assertTrue(self.did_write)

  def testDryRun(self):
    orig = "abc"
    self.tfile.write(orig)
    self.tfile.flush()
    utils.WriteFile(self.tfile.name, data="hello", dry_run=True)
    self.assertEqual(utils.ReadFile(self.tfile.name), orig)

  def testTimes(self):
    f = self.tfile.name
    for at, mt in [(0, 0), (1000, 1000), (2000, 3000),
                   (int(time.time()), 5000)]:
      utils.WriteFile(f, data="hello", atime=at, mtime=mt)
      st = os.stat(f)
      self.assertEqual(st.st_atime, at)
      self.assertEqual(st.st_mtime, mt)

  def testNoClose(self):
    data = "hello"
    self.assertEqual(utils.WriteFile(self.tfile.name, data="abc"), None)
    fd = utils.WriteFile(self.tfile.name, data=data, close=False)
    try:
      os.lseek(fd, 0, 0)
      self.assertEqual(os.read(fd, 4096), data)
    finally:
      os.close(fd)

  def testNoLeftovers(self):
    self.tmpdir = tempfile.mkdtemp()
    self.assertEqual(utils.WriteFile(utils.PathJoin(self.tmpdir, "test"),
                                     data="abc"),
                     None)
    self.assertEqual(os.listdir(self.tmpdir), ["test"])

  def testFailRename(self):
    self.tmpdir = tempfile.mkdtemp()
    target = utils.PathJoin(self.tmpdir, "target")
    os.mkdir(target)
    self.assertRaises(OSError, utils.WriteFile, target, data="abc")
    self.assertTrue(os.path.isdir(target))
    self.assertEqual(os.listdir(self.tmpdir), ["target"])
    self.assertFalse(os.listdir(target))

  def testFailRenameDryRun(self):
    self.tmpdir = tempfile.mkdtemp()
    target = utils.PathJoin(self.tmpdir, "target")
    os.mkdir(target)
    self.assertEqual(utils.WriteFile(target, data="abc", dry_run=True), None)
    self.assertTrue(os.path.isdir(target))
    self.assertEqual(os.listdir(self.tmpdir), ["target"])
    self.assertFalse(os.listdir(target))

  def testBackup(self):
    self.tmpdir = tempfile.mkdtemp()
    testfile = utils.PathJoin(self.tmpdir, "test")

    self.assertEqual(utils.WriteFile(testfile, data="foo", backup=True), None)
    self.assertEqual(utils.ReadFile(testfile), "foo")
    self.assertEqual(os.listdir(self.tmpdir), ["test"])

    # Write again
    assert os.path.isfile(testfile)
    self.assertEqual(utils.WriteFile(testfile, data="bar", backup=True), None)
    self.assertEqual(utils.ReadFile(testfile), "bar")
    self.assertEqual(len(glob.glob("%s.backup*" % testfile)), 1)
    self.assertTrue("test" in os.listdir(self.tmpdir))
    self.assertEqual(len(os.listdir(self.tmpdir)), 2)

    # Write again as dry-run
    assert os.path.isfile(testfile)
    self.assertEqual(utils.WriteFile(testfile, data="000", backup=True,
                                     dry_run=True),
                     None)
    self.assertEqual(utils.ReadFile(testfile), "bar")
    self.assertEqual(len(glob.glob("%s.backup*" % testfile)), 1)
    self.assertTrue("test" in os.listdir(self.tmpdir))
    self.assertEqual(len(os.listdir(self.tmpdir)), 2)

  def testFileMode(self):
    self.tmpdir = tempfile.mkdtemp()
    target = utils.PathJoin(self.tmpdir, "target")
    self.assertRaises(OSError, utils.WriteFile, target, data="data",
                      keep_perms=utils.KP_ALWAYS)
    # All masks have only user bits set, to avoid interactions with umask
    utils.WriteFile(target, data="data", mode=0200)
    self.assertFileMode(target, 0200)
    utils.WriteFile(target, data="data", mode=0400,
                    keep_perms=utils.KP_IF_EXISTS)
    self.assertFileMode(target, 0200)
    utils.WriteFile(target, data="data", keep_perms=utils.KP_ALWAYS)
    self.assertFileMode(target, 0200)
    utils.WriteFile(target, data="data", mode=0700)
    self.assertFileMode(target, 0700)

  def testNewFileMode(self):
    self.tmpdir = tempfile.mkdtemp()
    target = utils.PathJoin(self.tmpdir, "target")
    utils.WriteFile(target, data="data", mode=0400,
                    keep_perms=utils.KP_IF_EXISTS)
    self.assertFileMode(target, 0400)

class TestFileID(testutils.GanetiTestCase):
  def testEquality(self):
    name = self._CreateTempFile()
    oldi = utils.GetFileID(path=name)
    self.failUnless(utils.VerifyFileID(oldi, oldi))

  def testUpdate(self):
    name = self._CreateTempFile()
    oldi = utils.GetFileID(path=name)
    fd = os.open(name, os.O_RDWR)
    try:
      newi = utils.GetFileID(fd=fd)
      self.failUnless(utils.VerifyFileID(oldi, newi))
      self.failUnless(utils.VerifyFileID(newi, oldi))
    finally:
      os.close(fd)

  def testWriteFile(self):
    name = self._CreateTempFile()
    oldi = utils.GetFileID(path=name)
    mtime = oldi[2]
    os.utime(name, (mtime + 10, mtime + 10))
    self.assertRaises(errors.LockError, utils.SafeWriteFile, name,
                      oldi, data="")
    os.utime(name, (mtime - 10, mtime - 10))
    utils.SafeWriteFile(name, oldi, data="")
    oldi = utils.GetFileID(path=name)
    mtime = oldi[2]
    os.utime(name, (mtime + 10, mtime + 10))
    # this doesn't raise, since we passed None
    utils.SafeWriteFile(name, None, data="")

  def testError(self):
    t = tempfile.NamedTemporaryFile()
    self.assertRaises(errors.ProgrammerError, utils.GetFileID,
                      path=t.name, fd=t.fileno())


class TestRemoveFile(unittest.TestCase):
  """Test case for the RemoveFile function"""

  def setUp(self):
    """Create a temp dir and file for each case"""
    self.tmpdir = tempfile.mkdtemp("", "ganeti-unittest-")
    fd, self.tmpfile = tempfile.mkstemp("", "", self.tmpdir)
    os.close(fd)

  def tearDown(self):
    if os.path.exists(self.tmpfile):
      os.unlink(self.tmpfile)
    os.rmdir(self.tmpdir)

  def testIgnoreDirs(self):
    """Test that RemoveFile() ignores directories"""
    self.assertEqual(None, utils.RemoveFile(self.tmpdir))

  def testIgnoreNotExisting(self):
    """Test that RemoveFile() ignores non-existing files"""
    utils.RemoveFile(self.tmpfile)
    utils.RemoveFile(self.tmpfile)

  def testRemoveFile(self):
    """Test that RemoveFile does remove a file"""
    utils.RemoveFile(self.tmpfile)
    if os.path.exists(self.tmpfile):
      self.fail("File '%s' not removed" % self.tmpfile)

  def testRemoveSymlink(self):
    """Test that RemoveFile does remove symlinks"""
    symlink = self.tmpdir + "/symlink"
    os.symlink("no-such-file", symlink)
    utils.RemoveFile(symlink)
    if os.path.exists(symlink):
      self.fail("File '%s' not removed" % symlink)
    os.symlink(self.tmpfile, symlink)
    utils.RemoveFile(symlink)
    if os.path.exists(symlink):
      self.fail("File '%s' not removed" % symlink)


class TestRemoveDir(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    try:
      shutil.rmtree(self.tmpdir)
    except EnvironmentError:
      pass

  def testEmptyDir(self):
    utils.RemoveDir(self.tmpdir)
    self.assertFalse(os.path.isdir(self.tmpdir))

  def testNonEmptyDir(self):
    self.tmpfile = os.path.join(self.tmpdir, "test1")
    open(self.tmpfile, "w").close()
    self.assertRaises(EnvironmentError, utils.RemoveDir, self.tmpdir)


class TestRename(unittest.TestCase):
  """Test case for RenameFile"""

  def setUp(self):
    """Create a temporary directory"""
    self.tmpdir = tempfile.mkdtemp()
    self.tmpfile = os.path.join(self.tmpdir, "test1")

    # Touch the file
    open(self.tmpfile, "w").close()

  def tearDown(self):
    """Remove temporary directory"""
    shutil.rmtree(self.tmpdir)

  def testSimpleRename1(self):
    """Simple rename 1"""
    utils.RenameFile(self.tmpfile, os.path.join(self.tmpdir, "xyz"))
    self.assert_(os.path.isfile(os.path.join(self.tmpdir, "xyz")))

  def testSimpleRename2(self):
    """Simple rename 2"""
    utils.RenameFile(self.tmpfile, os.path.join(self.tmpdir, "xyz"),
                     mkdir=True)
    self.assert_(os.path.isfile(os.path.join(self.tmpdir, "xyz")))

  def testRenameMkdir(self):
    """Rename with mkdir"""
    utils.RenameFile(self.tmpfile, os.path.join(self.tmpdir, "test/xyz"),
                     mkdir=True)
    self.assert_(os.path.isdir(os.path.join(self.tmpdir, "test")))
    self.assert_(os.path.isfile(os.path.join(self.tmpdir, "test/xyz")))

    self.assertRaises(EnvironmentError, utils.RenameFile,
                      os.path.join(self.tmpdir, "test/xyz"),
                      os.path.join(self.tmpdir, "test/foo/bar/baz"),
                      mkdir=True)

    self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "test/xyz")))
    self.assertFalse(os.path.exists(os.path.join(self.tmpdir, "test/foo/bar")))
    self.assertFalse(os.path.exists(os.path.join(self.tmpdir,
                                                 "test/foo/bar/baz")))


class TestMakedirs(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testNonExisting(self):
    path = utils.PathJoin(self.tmpdir, "foo")
    utils.Makedirs(path)
    self.assert_(os.path.isdir(path))

  def testExisting(self):
    path = utils.PathJoin(self.tmpdir, "foo")
    os.mkdir(path)
    utils.Makedirs(path)
    self.assert_(os.path.isdir(path))

  def testRecursiveNonExisting(self):
    path = utils.PathJoin(self.tmpdir, "foo/bar/baz")
    utils.Makedirs(path)
    self.assert_(os.path.isdir(path))

  def testRecursiveExisting(self):
    path = utils.PathJoin(self.tmpdir, "B/moo/xyz")
    self.assertFalse(os.path.exists(path))
    os.mkdir(utils.PathJoin(self.tmpdir, "B"))
    utils.Makedirs(path)
    self.assert_(os.path.isdir(path))


class TestEnsureDirs(unittest.TestCase):
  """Tests for EnsureDirs"""

  def setUp(self):
    self.dir = tempfile.mkdtemp()
    self.old_umask = os.umask(0777)

  def testEnsureDirs(self):
    utils.EnsureDirs([
        (utils.PathJoin(self.dir, "foo"), 0777),
        (utils.PathJoin(self.dir, "bar"), 0000),
        ])
    self.assertEquals(os.stat(utils.PathJoin(self.dir, "foo"))[0] & 0777, 0777)
    self.assertEquals(os.stat(utils.PathJoin(self.dir, "bar"))[0] & 0777, 0000)

  def tearDown(self):
    os.rmdir(utils.PathJoin(self.dir, "foo"))
    os.rmdir(utils.PathJoin(self.dir, "bar"))
    os.rmdir(self.dir)
    os.umask(self.old_umask)


class TestIsNormAbsPath(unittest.TestCase):
  """Testing case for IsNormAbsPath"""

  def _pathTestHelper(self, path, result):
    if result:
      self.assert_(utils.IsNormAbsPath(path),
          msg="Path %s should result absolute and normalized" % path)
    else:
      self.assertFalse(utils.IsNormAbsPath(path),
          msg="Path %s should not result absolute and normalized" % path)

  def testBase(self):
    self._pathTestHelper("/etc", True)
    self._pathTestHelper("/srv", True)
    self._pathTestHelper("etc", False)
    self._pathTestHelper("/etc/../root", False)
    self._pathTestHelper("/etc/", False)

  def testSlashes(self):
    # Root directory
    self._pathTestHelper("/", True)

    # POSIX' "implementation-defined" double slashes
    self._pathTestHelper("//", True)

    # Three and more slashes count as one, so the path is not normalized
    for i in range(3, 10):
      self._pathTestHelper("/" * i, False)


class TestIsBelowDir(unittest.TestCase):
  """Testing case for IsBelowDir"""

  def testExactlyTheSame(self):
    self.assertFalse(utils.IsBelowDir("/a/b", "/a/b"))
    self.assertFalse(utils.IsBelowDir("/a/b", "/a/b/"))
    self.assertFalse(utils.IsBelowDir("/a/b/", "/a/b"))
    self.assertFalse(utils.IsBelowDir("/a/b/", "/a/b/"))

  def testSamePrefix(self):
    self.assertTrue(utils.IsBelowDir("/a/b", "/a/b/c"))
    self.assertTrue(utils.IsBelowDir("/a/b/", "/a/b/e"))

  def testSamePrefixButDifferentDir(self):
    self.assertFalse(utils.IsBelowDir("/a/b", "/a/bc/d"))
    self.assertFalse(utils.IsBelowDir("/a/b/", "/a/bc/e"))

  def testSamePrefixButDirTraversal(self):
    self.assertFalse(utils.IsBelowDir("/a/b", "/a/b/../c"))
    self.assertFalse(utils.IsBelowDir("/a/b/", "/a/b/../d"))

  def testSamePrefixAndTraversal(self):
    self.assertTrue(utils.IsBelowDir("/a/b", "/a/b/c/../d"))
    self.assertTrue(utils.IsBelowDir("/a/b", "/a/b/c/./e"))
    self.assertTrue(utils.IsBelowDir("/a/b", "/a/b/../b/./e"))

  def testBothAbsPath(self):
    self.assertRaises(ValueError, utils.IsBelowDir, "/a/b/c", "d")
    self.assertRaises(ValueError, utils.IsBelowDir, "a/b/c", "/d")
    self.assertRaises(ValueError, utils.IsBelowDir, "a/b/c", "d")
    self.assertRaises(ValueError, utils.IsBelowDir, "", "/")
    self.assertRaises(ValueError, utils.IsBelowDir, "/", "")

  def testRoot(self):
    self.assertFalse(utils.IsBelowDir("/", "/"))

    for i in ["/a", "/tmp", "/tmp/foo/bar", "/tmp/"]:
      self.assertTrue(utils.IsBelowDir("/", i))

  def testSlashes(self):
    # In POSIX a double slash is "implementation-defined".
    self.assertFalse(utils.IsBelowDir("//", "//"))
    self.assertFalse(utils.IsBelowDir("//", "/tmp"))
    self.assertTrue(utils.IsBelowDir("//tmp", "//tmp/x"))

    # Three (or more) slashes count as one
    self.assertFalse(utils.IsBelowDir("/", "///"))
    self.assertTrue(utils.IsBelowDir("/", "///tmp"))
    self.assertTrue(utils.IsBelowDir("/tmp", "///tmp/a/b"))


class TestPathJoin(unittest.TestCase):
  """Testing case for PathJoin"""

  def testBasicItems(self):
    mlist = ["/a", "b", "c"]
    self.failUnlessEqual(utils.PathJoin(*mlist), "/".join(mlist))

  def testNonAbsPrefix(self):
    self.failUnlessRaises(ValueError, utils.PathJoin, "a", "b")

  def testBackTrack(self):
    self.failUnlessRaises(ValueError, utils.PathJoin, "/a", "b/../c")

  def testMultiAbs(self):
    self.failUnlessRaises(ValueError, utils.PathJoin, "/a", "/b")


class TestTailFile(testutils.GanetiTestCase):
  """Test case for the TailFile function"""

  def testEmpty(self):
    fname = self._CreateTempFile()
    self.failUnlessEqual(utils.TailFile(fname), [])
    self.failUnlessEqual(utils.TailFile(fname, lines=25), [])

  def testAllLines(self):
    data = ["test %d" % i for i in range(30)]
    for i in range(30):
      fname = self._CreateTempFile()
      fd = open(fname, "w")
      fd.write("\n".join(data[:i]))
      if i > 0:
        fd.write("\n")
      fd.close()
      self.failUnlessEqual(utils.TailFile(fname, lines=i), data[:i])

  def testPartialLines(self):
    data = ["test %d" % i for i in range(30)]
    fname = self._CreateTempFile()
    fd = open(fname, "w")
    fd.write("\n".join(data))
    fd.write("\n")
    fd.close()
    for i in range(1, 30):
      self.failUnlessEqual(utils.TailFile(fname, lines=i), data[-i:])

  def testBigFile(self):
    data = ["test %d" % i for i in range(30)]
    fname = self._CreateTempFile()
    fd = open(fname, "w")
    fd.write("X" * 1048576)
    fd.write("\n")
    fd.write("\n".join(data))
    fd.write("\n")
    fd.close()
    for i in range(1, 30):
      self.failUnlessEqual(utils.TailFile(fname, lines=i), data[-i:])


class TestPidFileFunctions(unittest.TestCase):
  """Tests for WritePidFile and ReadPidFile"""

  def setUp(self):
    self.dir = tempfile.mkdtemp()
    self.f_dpn = lambda name: os.path.join(self.dir, "%s.pid" % name)

  def testPidFileFunctions(self):
    pid_file = self.f_dpn("test")
    fd = utils.WritePidFile(self.f_dpn("test"))
    self.failUnless(os.path.exists(pid_file),
                    "PID file should have been created")
    read_pid = utils.ReadPidFile(pid_file)
    self.failUnlessEqual(read_pid, os.getpid())
    self.failUnless(utils.IsProcessAlive(read_pid))
    self.failUnlessRaises(errors.PidFileLockError, utils.WritePidFile,
                          self.f_dpn("test"))
    os.close(fd)
    utils.RemoveFile(self.f_dpn("test"))
    self.failIf(os.path.exists(pid_file),
                "PID file should not exist anymore")
    self.failUnlessEqual(utils.ReadPidFile(pid_file), 0,
                         "ReadPidFile should return 0 for missing pid file")
    fh = open(pid_file, "w")
    fh.write("blah\n")
    fh.close()
    self.failUnlessEqual(utils.ReadPidFile(pid_file), 0,
                         "ReadPidFile should return 0 for invalid pid file")
    # but now, even with the file existing, we should be able to lock it
    fd = utils.WritePidFile(self.f_dpn("test"))
    os.close(fd)
    utils.RemoveFile(self.f_dpn("test"))
    self.failIf(os.path.exists(pid_file),
                "PID file should not exist anymore")

  def testKill(self):
    pid_file = self.f_dpn("child")
    r_fd, w_fd = os.pipe()
    new_pid = os.fork()
    if new_pid == 0: #child
      utils.WritePidFile(self.f_dpn("child"))
      os.write(w_fd, "a")
      signal.pause()
      os._exit(0)
      return
    # else we are in the parent
    # wait until the child has written the pid file
    os.read(r_fd, 1)
    read_pid = utils.ReadPidFile(pid_file)
    self.failUnlessEqual(read_pid, new_pid)
    self.failUnless(utils.IsProcessAlive(new_pid))

    # Try writing to locked file
    try:
      utils.WritePidFile(pid_file)
    except errors.PidFileLockError, err:
      errmsg = str(err)
      self.assertTrue(errmsg.endswith(" %s" % new_pid),
                      msg=("Error message ('%s') didn't contain correct"
                           " PID (%s)" % (errmsg, new_pid)))
    else:
      self.fail("Writing to locked file didn't fail")

    utils.KillProcess(new_pid, waitpid=True)
    self.failIf(utils.IsProcessAlive(new_pid))
    utils.RemoveFile(self.f_dpn("child"))
    self.failUnlessRaises(errors.ProgrammerError, utils.KillProcess, 0)

  def testExceptionType(self):
    # Make sure the PID lock error is a subclass of LockError in case some code
    # depends on it
    self.assertTrue(issubclass(errors.PidFileLockError, errors.LockError))

  def tearDown(self):
    shutil.rmtree(self.dir)


class TestNewUUID(unittest.TestCase):
  """Test case for NewUUID"""

  def runTest(self):
    self.failUnless(utils.UUID_RE.match(utils.NewUUID()))


def _MockStatResult(cb, mode, uid, gid):
  def _fn(path):
    if cb:
      cb()
    return {
      stat.ST_MODE: mode,
      stat.ST_UID: uid,
      stat.ST_GID: gid,
      }
  return _fn


def _RaiseNoEntError():
  raise EnvironmentError(errno.ENOENT, "not found")


def _OtherStatRaise():
  raise EnvironmentError()


class TestPermissionEnforcements(unittest.TestCase):
  UID_A = 16024
  UID_B = 25850
  GID_A = 14028
  GID_B = 29801

  def setUp(self):
    self._chown_calls = []
    self._chmod_calls = []
    self._mkdir_calls = []

  def tearDown(self):
    self.assertRaises(IndexError, self._mkdir_calls.pop)
    self.assertRaises(IndexError, self._chmod_calls.pop)
    self.assertRaises(IndexError, self._chown_calls.pop)

  def _FakeMkdir(self, path):
    self._mkdir_calls.append(path)

  def _FakeChown(self, path, uid, gid):
    self._chown_calls.append((path, uid, gid))

  def _ChmodWrapper(self, cb):
    def _fn(path, mode):
      self._chmod_calls.append((path, mode))
      if cb:
        cb()
    return _fn

  def _VerifyPerm(self, path, mode, uid=-1, gid=-1):
    self.assertEqual(path, "/ganeti-qa-non-test")
    self.assertEqual(mode, 0700)
    self.assertEqual(uid, self.UID_A)
    self.assertEqual(gid, self.GID_A)

  def testMakeDirWithPerm(self):
    is_dir_stat = _MockStatResult(None, stat.S_IFDIR, 0, 0)
    utils.MakeDirWithPerm("/ganeti-qa-non-test", 0700, self.UID_A, self.GID_A,
                          _lstat_fn=is_dir_stat, _perm_fn=self._VerifyPerm)

  def testDirErrors(self):
    self.assertRaises(errors.GenericError, utils.MakeDirWithPerm,
                      "/ganeti-qa-non-test", 0700, 0, 0,
                      _lstat_fn=_MockStatResult(None, 0, 0, 0))
    self.assertRaises(IndexError, self._mkdir_calls.pop)

    other_stat_raise = _MockStatResult(_OtherStatRaise, stat.S_IFDIR, 0, 0)
    self.assertRaises(errors.GenericError, utils.MakeDirWithPerm,
                      "/ganeti-qa-non-test", 0700, 0, 0,
                      _lstat_fn=other_stat_raise)
    self.assertRaises(IndexError, self._mkdir_calls.pop)

    non_exist_stat = _MockStatResult(_RaiseNoEntError, stat.S_IFDIR, 0, 0)
    utils.MakeDirWithPerm("/ganeti-qa-non-test", 0700, self.UID_A, self.GID_A,
                          _lstat_fn=non_exist_stat, _mkdir_fn=self._FakeMkdir,
                          _perm_fn=self._VerifyPerm)
    self.assertEqual(self._mkdir_calls.pop(0), "/ganeti-qa-non-test")

  def testEnforcePermissionNoEnt(self):
    self.assertRaises(errors.GenericError, utils.EnforcePermission,
                      "/ganeti-qa-non-test", 0600,
                      _chmod_fn=NotImplemented, _chown_fn=NotImplemented,
                      _stat_fn=_MockStatResult(_RaiseNoEntError, 0, 0, 0))

  def testEnforcePermissionNoEntMustNotExist(self):
    utils.EnforcePermission("/ganeti-qa-non-test", 0600, must_exist=False,
                            _chmod_fn=NotImplemented,
                            _chown_fn=NotImplemented,
                            _stat_fn=_MockStatResult(_RaiseNoEntError,
                                                          0, 0, 0))

  def testEnforcePermissionOtherErrorMustNotExist(self):
    self.assertRaises(errors.GenericError, utils.EnforcePermission,
                      "/ganeti-qa-non-test", 0600, must_exist=False,
                      _chmod_fn=NotImplemented, _chown_fn=NotImplemented,
                      _stat_fn=_MockStatResult(_OtherStatRaise, 0, 0, 0))

  def testEnforcePermissionNoChanges(self):
    utils.EnforcePermission("/ganeti-qa-non-test", 0600,
                            _stat_fn=_MockStatResult(None, 0600, 0, 0),
                            _chmod_fn=self._ChmodWrapper(None),
                            _chown_fn=self._FakeChown)

  def testEnforcePermissionChangeMode(self):
    utils.EnforcePermission("/ganeti-qa-non-test", 0444,
                            _stat_fn=_MockStatResult(None, 0600, 0, 0),
                            _chmod_fn=self._ChmodWrapper(None),
                            _chown_fn=self._FakeChown)
    self.assertEqual(self._chmod_calls.pop(0), ("/ganeti-qa-non-test", 0444))

  def testEnforcePermissionSetUidGid(self):
    utils.EnforcePermission("/ganeti-qa-non-test", 0600,
                            uid=self.UID_B, gid=self.GID_B,
                            _stat_fn=_MockStatResult(None, 0600,
                                                     self.UID_A,
                                                     self.GID_A),
                            _chmod_fn=self._ChmodWrapper(None),
                            _chown_fn=self._FakeChown)
    self.assertEqual(self._chown_calls.pop(0),
                     ("/ganeti-qa-non-test", self.UID_B, self.GID_B))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
