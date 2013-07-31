{-# LANGUAGE OverloadedStrings #-}
{-| Diskstats proc file parser

This module holds the definition of the parser that extracts status
information about the disks of the system from the @/proc/diskstats@ file.

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
module Ganeti.Storage.Diskstats.Parser (diskstatsParser) where

import Control.Applicative ((<*>), (<*), (<$>))
import qualified Data.Attoparsec.Text as A
import qualified Data.Attoparsec.Combinator as AC
import Data.Attoparsec.Text (Parser)

import Ganeti.Parsers
import Ganeti.Storage.Diskstats.Types

-- * Parser implementation

-- | The parser for one line of the diskstatus file.
oneDiskstatsParser :: Parser Diskstats
oneDiskstatsParser =
  let majorP = numberP
      minorP = numberP
      nameP = stringP
      readsNumP = numberP
      mergedReadsP = numberP
      secReadP = numberP
      timeReadP = numberP
      writesP = numberP
      mergedWritesP = numberP
      secWrittenP = numberP
      timeWriteP = numberP
      iosP = numberP
      timeIOP = numberP
      wIOmillisP = numberP
  in
    Diskstats <$> majorP <*> minorP <*> nameP <*> readsNumP <*> mergedReadsP
      <*> secReadP <*> timeReadP <*> writesP <*> mergedWritesP <*> secWrittenP
      <*> timeWriteP <*> iosP <*> timeIOP <*> wIOmillisP <* A.endOfLine

-- | The parser for a whole diskstatus file.
diskstatsParser :: Parser [Diskstats]
diskstatsParser = oneDiskstatsParser `AC.manyTill` A.endOfInput
