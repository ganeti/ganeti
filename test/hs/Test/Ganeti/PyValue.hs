{-# LANGUAGE TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Unittests for Ganeti.Pyvalue

-}

{-

Copyright (C) 2019 Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

-}

module Test.Ganeti.PyValue
  ( testPyValue
  ) where

import Test.QuickCheck
import qualified Test.HUnit as HUnit

import Data.List
import qualified Data.ByteString as BS
import qualified Data.ByteString.UTF8 as UTF8
import qualified Data.ByteString.Base64 as B64

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon
import Test.Ganeti.Types ()

import Ganeti.PyValue

-- * Arbitrary instances

instance Arbitrary BS.ByteString where
  -- Generate valid UTF-8 strings without newlines, to make data exchange
  -- between Python and Haskell a bit easier.
  arbitrary = UTF8.fromString <$> arbitrary `suchThat` (not . isInfixOf "\n")

-- | Custom HUnit test to check the correspondence between ByteStrings and
-- Python bytes. We use ast.literal_eval to evaluate the byte literals and then
-- write the resulting bytestrings back to Haskell for comparison.
--
-- For the technical background of this unit test, check the documentation
-- of "case_py_compat_types" of test/hs/Test/Ganeti/Opcodes.hs
--
-- Note that System.Process.readProcessWithExitCode (used by runPython) returns
-- Python's stdout as a String, by calling hGetContents on the standard output
-- handle. This means that data is decoded using the system locale, making the
-- channel not 8-bit-clean when run with a non-UTF-8 locale (such as POSIX). We
-- could use System.Process.Typed to get past this problem, but that's an extra
-- dependency not used elsewhere. Instead we work around this issue by
-- base64-encoding the UTF-8 output on the Python side.
caseByteStringsToBytes :: HUnit.Assertion
caseByteStringsToBytes = do
  let num_bs = 500::Int
  bytestrings <- generate $ vectorOf num_bs (arbitrary::Gen BS.ByteString)
  let input = intercalate "\n" $ map showValue bytestrings
  py_stdout <-
    runPython "from ast import literal_eval\n\
              \import sys\n\
              \import base64\n\
              \for item in sys.stdin:\n\
              \  data = literal_eval(item)\n\
              \  sys.stdout.buffer.write(base64.b64encode(data) + b'\\n')"
              input
    >>= checkPythonResult
  let decoded = map (B64.decodeLenient . UTF8.fromString) $ lines py_stdout
  HUnit.assertEqual "Mismatch in number of returned bytestrings"
    (length decoded) (length bytestrings)
  mapM_ (uncurry (HUnit.assertEqual "Different result after encoding/decoding")
        ) $ zip bytestrings decoded


testSuite "PyValue"
  [ 'caseByteStringsToBytes
  ]
