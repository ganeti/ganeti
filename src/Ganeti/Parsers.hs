{-# LANGUAGE OverloadedStrings #-}
{-| Utility functions for several parsers

This module holds the definition for some utility functions for two
parsers.  The parser for the @/proc/stat@ file and the parser for the
@/proc/diskstats@ file.

-}
{-

Copyright (C) 2013 Google Inc.

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
module Ganeti.Parsers where

import Control.Applicative ((*>))
import qualified Data.Attoparsec.Text as A
import Data.Attoparsec.Text (Parser)
import Data.Text (unpack)

-- * Utility functions

-- | Our own space-skipping function, because A.skipSpace also skips
-- newline characters. It skips ZERO or more spaces, so it does not
-- fail if there are no spaces.
skipSpaces :: Parser ()
skipSpaces = A.skipWhile A.isHorizontalSpace

-- | A parser recognizing a number preceeded by spaces.
numberP :: Parser Int
numberP = skipSpaces *> A.decimal

-- | A parser recognizing a word preceded by spaces, and closed by a space.
stringP :: Parser String
stringP = skipSpaces *> fmap unpack (A.takeWhile $ not . A.isHorizontalSpace)
