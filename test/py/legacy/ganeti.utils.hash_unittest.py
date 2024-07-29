#!/usr/bin/python3
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


"""Script for testing ganeti.utils.hash"""

import unittest
import random
import tempfile

from ganeti import constants
from ganeti import utils

import testutils


class TestHmacFunctions(unittest.TestCase):
  # Digests can be checked with "openssl sha1 -hmac $key"
  def testSha1Hmac(self):
    self.assertEqual(utils.Sha1Hmac("", ""),
                     "fbdb1d1b18aa6c08324b7d64b71fb76370690e1d")
    self.assertEqual(utils.Sha1Hmac("3YzMxZWE", "Hello World"),
                     "ef4f3bda82212ecb2f7ce868888a19092481f1fd")
    self.assertEqual(utils.Sha1Hmac("TguMTA2K", ""),
                     "f904c2476527c6d3e6609ab683c66fa0652cb1dc")

    longtext = 1500 * "The quick brown fox jumps over the lazy dog\n"
    self.assertEqual(utils.Sha1Hmac("3YzMxZWE", longtext),
                     "35901b9a3001a7cdcf8e0e9d7c2e79df2223af54")

  def testSha1HmacSalt(self):
    self.assertEqual(utils.Sha1Hmac("TguMTA2K", "", salt="abc0"),
                     "4999bf342470eadb11dfcd24ca5680cf9fd7cdce")
    self.assertEqual(utils.Sha1Hmac("TguMTA2K", "", salt="abc9"),
                     "17a4adc34d69c0d367d4ffbef96fd41d4df7a6e8")
    self.assertEqual(utils.Sha1Hmac("3YzMxZWE", "Hello World", salt="xyz0"),
                     "7f264f8114c9066afc9bb7636e1786d996d3cc0d")

  def testVerifySha1Hmac(self):
    self.assertTrue(utils.VerifySha1Hmac("", "", ("fbdb1d1b18aa6c08324b"
                                               "7d64b71fb76370690e1d")))
    self.assertTrue(utils.VerifySha1Hmac("TguMTA2K", "",
                                      ("f904c2476527c6d3e660"
                                       "9ab683c66fa0652cb1dc")))

    digest = "ef4f3bda82212ecb2f7ce868888a19092481f1fd"
    self.assertTrue(utils.VerifySha1Hmac("3YzMxZWE", "Hello World", digest))
    self.assertTrue(utils.VerifySha1Hmac("3YzMxZWE", "Hello World",
                                      digest.lower()))
    self.assertTrue(utils.VerifySha1Hmac("3YzMxZWE", "Hello World",
                                      digest.upper()))
    self.assertTrue(utils.VerifySha1Hmac("3YzMxZWE", "Hello World",
                                      digest.title()))

  def testVerifySha1HmacSalt(self):
    self.assertTrue(utils.VerifySha1Hmac("TguMTA2K", "",
                                      ("17a4adc34d69c0d367d4"
                                       "ffbef96fd41d4df7a6e8"),
                                      salt="abc9"))
    self.assertTrue(utils.VerifySha1Hmac("3YzMxZWE", "Hello World",
                                      ("7f264f8114c9066afc9b"
                                       "b7636e1786d996d3cc0d"),
                                      salt="xyz0"))


class TestFingerprintFiles(unittest.TestCase):
  def setUp(self):
    self.tmpfile = tempfile.NamedTemporaryFile()
    self.tmpfile2 = tempfile.NamedTemporaryFile()
    utils.WriteFile(self.tmpfile2.name, data="Hello World\n")
    self.results = {
      self.tmpfile.name: "da39a3ee5e6b4b0d3255bfef95601890afd80709",
      self.tmpfile2.name: "648a6a6ffffdaa0badb23b8baf90b6168dd16b3a",
      }

  def testSingleFile(self):
    self.assertEqual(utils.hash._FingerprintFile(self.tmpfile.name),
                     self.results[self.tmpfile.name])

    self.assertEqual(utils.hash._FingerprintFile("/no/such/file"), None)

  def testBigFile(self):
    self.tmpfile.write(b"A" * 8192)
    self.tmpfile.flush()
    self.assertEqual(utils.hash._FingerprintFile(self.tmpfile.name),
                     "35b6795ca20d6dc0aff8c7c110c96cd1070b8c38")

  def testMultiple(self):
    all_files = list(self.results)
    all_files.append("/no/such/file")
    self.assertEqual(utils.FingerprintFiles(list(self.results)), self.results)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
