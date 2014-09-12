{-# LANGUAGE TemplateHaskell #-}

{-| Unittests for Attoparsec support for unicode -}

{-

Copyright (C) 2012 Google Inc.
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

module Test.Ganeti.Attoparsec (testAttoparsec) where

import Test.HUnit

import Test.Ganeti.TestHelper

import qualified Data.Attoparsec.Text as A
import Data.Attoparsec.Text (Parser)
import Data.Text (pack, unpack)

-- | Unicode test string, first part.
part1 :: String
part1 = "äßĉ"

-- | Unicode test string, second part.
part2 :: String
part2 = "ðèق"

-- | Simple parser able to split a string in two parts, name and
-- value, separated by a '=' sign.
simpleParser :: Parser (String, String)
simpleParser = do
  n <- A.takeTill (\c -> A.isHorizontalSpace c || c == '=')
  A.skipWhile A.isHorizontalSpace
  _ <- A.char '='
  A.skipWhile A.isHorizontalSpace
  v <- A.takeTill A.isEndOfLine
  return (unpack n, unpack v)

{-# ANN case_unicodeParsing "HLint: ignore Use camelCase" #-}
-- | Tests whether a Unicode string is still Unicode after being
-- parsed.
case_unicodeParsing :: Assertion
case_unicodeParsing =
  case A.parseOnly simpleParser text of
    Right (name, value) -> do
      assertEqual "name part" part1 name
      assertEqual "value part" part2 value
    Left msg -> assertFailure $ "Failed to parse: " ++ msg
  where text = Data.Text.pack $ part1 ++ "  = \t" ++ part2

testSuite "Attoparsec"
          [ 'case_unicodeParsing
          ]
