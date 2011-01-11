#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.


"""Script for testing ganeti.utils.io"""

import os
import tempfile
import unittest
import shutil
import glob
import time
import signal

from ganeti import constants
from ganeti import utils
from ganeti import compat
from ganeti import errors

import testutils


class TestReadFile(testutils.GanetiTestCase):
  def testReadAll(self):
    data = utils.ReadFile(self._TestDataFilename("cert1.pem"))
    self.assertEqual(len(data), 814)

    h = compat.md5_hash()
    h.update(data)
    self.assertEqual(h.hexdigest(), "a491efb3efe56a0535f924d5f8680fd4")

  def testReadSize(self):
    data = utils.ReadFile(self._TestDataFilename("cert1.pem"),
                          size=100)
    self.assertEqual(len(data), 100)

    h = compat.md5_hash()
    h.update(data)
    self.assertEqual(h.hexdigest(), "893772354e4e690b9efd073eed433ce7")

  def testError(self):
    self.assertRaises(EnvironmentError, utils.ReadFile,
                      "/dev/null/does-not-exist")


class TestReadOneLineFile(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

  def testDefault(self):
    data = utils.ReadOneLineFile(self._TestDataFilename("cert1.pem"))
    self.assertEqual(len(data), 27)
    self.assertEqual(data, "-----BEGIN CERTIFICATE-----")

  def testNotStrict(self):
    data = utils.ReadOneLineFile(self._TestDataFilename("cert1.pem"),
                                 strict=False)
    self.assertEqual(len(data), 27)
    self.assertEqual(data, "-----BEGIN CERTIFICATE-----")

  def testStrictFailure(self):
    self.assertRaises(errors.GenericError, utils.ReadOneLineFile,
                      self._TestDataFilename("cert1.pem"), strict=True)

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


class TestWriteFile(unittest.TestCase):
  def setUp(self):
    self.tfile = tempfile.NamedTemporaryFile()
    self.did_pre = False
    self.did_post = False
    self.did_write = False

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

  def testErrors(self):
    self.assertRaises(errors.ProgrammerError, utils.WriteFile,
                      self.tfile.name, data="test", fn=lambda fd: None)
    self.assertRaises(errors.ProgrammerError, utils.WriteFile, self.tfile.name)
    self.assertRaises(errors.ProgrammerError, utils.WriteFile,
                      self.tfile.name, data="test", atime=0)

  def testCalls(self):
    utils.WriteFile(self.tfile.name, fn=self.markWrite,
                    prewrite=self.markPre, postwrite=self.markPost)
    self.assertTrue(self.did_pre)
    self.assertTrue(self.did_post)
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


class TestFileID(testutils.GanetiTestCase):
  def testEquality(self):
    name = self._CreateTempFile()
    oldi = utils.GetFileID(path=name)
    self.failUnless(utils.VerifyFileID(oldi, oldi))

  def testUpdate(self):
    name = self._CreateTempFile()
    oldi = utils.GetFileID(path=name)
    os.utime(name, None)
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
    self.tmpdir = tempfile.mkdtemp('', 'ganeti-unittest-')
    fd, self.tmpfile = tempfile.mkstemp('', '', self.tmpdir)
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

    utils.RenameFile(os.path.join(self.tmpdir, "test/xyz"),
                     os.path.join(self.tmpdir, "test/foo/bar/baz"),
                     mkdir=True)
    self.assert_(os.path.isdir(os.path.join(self.tmpdir, "test")))
    self.assert_(os.path.isdir(os.path.join(self.tmpdir, "test/foo/bar")))
    self.assert_(os.path.isfile(os.path.join(self.tmpdir, "test/foo/bar/baz")))


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
          "Path %s should result absolute and normalized" % path)
    else:
      self.assertFalse(utils.IsNormAbsPath(path),
          "Path %s should not result absolute and normalized" % path)

  def testBase(self):
    self._pathTestHelper("/etc", True)
    self._pathTestHelper("/srv", True)
    self._pathTestHelper("etc", False)
    self._pathTestHelper("/etc/../root", False)
    self._pathTestHelper("/etc/", False)


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
    pid_file = self.f_dpn('test')
    fd = utils.WritePidFile(self.f_dpn('test'))
    self.failUnless(os.path.exists(pid_file),
                    "PID file should have been created")
    read_pid = utils.ReadPidFile(pid_file)
    self.failUnlessEqual(read_pid, os.getpid())
    self.failUnless(utils.IsProcessAlive(read_pid))
    self.failUnlessRaises(errors.LockError, utils.WritePidFile,
                          self.f_dpn('test'))
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
    fd = utils.WritePidFile(self.f_dpn('test'))
    os.close(fd)
    utils.RemoveFile(self.f_dpn("test"))
    self.failIf(os.path.exists(pid_file),
                "PID file should not exist anymore")

  def testKill(self):
    pid_file = self.f_dpn('child')
    r_fd, w_fd = os.pipe()
    new_pid = os.fork()
    if new_pid == 0: #child
      utils.WritePidFile(self.f_dpn('child'))
      os.write(w_fd, 'a')
      signal.pause()
      os._exit(0)
      return
    # else we are in the parent
    # wait until the child has written the pid file
    os.read(r_fd, 1)
    read_pid = utils.ReadPidFile(pid_file)
    self.failUnlessEqual(read_pid, new_pid)
    self.failUnless(utils.IsProcessAlive(new_pid))
    utils.KillProcess(new_pid, waitpid=True)
    self.failIf(utils.IsProcessAlive(new_pid))
    utils.RemoveFile(self.f_dpn('child'))
    self.failUnlessRaises(errors.ProgrammerError, utils.KillProcess, 0)

  def tearDown(self):
    shutil.rmtree(self.dir)


class TestSshKeys(testutils.GanetiTestCase):
  """Test case for the AddAuthorizedKey function"""

  KEY_A = 'ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a'
  KEY_B = ('command="/usr/bin/fooserver -t --verbose",from="198.51.100.4" '
           'ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b')

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpname = self._CreateTempFile()
    handle = open(self.tmpname, 'w')
    try:
      handle.write("%s\n" % TestSshKeys.KEY_A)
      handle.write("%s\n" % TestSshKeys.KEY_B)
    finally:
      handle.close()

  def testAddingNewKey(self):
    utils.AddAuthorizedKey(self.tmpname,
                           'ssh-dss AAAAB3NzaC1kc3MAAACB root@test')

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n"
      "ssh-dss AAAAB3NzaC1kc3MAAACB root@test\n")

  def testAddingAlmostButNotCompletelyTheSameKey(self):
    utils.AddAuthorizedKey(self.tmpname,
        'ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@test')

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n"
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@test\n")

  def testAddingExistingKeyWithSomeMoreSpaces(self):
    utils.AddAuthorizedKey(self.tmpname,
        'ssh-dss  AAAAB3NzaC1w5256closdj32mZaQU   root@key-a')

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n")

  def testRemovingExistingKeyWithSomeMoreSpaces(self):
    utils.RemoveAuthorizedKey(self.tmpname,
        'ssh-dss  AAAAB3NzaC1w5256closdj32mZaQU   root@key-a')

    self.assertFileContent(self.tmpname,
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n")

  def testRemovingNonExistingKey(self):
    utils.RemoveAuthorizedKey(self.tmpname,
        'ssh-dss  AAAAB3Nsdfj230xxjxJjsjwjsjdjU   root@test')

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n")


class TestNewUUID(unittest.TestCase):
  """Test case for NewUUID"""

  def runTest(self):
    self.failUnless(utils.UUID_RE.match(utils.NewUUID()))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
