{-# LANGUAGE TemplateHaskell #-}

{-| Unittests for Attoparsec support for unicode -}

{-

Copyright (C) 2012 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}

module Test.Ganeti.Attoparsec (testAttoparsec) where

import Test.QuickCheck

import Test.Ganeti.TestHelper
import Test.Ganeti.TestCommon

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

-- | Tests whether a Unicode string is still Unicode after being
-- parsed.
prop_parserSupportsUnicode :: Property
prop_parserSupportsUnicode = case A.parseOnly simpleParser text of
    Right (name, value) -> (name ==? part1) .&&. (value ==? part2)
    Left msg -> failTest $ "Failed to parse: " ++ msg
  where text = Data.Text.pack $ part1 ++ "  = \t" ++ part2

testSuite "Attoparsec"
          [ 'prop_parserSupportsUnicode
          ]
